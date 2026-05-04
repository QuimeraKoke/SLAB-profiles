"""Server-side data resolution for layout widgets.

Given a (Widget, Player), produce a chart-ready payload that the frontend
dispatches to a renderer via `chart_type`. The frontend stays a dumb client —
all aggregation, ordering, percentage calculation, and delta computation
happens here.
"""

from __future__ import annotations

from typing import Any, Callable
from uuid import UUID

from exams.models import ExamResult, ExamTemplate

from .models import (
    Aggregation,
    ChartType,
    Widget,
    WidgetDataSource,
    field_lookup,
    iter_template_fields,
)


# ---------- helpers ----------

def _fetch_results(
    template: ExamTemplate, player_id: UUID, source: WidgetDataSource
) -> list[ExamResult]:
    """Apply the source's aggregation rule, return results in chronological order."""
    qs = ExamResult.objects.filter(template=template, player_id=player_id).order_by(
        "recorded_at"
    )
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
    return base


# ---------- resolvers ----------

def _resolve_comparison_table(
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.COMPARISON_TABLE.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source)

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


def _resolve_line_with_selector(
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
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

    for source in sources:
        template = source.template
        results = _fetch_results(template, player_id, source)
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

    return {
        "chart_type": ChartType.LINE_WITH_SELECTOR.value,
        "available_fields": available_fields,
        "series": series,
    }


def _resolve_donut_per_result(
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.DONUT_PER_RESULT.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source)

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
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.GROUPED_BAR.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source)

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
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
) -> dict[str, Any]:
    if not sources:
        return _empty(widget, ChartType.MULTI_LINE.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source)

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


def _resolve_cross_exam_line(
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
) -> dict[str, Any]:
    series_payload = []
    for src in sources:
        results = _fetch_results(src.template, player_id, src)
        key = src.field_keys[0] if src.field_keys else None
        if key is None:
            continue
        meta = _field_meta(src.template, key)
        series_payload.append(
            {
                "label": src.label or meta["label"],
                "color": src.color or None,
                "unit": meta["unit"],
                "template": src.template.name,
                "field_key": key,
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
        "chart_type": ChartType.CROSS_EXAM_LINE.value,
        "series": series_payload,
    }


def _resolve_body_map_heatmap(
    widget: Widget, sources: list[WidgetDataSource], player_id: UUID
) -> dict[str, Any]:
    """Count results per body region, bucketed by episode stage when applicable.

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

    counts: dict[str, int] = {}
    per_option_counts: dict[str, int] = {}
    counts_by_stage: dict[str, dict[str, int]] = {}

    for r in results:
        body_raw = (r.result_data or {}).get(field_key)
        if not body_raw:
            continue
        per_option_counts[body_raw] = per_option_counts.get(body_raw, 0) + 1
        region = option_regions.get(body_raw)
        if not region:
            continue
        counts[region] = counts.get(region, 0) + 1

        if stage_field_key:
            stage_raw = (r.result_data or {}).get(stage_field_key) or ""
            stage_raw = str(stage_raw)
            if stage_raw:
                bucket = counts_by_stage.setdefault(stage_raw, {})
                bucket[region] = bucket.get(region, 0) + 1

    max_count = max(counts.values(), default=0)

    region_to_options: dict[str, list[str]] = {}
    for opt, region in option_regions.items():
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


_RESOLVERS: dict[str, Callable[[Widget, list[WidgetDataSource], UUID], dict[str, Any]]] = {
    ChartType.COMPARISON_TABLE.value: _resolve_comparison_table,
    ChartType.LINE_WITH_SELECTOR.value: _resolve_line_with_selector,
    ChartType.DONUT_PER_RESULT.value: _resolve_donut_per_result,
    ChartType.GROUPED_BAR.value: _resolve_grouped_bar,
    ChartType.MULTI_LINE.value: _resolve_multi_line,
    ChartType.CROSS_EXAM_LINE.value: _resolve_cross_exam_line,
    ChartType.BODY_MAP_HEATMAP.value: _resolve_body_map_heatmap,
}


def resolve_widget(widget: Widget, player_id: UUID) -> dict[str, Any]:
    """Return a chart-ready payload for a widget bound to a player."""
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
    return handler(widget, sources, player_id)
