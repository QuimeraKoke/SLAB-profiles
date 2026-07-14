"""Resolve / promote an ad-hoc team chart spec.

The assistant composes a chart on the fly (V2), and "promote to dashboard"
(V3) saves that same spec. Both speak the exact `TeamReportWidget` vocabulary
and run through the exact same resolver, so a previewed chart and a promoted
one are identical.

- `resolve_chart_spec` builds throwaway `TeamReport*` rows inside a transaction,
  runs the real `resolve_team_widget`, then force-rolls-back — nothing persists.
- `promote_chart_spec` persists the spec as a real `TeamReportWidget` (+ data
  sources) on the department's active layout, under a "Mis gráficos" section.

`TeamReportLayout` is unique per (department, category), so both REUSE an
existing layout when present. Spec validation is shared (`_normalize_spec`).
Never raise to the caller: a malformed spec returns an ``{"error": ...}``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max

from core.models import Category, Department, Player
from exams.models import ExamTemplate

from .models import (
    Aggregation,
    ChartType,
    DepartmentLayout,
    LayoutSection,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
    Widget,
    WidgetDataSource,
)
from .aggregation import resolve_widget
from .team_aggregation import resolve_team_widget

logger = logging.getLogger(__name__)

# Only team-scoped chart types are resolvable here (the assistant proposes
# squad charts). Per-player chart types live in a different resolver.
VALID_CHART_TYPES = {c.value for c in ChartType if c.value.startswith("team_")}
# Per-player chart types (resolved by dashboards.aggregation, on the player
# profile's department tabs). Everything that isn't a team_* type.
VALID_PLAYER_CHART_TYPES = {c.value for c in ChartType if not c.value.startswith("team_")}
_VALID_AGGREGATIONS = {a.value for a in Aggregation}

# Section a promoted chart lands in (created on demand).
_PROMOTED_SECTION_TITLE = "Mis gráficos"


class _SpecError(Exception):
    """A spec failed validation — message is user-facing (Spanish)."""


def _err(msg: str) -> dict[str, Any]:
    return {"error": msg, "empty": True}


def _normalize_spec(
    category: Category, spec: Any, valid_chart_types: set[str]
) -> tuple[str, str, dict, list[dict]]:
    """Validate + resolve a chart spec. Returns
    ``(chart_type, title, display_config, resolved_sources)`` where each
    resolved source carries a real `template` instance. Raises `_SpecError`
    (user-facing message) on anything invalid. Shared by team + player resolve
    + promote (the caller passes the valid chart-type set for its surface)."""
    if not isinstance(spec, dict):
        raise _SpecError("spec debe ser un objeto")
    chart_type = str(spec.get("chart_type") or "").strip()
    if chart_type not in valid_chart_types:
        raise _SpecError(f"chart_type inválido: {chart_type!r}")

    sources_in = spec.get("sources") or []
    if not isinstance(sources_in, list) or not sources_in:
        raise _SpecError("spec.sources debe ser una lista no vacía")

    resolved: list[dict[str, Any]] = []
    for i, s in enumerate(sources_in):
        if not isinstance(s, dict):
            raise _SpecError(f"sources[{i}] debe ser un objeto")
        slug = str(s.get("template_slug") or "").strip()
        if not slug:
            raise _SpecError(f"sources[{i}].template_slug es obligatorio")
        # slug is unique per club; the category fixes the club. Prefer the
        # active version, then the highest version number.
        template = (
            ExamTemplate.objects.filter(slug=slug, applicable_categories=category)
            .order_by("-is_active_version", "-version")
            .first()
        )
        if template is None:
            raise _SpecError(f"No existe la plantilla '{slug}' para esta categoría")
        field_keys = s.get("field_keys") or []
        if not isinstance(field_keys, list):
            raise _SpecError(f"sources[{i}].field_keys debe ser una lista")
        agg = str(s.get("aggregation") or Aggregation.LAST_N.value)
        if agg not in _VALID_AGGREGATIONS:
            raise _SpecError(f"sources[{i}].aggregation inválida: {agg!r}")
        resolved.append({
            "template": template,
            "field_keys": [str(k) for k in field_keys],
            "aggregation": agg,
            "aggregation_param": int(s.get("aggregation_param") or 3),
            "label": str(s.get("label") or ""),
            "color": str(s.get("color") or ""),
        })

    display_config = spec.get("display_config")
    if not isinstance(display_config, dict):
        display_config = {}
    title = str(spec.get("title") or "")
    return chart_type, title, display_config, resolved


def resolve_chart_spec(
    *,
    category: Category,
    department: Department,
    spec: dict[str, Any],
    position_id: UUID | None = None,
    player_ids: list[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Resolve ``spec`` to a chart-ready payload (same shape the dashboard
    renders) WITHOUT persisting anything. Returns ``{"error": ...}`` on a bad
    spec — never raises."""
    try:
        chart_type, title, display_config, resolved_sources = _normalize_spec(
            category, spec, VALID_CHART_TYPES
        )
    except _SpecError as e:
        return _err(str(e))

    payload: dict[str, Any] = _err("no se pudo resolver el gráfico")
    try:
        with transaction.atomic():
            layout = TeamReportLayout.objects.filter(
                department=department, category=category, scope="period"
            ).first()
            if layout is None:
                layout = TeamReportLayout.objects.create(
                    department=department, category=category, scope="period",
                    name="__chart_preview__", is_active=False,
                )
            section = TeamReportSection.objects.create(
                layout=layout, title="", sort_order=99999,
            )
            widget = TeamReportWidget.objects.create(
                section=section, chart_type=chart_type, title=title,
                display_config=display_config,
            )
            for i, rs in enumerate(resolved_sources):
                TeamReportWidgetDataSource.objects.create(
                    widget=widget, template=rs["template"],
                    field_keys=rs["field_keys"], aggregation=rs["aggregation"],
                    aggregation_param=rs["aggregation_param"],
                    label=rs["label"], color=rs["color"], sort_order=i,
                )
            payload = resolve_team_widget(
                widget, category,
                position_id=position_id, player_ids=player_ids,
                date_from=date_from, date_to=date_to,
            )
            payload = _materialize(payload)
            transaction.set_rollback(True)  # pure preview — discard temp rows
    except Exception as e:  # noqa: BLE001 — a preview must never 500
        logger.exception("resolve_chart_spec failed")
        return _err(f"error al resolver el gráfico: {e}")

    # Echo the normalized spec so callers can promote it verbatim (V3).
    payload["spec"] = _echo_spec(chart_type, title, display_config, resolved_sources)
    return payload


def resolve_player_chart_spec(
    *,
    player: Player,
    department: Department,
    spec: dict[str, Any],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Per-player twin of `resolve_chart_spec`: resolve a PER-PLAYER chart spec
    for ONE player via the real `resolve_widget` (the player-profile resolver),
    without persisting. Builds throwaway DepartmentLayout/Section/Widget rows
    (reusing the existing layout for the dept+category when present) and rolls
    back. Returns ``{"error": ...}`` on a bad spec — never raises."""
    category = player.category
    try:
        chart_type, title, display_config, resolved_sources = _normalize_spec(
            category, spec, VALID_PLAYER_CHART_TYPES
        )
    except _SpecError as e:
        return _err(str(e))

    payload: dict[str, Any] = _err("no se pudo resolver el gráfico")
    try:
        with transaction.atomic():
            layout = DepartmentLayout.objects.filter(
                department=department, category=category
            ).first()
            if layout is None:
                layout = DepartmentLayout.objects.create(
                    department=department, category=category,
                    name="__chart_preview__", is_active=False,
                )
            section = LayoutSection.objects.create(
                layout=layout, title="", sort_order=99999,
            )
            widget = Widget.objects.create(
                section=section, chart_type=chart_type, title=title,
                display_config=display_config,
            )
            for i, rs in enumerate(resolved_sources):
                WidgetDataSource.objects.create(
                    widget=widget, template=rs["template"],
                    field_keys=rs["field_keys"], aggregation=rs["aggregation"],
                    aggregation_param=rs["aggregation_param"],
                    label=rs["label"], color=rs["color"], sort_order=i,
                )
            payload = resolve_widget(widget, player.id, date_from=date_from, date_to=date_to)
            payload = _materialize(payload)
            transaction.set_rollback(True)  # pure preview — discard temp rows
    except Exception as e:  # noqa: BLE001 — a preview must never 500
        logger.exception("resolve_player_chart_spec failed")
        return _err(f"error al resolver el gráfico: {e}")

    payload["spec"] = _echo_spec(chart_type, title, display_config, resolved_sources)
    return payload


def promote_chart_spec(
    *,
    category: Category,
    department: Department,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Persist ``spec`` as a real `TeamReportWidget` (+ data sources) on the
    department's active layout, under a "Mis gráficos" section (created on
    demand). Returns ``{"widget_id", "section_id", "layout_id", "title"}`` or
    ``{"error": ...}`` on a bad spec. Never raises a validation error."""
    try:
        chart_type, title, display_config, resolved_sources = _normalize_spec(
            category, spec, VALID_CHART_TYPES
        )
    except _SpecError as e:
        return {"error": str(e)}

    with transaction.atomic():
        layout, _created = TeamReportLayout.objects.get_or_create(
            department=department, category=category, scope="period",
            defaults={"name": "Default", "is_active": True},
        )
        if not layout.is_active:
            layout.is_active = True
            layout.save(update_fields=["is_active"])

        section = (
            layout.sections.filter(title=_PROMOTED_SECTION_TITLE)
            .order_by("sort_order").first()
        )
        if section is None:
            next_sort = (layout.sections.aggregate(m=Max("sort_order"))["m"] or 0) + 1
            section = TeamReportSection.objects.create(
                layout=layout, title=_PROMOTED_SECTION_TITLE, sort_order=next_sort,
            )

        next_w = (section.widgets.aggregate(m=Max("sort_order"))["m"] or 0) + 1
        widget = TeamReportWidget.objects.create(
            section=section, chart_type=chart_type,
            title=title or "Gráfico", display_config=display_config,
            column_span=6, sort_order=next_w,
        )
        for i, rs in enumerate(resolved_sources):
            TeamReportWidgetDataSource.objects.create(
                widget=widget, template=rs["template"],
                field_keys=rs["field_keys"], aggregation=rs["aggregation"],
                aggregation_param=rs["aggregation_param"],
                label=rs["label"], color=rs["color"], sort_order=i,
            )

    return {
        "widget_id": str(widget.id),
        "section_id": str(section.id),
        "layout_id": str(layout.id),
        "title": widget.title,
    }


def widget_config(widget) -> dict[str, Any]:
    """A team widget's editable config, for the in-place edit modal (§5/Fase5).
    Single-source shape (what the builder authors)."""
    src = widget.data_sources.select_related("template").order_by("sort_order", "id").first()
    return {
        "chart_type": widget.chart_type,
        "title": widget.title,
        "display_config": widget.display_config or {},
        "template_slug": src.template.slug if src else "",
        "field_keys": list(src.field_keys) if src else [],
        "aggregation": src.aggregation if src else "",
    }


def edit_chart_spec(*, widget, category: Category, spec: dict[str, Any]) -> dict[str, Any]:
    """Apply a spec to an EXISTING TeamReportWidget: update chart_type / title /
    display_config and replace its data sources, preserving layout position
    (section, column_span, sort_order). Returns {widget_id, title} or {error}."""
    try:
        chart_type, title, display_config, resolved_sources = _normalize_spec(
            category, spec, VALID_CHART_TYPES
        )
    except _SpecError as e:
        return {"error": str(e)}

    with transaction.atomic():
        widget.chart_type = chart_type
        widget.title = title or widget.title or "Gráfico"
        widget.display_config = display_config
        widget.save(update_fields=["chart_type", "title", "display_config"])
        widget.data_sources.all().delete()
        for i, rs in enumerate(resolved_sources):
            TeamReportWidgetDataSource.objects.create(
                widget=widget, template=rs["template"],
                field_keys=rs["field_keys"], aggregation=rs["aggregation"],
                aggregation_param=rs["aggregation_param"],
                label=rs["label"], color=rs["color"], sort_order=i,
            )
    return {"widget_id": str(widget.id), "title": widget.title}


def promote_player_chart_spec(
    *,
    category: Category,
    department: Department,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Per-player twin of `promote_chart_spec`: persist ``spec`` as a real
    per-player `Widget` (+ data sources) on the department's `DepartmentLayout`,
    under a "Mis gráficos" section (created on demand). The widget renders PER
    PLAYER on every profile's department tab in this category. Returns the
    created ids or ``{"error": ...}``.

    NOTE: a DepartmentLayout is per (department, category); creating/activating
    one here switches that department tab from the legacy auto card-grid to the
    configured layout for the whole category."""
    try:
        chart_type, title, display_config, resolved_sources = _normalize_spec(
            category, spec, VALID_PLAYER_CHART_TYPES
        )
    except _SpecError as e:
        return {"error": str(e)}

    with transaction.atomic():
        layout, _created = DepartmentLayout.objects.get_or_create(
            department=department, category=category,
            defaults={"name": "Default", "is_active": True},
        )
        if not layout.is_active:
            layout.is_active = True
            layout.save(update_fields=["is_active"])

        section = (
            layout.sections.filter(title=_PROMOTED_SECTION_TITLE)
            .order_by("sort_order").first()
        )
        if section is None:
            next_sort = (layout.sections.aggregate(m=Max("sort_order"))["m"] or 0) + 1
            section = LayoutSection.objects.create(
                layout=layout, title=_PROMOTED_SECTION_TITLE, sort_order=next_sort,
            )

        next_w = (section.widgets.aggregate(m=Max("sort_order"))["m"] or 0) + 1
        widget = Widget.objects.create(
            section=section, chart_type=chart_type,
            title=title or "Gráfico", display_config=display_config,
            column_span=6, sort_order=next_w,
        )
        for i, rs in enumerate(resolved_sources):
            WidgetDataSource.objects.create(
                widget=widget, template=rs["template"],
                field_keys=rs["field_keys"], aggregation=rs["aggregation"],
                aggregation_param=rs["aggregation_param"],
                label=rs["label"], color=rs["color"], sort_order=i,
            )

    return {
        "widget_id": str(widget.id),
        "section_id": str(section.id),
        "layout_id": str(layout.id),
        "title": widget.title,
    }


def _echo_spec(chart_type, title, display_config, resolved_sources) -> dict[str, Any]:
    return {
        "chart_type": chart_type,
        "title": title,
        "display_config": display_config,
        "sources": [
            {
                "template_slug": rs["template"].slug,
                "field_keys": rs["field_keys"],
                "aggregation": rs["aggregation"],
                "aggregation_param": rs["aggregation_param"],
                "label": rs["label"],
                "color": rs["color"],
            }
            for rs in resolved_sources
        ],
    }


def _materialize(obj: Any) -> Any:
    """Deep-copy plain containers so the returned payload holds no lazy DB
    references once the transaction rolls back. Scalars pass through."""
    if isinstance(obj, dict):
        return {k: _materialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_materialize(v) for v in obj]
    return obj
