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

from django.db import transaction
from django.db.models import Q

from core.models import Category, Player, PlayerAlias, PlayerCallUp
from events.models import Event
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate


class IngestError(ValueError):
    """Raised when the file or column_mapping can't be processed."""


def _validate_anthropometry_masses(result_data: dict) -> str | None:
    """La partición de Kerr como control de sí misma.

    El modelo reparte la masa corporal, así que cada componente tiene que ser
    positivo y la suma tiene que dar aproximadamente el peso medido. Un rango
    por campo no alcanza para esto: en la prueba, peso 78 kg y talla 178 cm eran
    ambos plausibles y la masa muscular salió **negativa** porque el RESTO de las
    31 mediciones era incoherente entre sí. Sin este chequeo eso se guardaba y
    entraba a los gráficos del jugador.
    """
    from exams.penta_ingest import implausible_masses

    return implausible_masses(result_data, result_data.get("peso"))


# Validadores que una plantilla puede pedir con
# `input_config["bulk_ingest"]["validate"]`. Un dict explícito y no un import
# dinámico: lo que puede correr acá tiene que poder leerse de una sola mirada.
POST_VALIDATORS = {
    "anthropometry_masses": _validate_anthropometry_masses,
}


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
    """Build two normalized lookups: by alias value and by full name.

    Includes the category's HOME players plus players actively CALLED UP to it
    (see core.models.PlayerCallUp) — so a first-team upload resolves youth
    players training with the first team, without matching across the whole club.
    """
    call_up_pids = list(
        PlayerCallUp.objects.filter(
            category=category, active=True, player__is_active=True,
        ).values_list("player_id", flat=True)
    )
    players = list(
        Player.objects.filter(is_active=True)
        .filter(Q(category=category) | Q(pk__in=call_up_pids))
        .distinct()
    )
    aliases = (
        PlayerAlias.objects.filter(player__is_active=True)
        .filter(Q(player__category=category) | Q(player_id__in=call_up_pids))
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

def mapping_from_schema(
    schema: dict, *, player_column: str = "Jugador", exclude: tuple = (),
) -> dict:
    """`column_mapping` derivado de los campos del propio examen.

    Existe porque la alternativa —tipear 31 encabezados a mano en un seed— se
    desincroniza del template en la primera edición, y porque habilitar
    `bulk_ingest` sin mapping deja la carga Y la descarga devolviendo 400. Pasó
    exactamente eso en `pentacompartimental` y `peso_talla`: el seed agregaba el
    modo a `input_modes` y nunca definía el mapping.

    Toma sólo los campos `number`. Los `calculated` los recalcula el motor, y un
    archivo de mediciones no lleva texto libre ni checkboxes.

    Los encabezados son `"Etiqueta (unidad)"` — la misma etiqueta que el club ve
    en la app, más la unidad. La unidad no es decoración: la clase de error que
    corrompe una antropometría es una talla en metros, y el encabezado que dice
    "(cm)" es la primera defensa contra eso.
    """
    field_map: dict[str, dict] = {}
    for f in (schema or {}).get("fields", []):
        key = f.get("key")
        if not key or key in exclude or f.get("type") != "number":
            continue
        unit = (f.get("unit") or "").strip()
        label = f.get("label") or key
        header = f"{label} ({unit})" if unit else label
        field_map[header] = {"template_key": key}
    return {
        "player_lookup": {"column": player_column, "kind": "alias"},
        "field_map": field_map,
    }


def blank_workbook(template) -> bytes:
    """El .xlsx vacío que este parser espera, generado desde el mapping.

    Vive acá, al lado de `parse_xlsx`/`match_rows`, para que el archivo que se
    descarga y el que se lee no puedan divergir: si alguien cambia una columna
    del `column_mapping`, la plantilla descargable cambia con ella.

    ⚠️ El orden NO puede salir de `field_map`. `input_config` es un JSONField y
    Postgres lo guarda como `jsonb`, que reordena las claves (por largo y luego
    bytewise) — la de Fatiga Central vuelve como `EA, PR, I1, I2, I3`. Así que
    el orden viene del orden de los campos del examen, que además es el orden en
    que el equipo los mide.
    """
    mapping = (template.input_config or {}).get("column_mapping") or {}
    field_map = mapping.get("field_map") or {}
    if not field_map:
        raise IngestError("La plantilla no tiene un column_mapping configurado.")

    order = {
        f.get("key"): i
        for i, f in enumerate((template.config_schema or {}).get("fields", []))
    }

    def position(spec_and_col):
        col, spec = spec_and_col
        key = spec.get("template_key") or spec.get("template_key_pattern") or ""
        # Los patrones segmentados llevan `{segment}`; se ordenan por el prefijo.
        key = key.split("{")[0].rstrip("_")
        return (order.get(key, len(order)), col.lower())

    headers: list[str] = []
    player_col = (mapping.get("player_lookup") or {}).get("column")
    if player_col:
        headers.append(player_col)
    for block in ("segment", "session_label"):
        col = (mapping.get(block) or {}).get("column")
        if col:
            headers.append(col)
    headers += [col for col, _ in sorted(field_map.items(), key=position)]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datos"
    for j, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=j, value=h)
        cell.font = openpyxl.styles.Font(bold=True)
        # Ancho al encabezado: son largos ("Var % intra-sesión") y la columna
        # por defecto los corta, que es justo lo que hace dudar del formato.
        ws.column_dimensions[cell.column_letter].width = max(12, len(h) + 4)
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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

    limits = {
        f["key"]: (f.get("min"), f.get("max"))
        for f in (template.config_schema or {}).get("fields", [])
        if f.get("type") == "number" and (f.get("min") is not None or f.get("max") is not None)
    }

    post_validator = POST_VALIDATORS.get(
        ((template.input_config or {}).get("bulk_ingest") or {}).get("validate")
    )

    matched: list[dict] = []
    rejected: list[dict] = []
    for payload in by_player.values():
        # Rango declarado por el propio campo. Sin esto, un archivo con la talla
        # en metros pasaba entero: 78 kg / 0,30 m² dio un IMC de 866, y una
        # antropometría desalineada dio masa muscular NEGATIVA — y ambos se
        # guardaban sin una queja, directo a los gráficos del jugador. Es la
        # misma clase de daño que corrompió 20 evaluaciones en 2026-08; los
        # encabezados por nombre eliminan el corrimiento de columnas, no un
        # valor mal tipeado.
        out_of_range = []
        for key, (lo, hi) in limits.items():
            v = payload.raw_data.get(key)
            if not isinstance(v, (int, float)):
                continue
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                rng = f"{lo if lo is not None else '−∞'}–{hi if hi is not None else '∞'}"
                out_of_range.append(f"{key}={v} (esperado {rng})")
        if out_of_range:
            rejected.append({
                "player_name": (
                    f"{payload.player.first_name} {payload.player.last_name}"
                ),
                "issues": out_of_range,
            })
            continue

        result_data, inputs_snapshot = compute_result_data(
            template, payload.raw_data, player=payload.player,
        )
        if post_validator is not None:
            why = post_validator(result_data)
            if why:
                rejected.append({
                    "player_name": (
                        f"{payload.player.first_name} {payload.player.last_name}"
                    ),
                    "issues": [why],
                })
                continue
        matched.append({
            "player_id": str(payload.player.id),
            "player_name": f"{payload.player.first_name} {payload.player.last_name}",
            "session_label": ", ".join(sorted(payload.session_labels)) or None,
            "contributing_rows": payload.contributing_rows,
            "result_data": result_data,
            "inputs_snapshot": inputs_snapshot,
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
        "rejected": rejected,
        "unmatched": list(unmatched.values()),
        "total_rows": len(resolved),
        "matched_players": len(matched),
        "created_results": 0,
        "dry_run": dry_run,
    }

    if not dry_run and matched:
        # Atómico: cada `create` dispara señales post_save (evaluación de
        # objetivos y de umbrales), así que una fila que falla a mitad de la
        # carga dejaba las anteriores escritas y devolvía 500 — el usuario veía
        # un error y la mitad de sus datos adentro, sin forma de saber cuál
        # mitad. Verificado: pasó al habilitar la primera plantilla con
        # column_mapping (200 → 201 resultados y una excepción).
        with transaction.atomic():
            for entry in matched:
                ExamResult.objects.create(
                    player_id=entry["player_id"],
                    template=template,
                    recorded_at=recorded_at,
                    result_data=entry["result_data"],
                    inputs_snapshot=entry.get("inputs_snapshot") or {},
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
