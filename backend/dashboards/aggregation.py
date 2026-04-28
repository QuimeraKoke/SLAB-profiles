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
    if not sources:
        return _empty(widget, ChartType.LINE_WITH_SELECTOR.value)
    source = sources[0]
    template = source.template
    results = _fetch_results(template, player_id, source)

    field_keys = source.field_keys or [
        f["key"]
        for f in iter_template_fields(template)
        if f.get("type") in {"number", "calculated"}
    ]
    available_fields = [_field_meta(template, k) for k in field_keys]
    series: dict[str, list[dict[str, Any]]] = {
        k: [
            {
                "recorded_at": r.recorded_at.isoformat(),
                "value": _safe_float(_read(r, k)),
            }
            for r in results
        ]
        for k in field_keys
    }
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


_RESOLVERS: dict[str, Callable[[Widget, list[WidgetDataSource], UUID], dict[str, Any]]] = {
    ChartType.COMPARISON_TABLE.value: _resolve_comparison_table,
    ChartType.LINE_WITH_SELECTOR.value: _resolve_line_with_selector,
    ChartType.DONUT_PER_RESULT.value: _resolve_donut_per_result,
    ChartType.GROUPED_BAR.value: _resolve_grouped_bar,
    ChartType.MULTI_LINE.value: _resolve_multi_line,
    ChartType.CROSS_EXAM_LINE.value: _resolve_cross_exam_line,
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
