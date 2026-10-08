"""`team_gauge` — one metric's latest value on an arc, against the squad.

The club's evaluation sheet reads sprint tests as a speed gauge ("T10 km/h
19.97") between the slowest and fastest of the squad. Here:

* each player's LATEST value in the period counts once;
* the needle is their mean — or, with exactly one player picked in the
  report's filter, that player's value (`subject` names that player);
* the arc runs from the squad's lowest to its highest latest value, so the
  needle says where the reading sits among the squad;
* the arc is coloured with the club's bands for the category when the field
  has them. A field without bands can borrow another's through a reciprocal
  conversion — km/h from seconds: `speed = k / time` — declared in
  `display_config.bands_from`, so T10 km/h is coloured with the club's T10
  bands without anyone keeping a second set in sync.

`display_config`:
    {"bands_from": {"t10_kmh": {"field": "t10_best", "k": 36}},
     "show_top": true}

`show_top` adds the squad's highest value and its owner (`top`,
`top_subject`): a match's top speed is one player's, and that is the number
the staff asks for next to the mean. (The club's sheet summed it: 16.159
km/h.) The needle stays on the mean — on a min-to-max arc the top value is
always the right end.

Several `field_keys` on the source → a selector, like `team_trend_line`.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from core.models import Category
from exams.models import ExamResult

from .models import TeamReportWidget


def _reciprocal(bands: list[dict], k: float) -> list[dict]:
    """Bands of `x` as bands of `k / x`: edges invert and swap sides."""
    out = []
    for b in bands:
        lo, hi = b.get("min"), b.get("max")
        nb = {kk: v for kk, v in b.items() if kk not in ("min", "max")}
        if isinstance(hi, (int, float)) and hi > 0:
            nb["min"] = round(k / hi, 2)
        if isinstance(lo, (int, float)) and lo > 0:
            nb["max"] = round(k / lo, 2)
        out.append(nb)
    out.sort(key=lambda b: (b.get("min") is not None, b.get("min") or 0))
    return out


def resolve(widget: TeamReportWidget, category: Category, *,
            position_id: UUID | None = None, player_ids: Sequence[UUID] | None = None,
            date_from: datetime | None = None, date_to: datetime | None = None,
            event_id=None, event_ids=None) -> dict[str, Any]:
    from .team_aggregation import _apply_date_window, _field_meta, _roster_query

    base = {"chart_type": "team_gauge", "title": widget.title,
            "description": widget.description, "column_span": widget.column_span}
    source = widget.data_sources.select_related("template").first()
    if source is None or not source.field_keys:
        return base | {"fields": [], "default_field_key": "", "empty": True,
                       "error": "El widget no tiene campos configurados."}

    roster = list(_roster_query(category, position_id, player_ids))
    by_id = {p.id: p for p in roster}
    qs = _apply_date_window(
        ExamResult.objects.filter(template__family_id=source.template.family_id,
                                  player_id__in=by_id.keys()),
        date_from, date_to, event_id, event_ids)
    rows = list(qs.order_by("player_id", "-recorded_at").values_list(
        "player_id", "recorded_at", "result_data"))

    cfg = widget.display_config or {}
    bands_from = cfg.get("bands_from") or {}
    solo = by_id[next(iter(by_id))] if len(by_id) == 1 else None

    fields = []
    for key in source.field_keys:
        latest: dict = {}
        for pid, _when, data in rows:
            v = (data or {}).get(key)
            if pid not in latest and isinstance(v, (int, float)) and not isinstance(v, bool):
                latest[pid] = float(v)
        meta = _field_meta(source.template, key)
        bands = meta["reference_ranges"]
        if not bands and key in bands_from:
            spec = bands_from[key]
            src = _field_meta(source.template, spec.get("field", ""))["reference_ranges"]
            if src and spec.get("k"):
                bands = _reciprocal(src, float(spec["k"]))
        vals = list(latest.values())
        subject = f"{solo.first_name} {solo.last_name}".strip() if solo else None
        value = latest.get(solo.id) if solo else (sum(vals) / len(vals) if vals else None)
        top = max(latest, key=latest.get) if (cfg.get("show_top") and latest and not solo) else None
        fields.append({
            "key": key, "label": meta["label"], "unit": meta["unit"],
            "direction_of_good": meta["direction_of_good"],
            "value": round(value, 2) if value is not None else None,
            "n": len(vals),
            "min": round(min(vals), 2) if vals else None,
            "max": round(max(vals), 2) if vals else None,
            "bands": bands,
            "subject": subject,
            "top": round(latest[top], 2) if top else None,
            "top_subject": f"{by_id[top].first_name} {by_id[top].last_name}".strip() if top else None,
        })
    return base | {
        "fields": fields,
        "default_field_key": fields[0]["key"] if fields else "",
        "empty": not any(f["value"] is not None for f in fields),
    }
