"""Per-player department report PDF.

Walks the DepartmentLayout for the player's department + category and
renders each widget with its per-player resolver. Portrait A4.

P5 fully wires the widget renderers; for now ships the cover + exec
summary + a skeleton list of section titles so a download already
returns a real-looking PDF.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm, mm

from core.models import Department, Player
from dashboards.models import DepartmentLayout
from dashboards.aggregation import resolve_widget

from .charts import render_widget_for_pdf
from .executive_summary import player_executive_summary
from .scaffold import (
    build_pdf,
    logo_image_for_club,
    styles,
)


# Portrait A4 content frame width (after page margins in scaffold.py).
_PORTRAIT_CONTENT_WIDTH_CM = 17.5
_CELL_HORIZONTAL_PADDING_CM = 0.4

# Display timezone for cover-page "Generado" timestamp.
# Mirrors team_report._DISPLAY_TZ.
_DISPLAY_TZ = ZoneInfo("America/Santiago")

# Per-player chart types whose vertical-bar nature requires full-page
# width. See team_report._FORCE_FULL_WIDTH_CHART_TYPES for rationale.
_FORCE_FULL_WIDTH_CHART_TYPES = {
    "grouped_bar",  # per-player vertical bars across recent readings
}

# See team_report._SPLITTABLE_CHART_TYPES — same idea, per-player chart
# types that may produce multi-page tables and shouldn't be forced onto
# a single page via KeepTogether.
_SPLITTABLE_CHART_TYPES = {
    "activity_log",
    "comparison_table",
}


def _forces_full_width(widget) -> bool:
    if widget.chart_type in _FORCE_FULL_WIDTH_CHART_TYPES:
        return True
    if widget.chart_type == "team_leaderboard":
        if (widget.display_config or {}).get("style") == "vertical_bars":
            return True
    return False


def render_player_pdf(
    *,
    player: Player,
    department: Department,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> bytes:
    category = player.category
    layout = (
        DepartmentLayout.objects
        .filter(department=department, category=category, is_active=True)
        .prefetch_related("sections__widgets__data_sources")
        .first()
    )

    cover = {
        "club_name": category.club.name.upper() if category else "",
        "club_logo": logo_image_for_club(category.club) if category else None,
        "title": f"{player.first_name} {player.last_name}".strip(),
        "subtitle": f"Reporte de {department.name}",
        "category_name": category.name if category else "",
        "period_label": _format_period(date_from, date_to),
        "generated_at": timezone.now().astimezone(_DISPLAY_TZ),
    }

    body_styles = styles()
    sections: list[dict[str, Any]] = []

    # Executive summary first — same "30-second scan" intent as the team
    # report but personalised: alerts, status, key latest values.
    exec_block = player_executive_summary(
        player=player, department=department,
        date_from=date_from, date_to=date_to,
    )
    sections.append({
        "title": "Resumen ejecutivo",
        "flowables": exec_block,
    })

    if layout is not None:
        for section in layout.sections.all():
            widgets = list(section.widgets.all())
            section_flowables: list = []
            for row_widgets in _pack_widgets_into_rows(widgets):
                payloads = [
                    resolve_widget(w, player.id, date_from=date_from, date_to=date_to)
                    for w in row_widgets
                ]
                section_flowables.extend(
                    _render_widget_row(row_widgets, payloads, body_styles)
                )
            sections.append({
                "title": section.title or "Sección",
                "flowables": section_flowables,
            })
    else:
        sections.append({
            "title": "Sin layout configurado",
            "flowables": [
                Paragraph(
                    "No hay un DepartmentLayout activo para esta categoría "
                    f"en {department.name}.",
                    body_styles["body_muted"],
                ),
            ],
        })

    return build_pdf(
        orientation="portrait",
        cover=cover,
        sections=sections,
    )


def _pack_widgets_into_rows(widgets: list) -> list[list]:
    """Same packing rule as team_report: consecutive widgets whose
    summed `column_span` fits in 12 share a row. Vertical-bar charts
    are pinned to full width via `_forces_full_width`."""
    rows: list[list] = []
    buffer: list = []
    used = 0
    for w in widgets:
        configured = max(1, min(12, int(getattr(w, "column_span", 12) or 12)))
        span = 12 if _forces_full_width(w) else configured
        if span >= 12:
            if buffer:
                rows.append(buffer)
                buffer, used = [], 0
            rows.append([w])
            continue
        if used + span > 12:
            rows.append(buffer)
            buffer, used = [], 0
        buffer.append(w)
        used += span
    if buffer:
        rows.append(buffer)
    return rows


def _widget_inner_flowables(widget, payload: dict, body_styles, *, max_width_cm=None) -> list:
    flow: list = [Paragraph(widget.title, body_styles["body"])]
    if widget.description:
        flow.append(Paragraph(widget.description, body_styles["body_muted"]))
        flow.append(Spacer(1, 2 * mm))
    flow.extend(render_widget_for_pdf(widget, payload, max_width_cm=max_width_cm))
    return flow


def _render_widget_row(row_widgets: list, payloads: list[dict], body_styles) -> list:
    if len(row_widgets) == 1:
        w = row_widgets[0]
        flow = _widget_inner_flowables(w, payloads[0], body_styles)
        if w.chart_type in _SPLITTABLE_CHART_TYPES:
            return [*flow, Spacer(1, 8 * mm)]
        return [KeepTogether(flow), Spacer(1, 8 * mm)]

    total_span = sum(
        max(1, min(12, int(getattr(w, "column_span", 12) or 12)))
        for w in row_widgets
    )
    cells = []
    col_widths_cm = []
    for w, payload in zip(row_widgets, payloads):
        span = max(1, min(12, int(getattr(w, "column_span", 12) or 12)))
        cell_width_cm = _PORTRAIT_CONTENT_WIDTH_CM * (span / total_span)
        inner_width_cm = max(3.0, cell_width_cm - _CELL_HORIZONTAL_PADDING_CM)
        col_widths_cm.append(cell_width_cm)
        cells.append(_widget_inner_flowables(
            w, payload, body_styles, max_width_cm=inner_width_cm,
        ))

    row_table = Table(
        [cells],
        colWidths=[w * cm for w in col_widths_cm],
        hAlign="LEFT",
    )
    row_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [row_table, Spacer(1, 8 * mm)]


def _format_period(
    date_from: datetime | None,
    date_to: datetime | None,
) -> str:
    if date_from and date_to:
        return f"{date_from:%d/%m/%Y} – {date_to:%d/%m/%Y}"
    if date_from:
        return f"Desde {date_from:%d/%m/%Y}"
    if date_to:
        return f"Hasta {date_to:%d/%m/%Y}"
    return "Sin filtro de fecha"
