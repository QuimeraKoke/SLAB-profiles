"""Bulk ingest pipeline for `ExamTemplate.input_config['bulk_ingest']`.

Pure-Python orchestration in four steps — parse, match, transform, commit —
each exposed as its own function so they can be tested in isolation. The
`column_mapping` shape this code reads is documented on
`ExamTemplate.input_config` (see `backend/exams/models.py`).

The pipeline is segment-aware: when a `segment` block is present in the
mapping, multiple rows per player (e.g. P1 / P2) are collapsed into ONE
`ExamResult` per player by pattern-substituting `{segment}` in each
`field_map[*].template_key_pattern`. Without a segment block, rows still
collapse per player but `template_key` + optional `reduce` is required.
"""
from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from core.models import Category, Player, PlayerAlias
from events.models import Event
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate


class IngestError(ValueError):
    """Raised when the file or column_mapping can't be processed."""


# ---------- step 1: parse ----------

@dataclass
class ParsedFile:
    headers: list[str]
    rows: list[dict[str, Any]]  # header -> raw cell value


def parse_xlsx(file_bytes: bytes) -> ParsedFile:
    """Read xlsx/OOXML bytes and return whitespace-stripped headers + rows."""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except (InvalidFileException, OSError, KeyError, ValueError) as exc:
        raise IngestError(f"No se pudo leer el archivo: {exc}")

    sheet = workbook.active
    if sheet is None:
        raise IngestError("El archivo no tiene hojas legibles.")

    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise IngestError("El archivo está vacío.")

    headers = [str(cell).strip() if cell is not None else "" for cell in header_row]
    if not any(headers):
        raise IngestError("La primera fila debe contener encabezados.")

    rows: list[dict[str, Any]] = []
    for raw in rows_iter:
        if all(cell is None or (isinstance(cell, str) and not cell.strip()) for cell in raw):
            continue
        row = {header: value for header, value in zip(headers, raw) if header}
        rows.append(row)
    return ParsedFile(headers=headers, rows=rows)


# ---------- step 2: match ----------

@dataclass
class ResolvedRow:
    raw_player: str
    raw_segment: str | None
    segment_suffix: str | None       # the value-side of segment.values
    session_label: str | None
    player: Player | None
    match_strategy: str | None       # "alias" | "name" | None
    metric_values: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics. For tolerant alias / name comparison."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def _build_player_index(category: Category) -> tuple[dict[str, Player], dict[str, Player]]:
    """Build two normalized lookups: by alias value and by full name."""
    players = list(Player.objects.filter(category=category, is_active=True))
    aliases = (
        PlayerAlias.objects.filter(player__category=category, player__is_active=True)
        .select_related("player")
    )

    by_alias: dict[str, Player] = {}
    for alias in aliases:
        by_alias[_normalize(alias.value)] = alias.player

    by_name: dict[str, Player] = {}
    for p in players:
        by_name[_normalize(f"{p.first_name} {p.last_name}")] = p
    return by_alias, by_name


def match_rows(parsed: ParsedFile, mapping: dict, category: Category) -> list[ResolvedRow]:
    lookup = mapping.get("player_lookup") or {}
    player_col = (lookup.get("column") or "").strip()
    if not player_col:
        raise IngestError("column_mapping.player_lookup.column no está definido.")

    segment_cfg = mapping.get("segment")
    segment_col = (segment_cfg.get("column") or "").strip() if segment_cfg else None
    segment_values = segment_cfg.get("values", {}) if segment_cfg else {}

    session_cfg = mapping.get("session_label")
    session_col = (session_cfg.get("column") or "").strip() if session_cfg else None

    # Headers were already stripped at parse time; strip the mapping keys at
    # lookup time so a stray space in either side doesn't drop the column.
    field_columns = [
        (orig_col, orig_col.strip())
        for orig_col in (mapping.get("field_map") or {}).keys()
    ]
    by_alias, by_name = _build_player_index(category)

    resolved: list[ResolvedRow] = []
    for row in parsed.rows:
        raw_player = row.get(player_col)
        if raw_player is None or (isinstance(raw_player, str) and not raw_player.strip()):
            continue
        raw_player_str = str(raw_player).strip()

        norm = _normalize(raw_player_str)
        player = by_alias.get(norm)
        strategy = "alias" if player else None
        if not player:
            player = by_name.get(norm)
            strategy = "name" if player else None

        raw_segment = row.get(segment_col) if segment_col else None
        raw_segment_str = str(raw_segment).strip() if raw_segment is not None else None
        seg_suffix = segment_values.get(raw_segment_str) if raw_segment_str else None

        session = None
        if session_col:
            v = row.get(session_col)
            session = str(v).strip() if v is not None else None

        # Preserve the original (with-space) key so transform_rows can index
        # field_map by the same string the admin saved.
        metric_values = {
            orig: row.get(stripped)
            for orig, stripped in field_columns
            if stripped in row
        }

        rr = ResolvedRow(
            raw_player=raw_player_str,
            raw_segment=raw_segment_str,
            segment_suffix=seg_suffix,
            session_label=session,
            player=player,
            match_strategy=strategy,
            metric_values=metric_values,
        )
        if not player:
            rr.issues.append(f"jugador no encontrado: {raw_player_str!r}")
        if segment_col and not seg_suffix:
            rr.issues.append(f"segmento desconocido: {raw_segment_str!r}")
        resolved.append(rr)
    return resolved


# ---------- step 3: transform ----------

@dataclass
class PlayerPayload:
    player: Player
    raw_data: dict[str, Any] = field(default_factory=dict)
    session_labels: set[str] = field(default_factory=set)
    contributing_rows: int = 0


def _reduce(values: list[Any], mode: str) -> Any:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    if mode == "sum":
        return sum(nums)
    if mode == "max":
        return max(nums)
    if mode == "min":
        return min(nums)
    if mode == "avg":
        return sum(nums) / len(nums)
    if mode == "last":
        return nums[-1]
    return nums[-1]  # safe fallback


def transform_rows(resolved: list[ResolvedRow], mapping: dict) -> dict[str, PlayerPayload]:
    """Group resolved rows by player and apply the field_map.

    Returns dict keyed by player id (str). Per-segment fields use
    `template_key_pattern`; cross-segment fields are reduced via `reduce`.
    """
    field_map = mapping.get("field_map") or {}

    # Pre-compute reduce mode per template_key for cross-segment fields.
    reduce_modes: dict[str, str] = {
        spec["template_key"]: spec.get("reduce", "last")
        for spec in field_map.values()
        if "template_key" in spec
    }

    by_player: dict[str, PlayerPayload] = {}
    reduce_buckets: dict[str, dict[str, list[Any]]] = {}

    for row in resolved:
        if not row.player:
            continue
        key = str(row.player.id)
        payload = by_player.setdefault(key, PlayerPayload(player=row.player))
        bucket = reduce_buckets.setdefault(key, {})
        payload.contributing_rows += 1
        if row.session_label:
            payload.session_labels.add(row.session_label)

        for col, spec in field_map.items():
            value = row.metric_values.get(col)
            if "template_key_pattern" in spec:
                if not row.segment_suffix:
                    continue
                resolved_key = spec["template_key_pattern"].replace(
                    "{segment}", row.segment_suffix,
                )
                payload.raw_data[resolved_key] = value
            elif "template_key" in spec:
                bucket.setdefault(spec["template_key"], []).append(value)

    for player_key, payload in by_player.items():
        for tkey, values in reduce_buckets[player_key].items():
            payload.raw_data[tkey] = _reduce(values, reduce_modes.get(tkey, "last"))
    return by_player


# ---------- step 4: orchestrate ----------

def run_ingest(
    file_bytes: bytes,
    template: ExamTemplate,
    category: Category,
    recorded_at: datetime,
    *,
    dry_run: bool,
    event: Event | None = None,
) -> dict:
    """Run parse → match → transform, optionally commit.

    `event` is the optional calendar event the upload is associated with —
    typically a `match`. When provided it's stored as a FK on each
    `ExamResult`, but `recorded_at` still comes from the caller (the API
    layer is the one that decides whether to derive from `event.starts_at`).

    Returns a JSON-friendly dict suitable for the API response.
    """
    mapping = (template.input_config or {}).get("column_mapping")
    if not mapping:
        raise IngestError("La plantilla no tiene un column_mapping configurado.")

    parsed = parse_xlsx(file_bytes)
    resolved = match_rows(parsed, mapping, category)
    by_player = transform_rows(resolved, mapping)

    matched: list[dict] = []
    for payload in by_player.values():
        result_data = compute_result_data(template, payload.raw_data)
        matched.append({
            "player_id": str(payload.player.id),
            "player_name": f"{payload.player.first_name} {payload.player.last_name}",
            "session_label": ", ".join(sorted(payload.session_labels)) or None,
            "contributing_rows": payload.contributing_rows,
            "result_data": result_data,
        })
    matched.sort(key=lambda m: m["player_name"].lower())

    unmatched: dict[str, dict] = {}
    for row in resolved:
        if row.player:
            continue
        bucket = unmatched.setdefault(
            row.raw_player,
            {"raw_player": row.raw_player, "rows": 0, "issues": []},
        )
        bucket["rows"] += 1
        for issue in row.issues:
            if issue not in bucket["issues"]:
                bucket["issues"].append(issue)

    response: dict = {
        "matched": matched,
        "unmatched": list(unmatched.values()),
        "total_rows": len(resolved),
        "matched_players": len(matched),
        "created_results": 0,
        "dry_run": dry_run,
    }

    if not dry_run and matched:
        for entry in matched:
            ExamResult.objects.create(
                player_id=entry["player_id"],
                template=template,
                recorded_at=recorded_at,
                result_data=entry["result_data"],
                event=event,
            )
        response["created_results"] = len(matched)
    if event is not None:
        response["event"] = {
            "id": str(event.id),
            "title": event.title,
            "starts_at": event.starts_at.isoformat(),
        }
    return response
