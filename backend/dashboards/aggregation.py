"""Server-side data resolution for layout widgets.

Given a (Widget, Player), produce a chart-ready payload that the frontend
dispatches to a renderer via `chart_type`. The frontend stays a dumb client —
all aggregation, ordering, percentage calculation, and delta computation
happens here.
"""

from __future__ import annotations

import re

from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import UUID

from django.utils import timezone

from exams.models import ExamResult, ExamTemplate

from .models import (
    Aggregation,
    ChartType,
    Widget,
    WidgetDataSource,
    field_lookup,
    iter_template_fields,
)
from .player_state import _GPS_TRAIN_SLUG, match_load_refs


# ---------- helpers ----------

def _fetch_results(
    template: ExamTemplate,
    player_id: UUID,
    source: WidgetDataSource,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[ExamResult]:
    """Apply the source's aggregation rule, return results in chronological order.

    Optional `date_from` / `date_to` bound `recorded_at` BEFORE the
    aggregation runs. That means `LATEST` returns the last result within
    the window (not the last result ever), `LAST_N` returns the last N
    within the window (may be fewer than N if the window is sparse), and
    `ALL` returns everything in the window. The semantics match the team
    aggregator so the two layers stay consistent.

    Widgets that conceptually ignore the window (e.g. body-map heatmap
    of all-time injuries) should call `_fetch_results` without passing
    the bounds — the resolver is in charge of that policy decision.
    """
    # Fan out across the template's whole version family. A WidgetDataSource
    # pointing at v2 also surfaces results that were written against v1 —
    # field keys that no longer exist on the active version are silently
    # dropped at the field-extraction step (see `_read`). This preserves
    # history without requiring schema migrations on JSONB result_data.
    qs = ExamResult.objects.filter(
        template__family_id=template.family_id,
        player_id=player_id,
    )
    if date_from is not None:
        qs = qs.filter(recorded_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(recorded_at__lte=date_to)
    qs = qs.order_by("recorded_at")
    if source.aggregation == Aggregation.LATEST:
        latest = qs.last()
        return [latest] if latest else []
    if source.aggregation == Aggregation.LAST_N:
        # Newest first → trim to N → reverse so callers receive chronological.
        n = max(int(source.aggregation_param or 1), 1)
        return list(qs.order_by("-recorded_at")[:n])[::-1]
    return list(qs)


def _read(result: ExamResult, key: str) -> Any:
    return (result.result_data or {}).get(key)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _field_meta(template: ExamTemplate, key: str) -> dict[str, Any]:
    field = field_lookup(template, key) or {}
    return {
        "key": key,
        "label": field.get("label", key),
        "unit": field.get("unit", ""),
        "group": field.get("group", ""),
        "type": field.get("type", "text"),
        "direction_of_good": field.get("direction_of_good", "neutral"),
        "reference_ranges": list(field.get("reference_ranges") or []),
    }


def _empty(widget: Widget, chart_type: str) -> dict[str, Any]:
    """Return a payload that matches the chart_type's shape but is empty.

    This way frontend renderers can check `data.columns.length` etc. without
    guarding against missing keys.
    """
    base: dict[str, Any] = {"chart_type": chart_type, "title": widget.title, "empty": True}
    if chart_type == ChartType.COMPARISON_TABLE.value:
        return {**base, "columns": [], "rows": []}
    if chart_type == ChartType.LINE_WITH_SELECTOR.value:
        return {**base, "available_fields": [], "series": {}}
    if chart_type == ChartType.DONUT_PER_RESULT.value:
        return {**base, "donuts": []}
    if chart_type == ChartType.GROUPED_BAR.value:
        return {**base, "groups": [], "fields": []}
    if chart_type == ChartType.MULTI_LINE.value:
        return {**base, "series": []}
    if chart_type == ChartType.CROSS_EXAM_LINE.value:
        return {**base, "series": []}
    if chart_type == ChartType.BODY_MAP_HEATMAP.value:
        return {
            **base,
            "counts": {},
            "counts_by_stage": {},
            "stages": [],
            "stage_field_key": "",
            "max_count": 0,
            "items": [],
            "total_results": 0,
        }
    if chart_type == ChartType.GOAL_CARD.value:
        return {**base, "cards": []}
    return base


# ---------- resolvers ----------

def _resolve_comparison_table(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.COMPARISON_TABLE.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source, date_from, date_to)

    columns = [
        {"result_id": str(r.id), "recorded_at": r.recorded_at.isoformat()}
        for r in results
    ]
    rows: list[dict[str, Any]] = []
    for key in source.field_keys:
        meta = _field_meta(template, key)
        values: list[Any] = []
        deltas: list[float | None] = []
        prev_numeric: float | None = None
        for r in results:
            raw = _read(r, key)
            num = _safe_float(raw)
            values.append(raw)
            deltas.append(
                None
                if num is None or prev_numeric is None
                else round(num - prev_numeric, 2)
            )
            if num is not None:
                prev_numeric = num
        rows.append({**meta, "values": values, "deltas": deltas})

    return {
        "chart_type": ChartType.COMPARISON_TABLE.value,
        "columns": columns,
        "rows": rows,
    }


def _match_load_reference_lines(
    player_id: UUID, source: WidgetDataSource, field_keys: list[str], anchor: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """Per-field acute/chronic reference lines from match GPS (≥75 min only).

    Delegates the computation to `player_state.match_load_refs` and formats it
    into chart lines keyed by `<source_id>::<field_key>` (same keys as `series`).
    """
    refs = match_load_refs(player_id, anchor, field_keys)
    out: dict[str, list[dict[str, Any]]] = {}
    for field_key, ref in refs.items():
        lines: list[dict[str, Any]] = []
        if ref.get("chronic") is not None:
            lines.append({"kind": "chronic", "short": "Crónica",
                          "label": "Carga crónica (máx. partido 28 d)",
                          "value": round(ref["chronic"], 1)})
        if ref.get("acute") is not None:
            lines.append({"kind": "acute", "short": "Aguda",
                          "label": "Carga aguda (máx. partido 7 d)",
                          "value": round(ref["acute"], 1)})
        if lines:
            out[f"{source.id}::{field_key}"] = lines
    return out


def _peer_average_lines(
    player, sources: list[WidgetDataSource],
) -> dict[str, list[dict[str, Any]]]:
    """Team + same-position AVERAGE reference lines for every field on a
    line-with-selector chart (works for GPS and any metric). Lets a player's
    series be read against the squad and their positional peers."""
    from .references import peer_averages

    if player is None:
        return {}
    category = player.category
    position = player.position.name if player.position else None

    out: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        # Skip training GPS: it already carries the acute/chronic match-load
        # lines, and a team average of "latest training session" is noisy
        # (it mixes players sitting on different microcycle days).
        if source.template.slug == _GPS_TRAIN_SLUG:
            continue
        fkeys = source.field_keys or [
            f["key"] for f in iter_template_fields(source.template)
            if f.get("type") in {"number", "calculated"}
        ]
        for field_key in fkeys:
            pa = peer_averages(source.template, field_key, category, position=position)
            if not pa:
                continue
            lines: list[dict[str, Any]] = []
            if pa.get("team") is not None:
                lines.append({"kind": "team", "short": "Equipo",
                              "label": "Promedio del equipo", "value": round(pa["team"], 1)})
            if pa.get("position"):
                pos = pa["position"]
                lines.append({"kind": "position", "short": pos["label"],
                              "label": f"Promedio {pos['label']}", "value": round(pos["avg"], 1)})
            if lines:
                out[f"{source.id}::{field_key}"] = lines
    return out


def position_comparison(
    source: WidgetDataSource,
    field_key: str,
    player,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Same-position peers' series for one field — the on-demand payload
    behind a chart's comparison toggle. Two levels:

    - ``players``: each ACTIVE same-position teammate's full series, one
      entry per player (the viewed player is excluded — they're already the
      chart's main line).
    - ``mean``: per-calendar-day average across the WHOLE position
      (viewed player included), only for days where at least two players
      have a value — a "mean" of one player is just that player's line.

    Results are fetched with the SAME source aggregation/window rules as
    the widget's own series (`_fetch_results`), so both sides of the
    comparison see the same data policy.
    """
    from core.models import Player

    if player is None or player.position_id is None:
        return {"position": None, "players": [], "mean": []}

    def _points(pid) -> list[dict[str, Any]]:
        results = _fetch_results(source.template, pid, source, date_from, date_to)
        return [
            {
                "recorded_at": r.recorded_at.isoformat(),
                "value": _safe_float(_read(r, field_key)),
            }
            for r in results
        ]

    day_values: dict[str, list[float]] = {}

    def _collect(points: list[dict[str, Any]]) -> None:
        for pt in points:
            if pt["value"] is not None:
                day_values.setdefault(pt["recorded_at"][:10], []).append(pt["value"])

    _collect(_points(player.id))

    peers = (
        Player.objects.filter(
            category_id=player.category_id,
            position_id=player.position_id,
            is_active=True,
        )
        .exclude(id=player.id)
        .order_by("last_name", "first_name")
    )
    players_payload: list[dict[str, Any]] = []
    for peer in peers:
        points = _points(peer.id)
        if not any(pt["value"] is not None for pt in points):
            continue
        first = (peer.first_name or "").strip()
        last = (peer.last_name or "").strip().title()
        players_payload.append(
            {
                "player_id": str(peer.id),
                "name": f"{first[:1]}. {last}".strip(". ") if last else first.title(),
                "points": points,
            }
        )
        _collect(points)

    mean_points = [
        {"day": day, "value": round(sum(vals) / len(vals), 2), "n": len(vals)}
        for day, vals in sorted(day_values.items())
        if len(vals) >= 2
    ]
    return {
        "position": player.position.name,
        "players": players_payload,
        "mean": mean_points,
    }


def _resolve_line_with_selector(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Build a flat dropdown of fields drawn from one or more templates.

    Composite series keys (`<source_id>::<field_key>`) keep two templates
    that happen to share a field name from collapsing into the same series.
    Each option carries its template label so the frontend can prefix the
    dropdown when more than one template is bound.
    """
    if not sources:
        return _empty(widget, ChartType.LINE_WITH_SELECTOR.value)

    available_fields: list[dict[str, Any]] = []
    series: dict[str, list[dict[str, Any]]] = {}
    all_results: list[ExamResult] = []

    for source in sources:
        template = source.template
        results = _fetch_results(template, player_id, source, date_from, date_to)
        all_results.extend(results)
        field_keys = source.field_keys or [
            f["key"]
            for f in iter_template_fields(template)
            if f.get("type") in {"number", "calculated"}
        ]
        for field_key in field_keys:
            composite_key = f"{source.id}::{field_key}"
            meta = _field_meta(template, field_key)
            available_fields.append(
                {
                    **meta,
                    "key": composite_key,
                    "field_key": field_key,
                    "template_id": str(template.id),
                    "template_label": source.label or template.name,
                }
            )
            series[composite_key] = [
                {
                    "recorded_at": r.recorded_at.isoformat(),
                    "value": _safe_float(_read(r, field_key)),
                }
                for r in results
            ]

    # Training-load chart: overlay acute/chronic match-load reference lines.
    reference_lines: dict[str, list[dict[str, Any]]] = {}
    anchor = date_to or timezone.now()
    # `date_to` arrives naive (parsed from a date string); DB timestamps are
    # tz-aware, so normalize before any comparison.
    if timezone.is_naive(anchor):
        anchor = timezone.make_aware(anchor, timezone.get_default_timezone())
    for source in sources:
        if source.template.slug != _GPS_TRAIN_SLUG:
            continue
        fkeys = source.field_keys or [
            f["key"] for f in iter_template_fields(source.template)
            if f.get("type") in {"number", "calculated"}
        ]
        reference_lines.update(
            _match_load_reference_lines(player_id, source, fkeys, anchor)
        )

    # Team + same-position average lines for EVERY field (GPS + any metric).
    from core.models import Player

    player = (
        Player.objects.select_related("position", "category")
        .filter(id=player_id).first()
    )
    for key, lines in _peer_average_lines(player, sources).items():
        reference_lines.setdefault(key, []).extend(lines)

    return {
        "chart_type": ChartType.LINE_WITH_SELECTOR.value,
        "available_fields": available_fields,
        "series": series,
        "reference_lines": reference_lines,
        # Rival names for tooltip rows whose date is a match date (e.g. the
        # per-match GPS charts, where every point IS a match).
        "matches": _matches_for([(all_results, timedelta(0))]),
    }


def _resolve_training_radar(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Radar: one training session's GPS variables as a % of the player's
    chronic match-load reference (max match in 28 d, ≥75 GPS-min). One axis
    per metric; the reference ring is 100% (= match-day chronic).

    Ships the last N sessions (display_config `session_count`, default 15),
    each with its own reference — the frontend offers them in a selector and
    defaults to the newest. When no qualifying match sits in the 28 days
    before a session (subs, layoffs, off-season), that session's reference
    re-anchors at the player's most recent full match so the comparison
    still reads against his own match demands — `reference_kind` tells the
    frontend which one it got."""
    from .player_state import MATCH_REFERENCE_FIELDS, MIN_MATCH_MINUTES, _GPS_MATCH_SLUG

    empty = {"chart_type": ChartType.TRAINING_RADAR.value, "empty": True,
             "axes": [], "sessions": []}
    src = next((s for s in sources if s.template.slug == _GPS_TRAIN_SLUG), None)
    if src is None:
        return empty
    template = src.template
    field_keys = [
        k for k in (src.field_keys or sorted(MATCH_REFERENCE_FIELDS))
        if k in MATCH_REFERENCE_FIELDS
    ]

    session_count = 15
    if isinstance(widget.display_config, dict):
        session_count = int(widget.display_config.get("session_count") or 15)

    qs = ExamResult.objects.filter(player_id=player_id, template=template)
    if date_to is not None:
        cap = date_to
        if timezone.is_naive(cap):
            cap = timezone.make_aware(cap, timezone.get_default_timezone())
        qs = qs.filter(recorded_at__lte=cap)
    trainings = list(qs.order_by("-recorded_at")[:session_count])
    if not trainings:
        return empty

    # One query for every full match up to the newest session; per-session
    # windows are then resolved in Python (avoids N `match_load_refs` calls).
    matches = [
        (rec, data or {}) for rec, data in ExamResult.objects.filter(
            player_id=player_id, template__slug=_GPS_MATCH_SLUG,
            recorded_at__lte=trainings[0].recorded_at,
        ).order_by("-recorded_at").values_list("recorded_at", "result_data")
        if (_safe_float((data or {}).get("tot_dur")) or 0.0) >= MIN_MATCH_MINUTES
    ]

    def _axes_for(session) -> tuple[list[dict[str, Any]], str, Any]:
        anchor = session.recorded_at
        kind = "ventana_28d"
        window = [d for rec, d in matches
                  if anchor - timedelta(days=28) <= rec <= anchor]
        if not window:
            # Fall back to a 28 d block ending at the last full match.
            prior = [(rec, d) for rec, d in matches if rec <= anchor]
            if prior:
                kind, anchor = "ultimo_partido_completo", prior[0][0]
                window = [d for rec, d in prior
                          if rec >= anchor - timedelta(days=28)]
        axes: list[dict[str, Any]] = []
        for key in field_keys:
            tv = _safe_float((session.result_data or {}).get(key))
            vals = [v for v in (_safe_float(d.get(key)) for d in window) if v is not None]
            chronic = max(vals) if vals else None
            if tv is None or not chronic:
                continue
            meta = _field_meta(template, key)
            axes.append({
                "key": key,
                "label": meta.get("label") or key,
                "unit": meta.get("unit"),
                "training_value": round(tv, 1),
                "reference_value": round(chronic, 1),
                "pct": round(tv / chronic * 100, 1),
            })
        return axes, kind, anchor

    sessions_payload: list[dict[str, Any]] = []
    for t in trainings:
        axes, kind, anchor = _axes_for(t)
        label = ((t.result_data or {}).get("sesion") or "").strip()
        sessions_payload.append({
            "session_date": t.recorded_at.isoformat(),
            "label": label,
            "axes": axes,
            "reference_kind": kind,
            "reference_date": anchor.date().isoformat(),
        })

    newest = sessions_payload[0]
    return {
        "chart_type": ChartType.TRAINING_RADAR.value,
        # Top-level mirrors the newest session (pre-selector payload shape).
        "axes": newest["axes"],
        "reference_pct": 100,
        "session_date": newest["session_date"],
        "reference_kind": newest["reference_kind"],
        "reference_date": newest["reference_date"],
        "sessions": sessions_payload,
        "empty": not any(s["axes"] for s in sessions_payload),
    }


def _resolve_donut_per_result(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.DONUT_PER_RESULT.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source, date_from, date_to)

    palette = (
        widget.display_config.get("colors", [])
        if isinstance(widget.display_config, dict)
        else []
    )
    metas = [_field_meta(template, k) for k in source.field_keys]
    donuts: list[dict[str, Any]] = []
    for r in results:
        slices: list[dict[str, Any]] = []
        total = 0.0
        for i, key in enumerate(source.field_keys):
            num = _safe_float(_read(r, key))
            if num is None:
                continue
            color = palette[i] if i < len(palette) else None
            slices.append(
                {
                    "key": key,
                    "label": metas[i]["label"],
                    "value": num,
                    "color": color,
                }
            )
            total += num
        for slice_ in slices:
            slice_["percentage"] = (
                round(slice_["value"] / total * 100, 1) if total else 0.0
            )
        donuts.append(
            {
                "result_id": str(r.id),
                "recorded_at": r.recorded_at.isoformat(),
                "slices": slices,
                "total": round(total, 2),
            }
        )
    return {
        "chart_type": ChartType.DONUT_PER_RESULT.value,
        "donuts": donuts,
    }


def _resolve_grouped_bar(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.GROUPED_BAR.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source, date_from, date_to)

    palette = (
        widget.display_config.get("colors", [])
        if isinstance(widget.display_config, dict)
        else []
    )
    metas = [_field_meta(template, k) for k in source.field_keys]
    fields_payload = [
        {**meta, "color": palette[i] if i < len(palette) else None}
        for i, meta in enumerate(metas)
    ]
    groups: list[dict[str, Any]] = []
    for r in results:
        groups.append(
            {
                "result_id": str(r.id),
                "recorded_at": r.recorded_at.isoformat(),
                "bars": [
                    {
                        "key": meta["key"],
                        "label": meta["label"],
                        "value": _safe_float(_read(r, meta["key"])),
                    }
                    for meta in metas
                ],
            }
        )
    return {
        "chart_type": ChartType.GROUPED_BAR.value,
        "groups": groups,
        "fields": fields_payload,
    }


def _resolve_multi_line(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.MULTI_LINE.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source, date_from, date_to)

    palette = (
        widget.display_config.get("colors", [])
        if isinstance(widget.display_config, dict)
        else []
    )
    series = []
    for i, key in enumerate(source.field_keys):
        meta = _field_meta(template, key)
        series.append(
            {
                "key": key,
                "label": meta["label"],
                "unit": meta["unit"],
                "color": palette[i] if i < len(palette) else None,
                "points": [
                    {
                        "recorded_at": r.recorded_at.isoformat(),
                        "value": _safe_float(_read(r, key)),
                    }
                    for r in results
                ],
            }
        )
    return {
        "chart_type": ChartType.MULTI_LINE.value,
        "series": series,
    }


_MATCH_TITLE_COUNTER = re.compile(r"\s*\(\d+\)\s*$")
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")


def _match_info(event) -> dict[str, Any]:
    """Opponent + venue for a match event, best source available.

    Preference order: the structured `opponent_team` FK, then
    `metadata.opponent`, then parsing the "Home vs Away" title against the
    event's own club name (which also yields home/away). Parentheticals
    ("(3)" fixture counters, "(Semifinal)") stay in the title but are
    stripped from a derived opponent name.
    """
    title = _MATCH_TITLE_COUNTER.sub("", event.title or "").strip()
    club_name = (event.club.name if event.club_id else "").strip()
    home: bool | None = None
    opponent = (
        event.opponent_team.name
        if event.opponent_team_id
        else (event.metadata or {}).get("opponent") or None
    )
    parts = re.split(r"\s+vs\.?\s+", title, flags=re.IGNORECASE)
    if len(parts) == 2 and club_name:
        home_side, away_side = (
            _TRAILING_PARENTHETICAL.sub("", p).strip() for p in parts
        )
        if club_name.lower() in home_side.lower():
            home = True
            opponent = opponent or away_side
        elif club_name.lower() in away_side.lower():
            home = False
            opponent = opponent or home_side
    return {"opponent": opponent, "home": home, "title": title}


def _matches_for(
    groups: list[tuple[list[ExamResult], timedelta]],
) -> dict[str, dict[str, Any]]:
    """Match events linked to any of the given results, for tooltips.

    One query. Returns `{YYYY-MM-DD: {opponent, home, title}}` keyed by the
    match's own date AND by each linked result's displayed day (recorded_at
    plus that group's display shift), so the frontend lookup hits even when
    the export was recorded on a different calendar day than the event start.
    """
    event_ids = {r.event_id for results, _ in groups for r in results if r.event_id}
    if not event_ids:
        return {}
    from events.models import Event

    info_by_event = {
        ev.id: (ev, _match_info(ev))
        for ev in Event.objects.filter(
            id__in=event_ids, event_type=Event.TYPE_MATCH
        ).select_related("club", "opponent_team")
    }
    matches: dict[str, dict[str, Any]] = {}
    for ev, info in info_by_event.values():
        matches[ev.starts_at.date().isoformat()] = info
    for results, shift in groups:
        for r in results:
            hit = info_by_event.get(r.event_id)
            if hit is not None:
                matches.setdefault((r.recorded_at + shift).date().isoformat(), hit[1])
    return matches


def _resolve_cross_exam_line(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    series_payload = []
    results_by_src: list[tuple[WidgetDataSource, str, list[ExamResult]]] = []
    for src in sources:
        key = src.field_keys[0] if src.field_keys else None
        if key is None:
            continue
        # The window bounds address DISPLAYED dates; a shifted series must
        # fetch from the equivalently un-shifted recorded_at range so points
        # that land inside the window after shifting aren't dropped.
        shift = timedelta(days=src.date_shift_days or 0)
        results = _fetch_results(
            src.template,
            player_id,
            src,
            date_from - shift if date_from else None,
            date_to - shift if date_to else None,
        )
        results_by_src.append((src, key, results))

    matches = _matches_for(
        [
            (results, timedelta(days=src.date_shift_days or 0))
            for src, _key, results in results_by_src
        ]
    )

    for src, key, results in results_by_src:
        shift = timedelta(days=src.date_shift_days or 0)
        meta = _field_meta(src.template, key)
        points = []
        for r in results:
            point: dict[str, Any] = {
                "recorded_at": (r.recorded_at + shift).isoformat(),
                "value": _safe_float(_read(r, key)),
            }
            if shift:
                point["actual_recorded_at"] = r.recorded_at.isoformat()
            points.append(point)
        series_payload.append(
            {
                "label": src.label or meta["label"],
                "color": src.color or None,
                "unit": meta["unit"],
                "template": src.template.name,
                "field_key": key,
                "date_shift_days": src.date_shift_days or 0,
                "points": points,
            }
        )
    return {
        "chart_type": ChartType.CROSS_EXAM_LINE.value,
        "series": series_payload,
        "matches": matches,
    }


def _resolve_body_map_heatmap(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,  # accepted but unused; see docstring
    date_to: datetime | None = None,    # accepted but unused; see docstring
) -> dict[str, Any]:
    """Count results per body region, bucketed by episode stage when applicable.

    Note: `date_from` / `date_to` are accepted for signature parity with
    the other resolvers but NOT applied. A body-map heatmap of "injuries
    in the last 30 days" misleads — old open injuries (e.g. a recovering
    ACL diagnosed 2 months ago) would silently disappear from the map.
    Lesion history is fundamentally an all-time view; we keep it that way.

    For each result on (player, template), reads `result_data[field_key]`,
    maps it to a body region via the field's `option_regions` map, and
    counts. When the source template is episodic and has a categorical
    stage_field, the resolver ALSO buckets counts by stage value so the
    frontend can render a stage-filter chip selector and recompute the
    displayed counts client-side without an extra round-trip.

    Returns:
      - counts: total counts per region across all stages
      - counts_by_stage: {stage_value: {region: count}} when stages available
      - stages: ordered list of {value, label, kind} for chip rendering
      - max_count: peak across `counts` (for color scaling)
      - items: per-region detail with contributing-option breakdown
      - total_results: how many results contributed
    """
    if not sources:
        return _empty(widget, ChartType.BODY_MAP_HEATMAP.value)
    source = sources[0]
    template = source.template
    if not source.field_keys:
        return _empty(widget, ChartType.BODY_MAP_HEATMAP.value)
    field_key = source.field_keys[0]
    field = field_lookup(template, field_key) or {}
    option_regions: dict[str, str] = field.get("option_regions") or {}
    option_labels: dict[str, str] = field.get("option_labels") or {}
    # Optional side-aware mapping: when the schema splits region and side
    # into two fields (Fuller surveillance format), `option_regions` values
    # may carry a "{side}" placeholder (e.g. "Muslo" → "{side}_thigh") and
    # the field declares `side_field` (e.g. "lado"). Central/bilateral or
    # missing side paints BOTH sides — an injury without a side shouldn't
    # vanish from the map.
    side_field_key: str = field.get("side_field") or ""
    _SIDES = {"izquierdo": "left", "derecho": "right", "izquierda": "left", "derecha": "right"}

    def regions_for(result_data: dict, body_raw: str) -> list[str]:
        tpl = option_regions.get(body_raw)
        if not tpl:
            return []
        if "{side}" not in tpl:
            return [tpl]
        side_raw = str((result_data or {}).get(side_field_key) or "").strip().lower()
        side = _SIDES.get(side_raw)
        if side:
            return [tpl.replace("{side}", side)]
        return [tpl.replace("{side}", "left"), tpl.replace("{side}", "right")]

    # Detect episodic stage field for bucketing.
    episode_cfg = template.episode_config or {} if template.is_episodic else {}
    stage_field_key: str = episode_cfg.get("stage_field") or ""
    stage_field = field_lookup(template, stage_field_key) if stage_field_key else None
    stage_labels: dict[str, str] = (
        (stage_field or {}).get("option_labels") or {}
    ) if stage_field else {}
    open_stages: list[str] = list(episode_cfg.get("open_stages") or [])
    closed_stage: str = episode_cfg.get("closed_stage") or ""
    # Ordered worst → best, then closed at the end.
    canonical_stage_order: list[str] = (
        open_stages + ([closed_stage] if closed_stage else [])
    )

    results = _fetch_results(template, player_id, source)

    # Episodic templates: one episode = one injury, but an episode may carry
    # several results (opening, progress notes, closing). Count each episode
    # once, using its LATEST result — which holds the final stage and data.
    if template.is_episodic:
        latest_by_episode: dict = {}
        for r in results:
            key = r.episode_id or r.id
            cur = latest_by_episode.get(key)
            if cur is None or r.recorded_at > cur.recorded_at:
                latest_by_episode[key] = r
        results = list(latest_by_episode.values())

    counts: dict[str, int] = {}
    per_option_counts: dict[str, int] = {}
    counts_by_stage: dict[str, dict[str, int]] = {}

    for r in results:
        body_raw = (r.result_data or {}).get(field_key)
        if not body_raw:
            continue
        regions = regions_for(r.result_data or {}, body_raw)
        if not regions:
            continue
        per_option_counts[body_raw] = per_option_counts.get(body_raw, 0) + 1
        for region in regions:
            counts[region] = counts.get(region, 0) + 1

            if stage_field_key:
                stage_raw = str((r.result_data or {}).get(stage_field_key) or "")
                if stage_raw:
                    bucket = counts_by_stage.setdefault(stage_raw, {})
                    bucket[region] = bucket.get(region, 0) + 1

    max_count = max(counts.values(), default=0)

    region_to_options: dict[str, list[str]] = {}
    for opt, region in option_regions.items():
        if "{side}" in region:
            region_to_options.setdefault(region.replace("{side}", "left"), []).append(opt)
            region_to_options.setdefault(region.replace("{side}", "right"), []).append(opt)
        else:
            region_to_options.setdefault(region, []).append(opt)

    items = [
        {
            "region": region,
            "count": cnt,
            "options": [
                {
                    "value": opt,
                    "label": option_labels.get(opt, opt),
                    "count": per_option_counts.get(opt, 0),
                }
                for opt in region_to_options.get(region, [])
                if per_option_counts.get(opt, 0) > 0
            ],
        }
        for region, cnt in counts.items()
    ]

    # Stages list — preserve canonical order, then append any "stray" values
    # we saw in the data that aren't in episode_config (defensive).
    stages: list[dict[str, str]] = []
    if stage_field_key:
        seen = set(counts_by_stage.keys())
        for v in canonical_stage_order:
            if v in seen or v in (stage_field or {}).get("options", []):
                stages.append({
                    "value": v,
                    "label": stage_labels.get(v, v),
                    "kind": "closed" if v == closed_stage else "open",
                })
                seen.discard(v)
        # Stray values (rare): append at the end so the UI doesn't lose them.
        for v in seen:
            stages.append({"value": v, "label": stage_labels.get(v, v), "kind": "open"})

    return {
        "chart_type": ChartType.BODY_MAP_HEATMAP.value,
        "field": _field_meta(template, field_key),
        "counts": counts,
        "counts_by_stage": counts_by_stage,
        "stages": stages,
        "stage_field_key": stage_field_key,
        "max_count": max_count,
        "items": items,
        "total_results": len(results),
    }


# Callable type widened with `Any` because mypy/pyright can't express the
# date_from/date_to optionals across the literal Callable type alias. The
# actual resolvers accept the kwargs.
_RESOLVERS: dict[str, Callable[..., dict[str, Any]]] = {
    ChartType.COMPARISON_TABLE.value: _resolve_comparison_table,
    ChartType.LINE_WITH_SELECTOR.value: _resolve_line_with_selector,
    ChartType.TRAINING_RADAR.value: _resolve_training_radar,
    ChartType.DONUT_PER_RESULT.value: _resolve_donut_per_result,
    ChartType.GROUPED_BAR.value: _resolve_grouped_bar,
    ChartType.MULTI_LINE.value: _resolve_multi_line,
    ChartType.CROSS_EXAM_LINE.value: _resolve_cross_exam_line,
    ChartType.BODY_MAP_HEATMAP.value: _resolve_body_map_heatmap,
    # `_resolve_goal_card` is defined below this dict to keep its
    # imports lazy (it pulls from `api.routers` + `goals.models`).
    # Registered at module bottom via `_RESOLVERS[...] = _resolve_goal_card`.
}


def resolve_widget(
    widget: Widget,
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Return a chart-ready payload for a widget bound to a player.

    Optional `date_from` / `date_to` bound `ExamResult.recorded_at`
    before aggregation. Per-resolver policy: most apply the bounds;
    `body_map_heatmap` ignores them by design (cumulative view).
    """
    sources = list(widget.data_sources.all())
    handler = _RESOLVERS.get(widget.chart_type)
    if handler is None:
        return {
            "chart_type": widget.chart_type,
            "unsupported": True,
            "reason": (
                f"chart_type '{widget.chart_type}' has no server resolver yet. "
                "Reserved for V2."
            ),
        }
    return handler(widget, sources, player_id, date_from, date_to)


# ---------- goal_card -----------------------------------------------------

def _resolve_goal_card(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,  # accepted but unused; see docstring
    date_to: datetime | None = None,    # accepted but unused; see docstring
) -> dict[str, Any]:
    """Active goals for this player, scoped to the widget's department.

    Filter rules:
    - Only goals with `status='active'` (cumplidas / no cumplidas /
      canceladas se ven en la pestaña Metas, no en dashboards).
    - If the widget has a `WidgetDataSource` with a template set →
      restrict to goals on that template (and any older versions of
      the same family, via `family_id`).
    - Otherwise → restrict to goals on any template in the widget's
      department (`widget.section.layout.department`).

    Note: `date_from` / `date_to` accepted for signature parity but
    NOT applied. Goals are future-target objects; the cross-tab date
    filter has no meaning here.

    Each card returns:
        {
            "id": "...", "field_label": "Peso", "field_unit": "kg",
            "operator": "<=", "target_value": 75.0,
            "due_date": "2026-08-01",
            "current_value": 78.5, "current_recorded_at": "...",
            "progress": {"achieved": false, "distance": 3.5, "distance_pct": 4.67},
            "days_to_due": 82,
        }
    """
    from datetime import date as _date
    # Lazy imports: dashboards can't import goals/api at module load
    # without risking a circular dep with the registry.
    from api.routers import _resolve_goal_current_value, _goal_progress  # noqa: WPS433
    from goals.models import Goal  # noqa: WPS433

    # Department scoping: layout.department is the natural filter.
    department = widget.section.layout.department

    # GoalStatus.ACTIVE is the active sentinel — see goals/models.py.
    goals_qs = Goal.objects.filter(
        player_id=player_id,
        status="active",
    ).select_related("template")

    # If admin bound a specific template via WidgetDataSource, narrow to it
    # (via family for cross-version continuity).
    if sources:
        family_ids = [s.template.family_id for s in sources if s.template_id]
        if family_ids:
            goals_qs = goals_qs.filter(template__family_id__in=family_ids)
    else:
        goals_qs = goals_qs.filter(template__department_id=department.id)

    goals_qs = goals_qs.order_by("due_date", "-created_at")

    today = _date.today()
    cards: list[dict[str, Any]] = []
    for goal in goals_qs:
        current, recorded_at = _resolve_goal_current_value(goal)
        progress = _goal_progress(goal, current)
        # Resolve field meta from the template's schema for label/unit.
        meta = _field_meta(goal.template, goal.field_key)
        cards.append({
            "id": str(goal.id),
            "template_name": goal.template.name,
            "field_key": goal.field_key,
            "field_label": meta["label"],
            "field_unit": meta["unit"],
            "operator": goal.operator,
            "target_value": float(goal.target_value),
            "due_date": goal.due_date.isoformat(),
            "days_to_due": (goal.due_date - today).days,
            "current_value": current,
            "current_recorded_at": (
                recorded_at.isoformat() if recorded_at else None
            ),
            "progress": progress,
            "notes": goal.notes or "",
        })

    return {
        "chart_type": ChartType.GOAL_CARD.value,
        "title": widget.title,
        "cards": cards,
        "empty": len(cards) == 0,
    }


# Register goal_card after its definition — keeps the function's lazy
# imports out of module-load order.
_RESOLVERS[ChartType.GOAL_CARD.value] = _resolve_goal_card


def _resolve_player_alerts(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,  # accepted for signature parity; not used
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Active alerts for this player, scoped to the widget's department.

    An alert is "in this department" when the underlying source's
    template lives in that department. Mapping by source_type:

      - `goal` / `goal_warning` → Goal.template.department
      - `threshold` → AlertRule.template.department  (covers BAND / BOUND /
        VARIATION rules)
      - `medication` → reserved (not yet wired); ignored for now

    No `WidgetDataSource` consumed; the resolver always uses the
    layout's department as the scope. Returns the alerts most-recent
    first, capped at a soft limit so massive layouts don't pay for
    rendering a 200-row list.
    """
    # Lazy imports avoid a circular dep when goals' AppConfig imports
    # signal handlers that import resolvers.
    from goals.models import Alert, AlertRule, AlertStatus, AlertSource  # noqa: WPS433
    from goals.models import Goal  # noqa: WPS433

    department = widget.section.layout.department
    department_id = department.id

    display_config = widget.display_config or {}
    limit = int(display_config.get("limit") or 20)
    limit = max(1, min(limit, 100))

    # Pull the player's active alerts and partition by source_type so we
    # can resolve each source's template → department in two batched
    # queries (avoid N+1).
    alerts = list(
        Alert.objects
        .filter(player_id=player_id, status=AlertStatus.ACTIVE)
        .order_by("-fired_at")
    )
    if not alerts:
        return {
            "chart_type": ChartType.PLAYER_ALERTS.value,
            "title": widget.title,
            "department_id": str(department_id),
            "department_name": department.name,
            "alerts": [],
            "total": 0,
            "empty": True,
        }

    goal_ids = {
        a.source_id for a in alerts
        if a.source_type in (AlertSource.GOAL, AlertSource.GOAL_WARNING)
    }
    threshold_ids = {
        a.source_id for a in alerts if a.source_type == AlertSource.THRESHOLD
    }

    # Resolve each source_id → (template_id, department_id, source meta).
    goal_meta: dict = {}
    if goal_ids:
        for g in (
            Goal.objects
            .filter(id__in=goal_ids)
            .select_related("template", "template__department")
            .only(
                "id", "field_key",
                "template__id", "template__name",
                "template__department_id",
            )
        ):
            goal_meta[g.id] = {
                "template_id": g.template_id,
                "template_name": g.template.name,
                "department_id": g.template.department_id,
                "field_key": g.field_key,
            }

    rule_meta: dict = {}
    if threshold_ids:
        for r in (
            AlertRule.objects
            .filter(id__in=threshold_ids)
            .select_related("template", "template__department")
            .only(
                "id", "field_key", "kind",
                "template__id", "template__name",
                "template__department_id",
            )
        ):
            rule_meta[r.id] = {
                "template_id": r.template_id,
                "template_name": r.template.name,
                "department_id": r.template.department_id,
                "field_key": r.field_key,
                "kind": r.kind,
            }

    filtered: list[dict[str, Any]] = []
    for a in alerts:
        if a.source_type in (AlertSource.GOAL, AlertSource.GOAL_WARNING):
            meta = goal_meta.get(a.source_id)
        elif a.source_type == AlertSource.THRESHOLD:
            meta = rule_meta.get(a.source_id)
        else:
            meta = None
        if meta is None or meta["department_id"] != department_id:
            continue
        filtered.append(_serialize_alert(a, meta))
        if len(filtered) >= limit:
            break

    return {
        "chart_type": ChartType.PLAYER_ALERTS.value,
        "title": widget.title,
        "department_id": str(department_id),
        "department_name": department.name,
        "alerts": filtered,
        "total": len(filtered),
        "empty": len(filtered) == 0,
    }


def _serialize_alert(alert, meta: dict | None) -> dict[str, Any]:
    """Shape one Alert row into the widget payload.

    `meta` comes from the dept-scoping batch lookup above; when the alert
    can't be tied back to a source (orphaned), we still surface enough
    to render the message — `template_name` / `field_key` degrade to "".
    """
    return {
        "id": str(alert.id),
        "source_type": alert.source_type,
        "source_id": str(alert.source_id),
        "severity": alert.severity,
        "message": alert.message,
        "fired_at": alert.fired_at.isoformat(),
        "last_fired_at": (
            alert.last_fired_at.isoformat() if alert.last_fired_at else None
        ),
        "trigger_count": alert.trigger_count,
        "template_name": (meta or {}).get("template_name", ""),
        "field_key": (meta or {}).get("field_key", ""),
    }


_RESOLVERS[ChartType.PLAYER_ALERTS.value] = _resolve_player_alerts


def _resolve_activity_log(
    widget: Widget,
    sources: list[WidgetDataSource],
    player_id: UUID,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Last N ExamResults for the player rendered as a chronological
    list. Each source contributes the fields the timeline should
    surface (e.g. 'tipo', 'zona', 'comentarios' for Molestias).

    `display_config`:
        {"limit": 10}  // max entries to return; clamp [3, 50]

    Returns a payload sharing the shape with `team_activity_log` so
    a single frontend list component renders both. Items carry the
    raw field values + a `field_label` lookup so the frontend can
    render arbitrary key/value pairs without knowing the schema.
    """
    if not sources:
        return _empty(widget, ChartType.ACTIVITY_LOG.value) | {
            "entries": [],
            "error": (
                "Configura una Data Source en este widget: elige la "
                "plantilla y los campos a listar."
            ),
        }

    display_config = widget.display_config or {}
    limit = max(3, min(int(display_config.get("limit") or 10), 50))

    # Collect entries across every data source on the widget. Mostly
    # single-source (Molestias), but supports merging Molestias + a
    # related daily-notes template into one chronology if needed.
    entries: list[dict[str, Any]] = []
    for source in sources:
        template = source.template
        field_keys = source.field_keys or []
        meta_by_key = {fk: _field_meta(template, fk) for fk in field_keys}

        qs = ExamResult.objects.filter(
            template__family_id=template.family_id,
            player_id=player_id,
        )
        if date_from is not None:
            qs = qs.filter(recorded_at__gte=date_from)
        if date_to is not None:
            qs = qs.filter(recorded_at__lte=date_to)

        for result in qs.order_by("-recorded_at")[:limit]:
            fields_payload = []
            raw = result.result_data or {}
            for fk in field_keys:
                meta = meta_by_key[fk]
                fields_payload.append({
                    "key": fk,
                    "label": meta["label"],
                    "unit": meta["unit"],
                    "value": raw.get(fk),
                })
            entries.append({
                "id": str(result.id),
                "recorded_at": result.recorded_at.isoformat(),
                "template_name": template.name,
                "fields": fields_payload,
            })

    # Cross-source ordering + cap.
    entries.sort(key=lambda e: e["recorded_at"], reverse=True)
    entries = entries[:limit]

    return {
        "chart_type": ChartType.ACTIVITY_LOG.value,
        "title": widget.title,
        "entries": entries,
        "limit": limit,
        "empty": len(entries) == 0,
    }


_RESOLVERS[ChartType.ACTIVITY_LOG.value] = _resolve_activity_log
