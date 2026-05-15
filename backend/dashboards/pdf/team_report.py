"""Team report PDF orchestrator.

Pulls the active TeamReportLayout, runs every widget through its
resolver (same code path as the live API), feeds each payload into
its matplotlib chart renderer, and assembles the result inside the
shared scaffold.

P1 ships the scaffold only — sections render their title + a
placeholder "(gráfico en construcción)" line. P2 wires the chart
renderers. P3 fills the long tail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone

from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.units import cm, mm

from core.models import Category, Department
from dashboards.models import TeamReportLayout
from dashboards.team_aggregation import resolve_team_widget

from .charts import render_widget_for_pdf
from .executive_summary import team_executive_summary
from .scaffold import (
    build_pdf,
    logo_image_for_club,
    section_header,
    styles,
)


# Landscape A4 content frame width — must match the page margins in
# scaffold.py. Used to compute per-cell widths when packing widgets
# onto a multi-column row.
_LANDSCAPE_CONTENT_WIDTH_CM = 26.5

# Display timezone for cover-page "Generado" timestamp. Django runs in
# UTC (TIME_ZONE setting); the client is in Chile and expects local
# time on the cover, not UTC. Centralised here so the future Cliente:
# Argentina/Perú/etc. case is a one-line change.
_DISPLAY_TZ = ZoneInfo("America/Santiago")

# Vertical gutter eaten by the multi-column wrapper Table cell padding
# (left+right). Subtract from the per-widget content budget so the
# nested chart/table doesn't overflow.
_CELL_HORIZONTAL_PADDING_CM = 0.4

# Chart types that always render at full page width regardless of the
# widget's `column_span`. Vertical-bar charts need the horizontal room
# for player-name X-axis labels — squeezing them into half a row makes
# the labels overlap and the bars too thin to read.
#
# Horizontal-bar charts (team_horizontal_comparison, team_stacked_bars,
# the horizontal team_distribution) and tables CAN safely be packed at
# 50%, because they grow vertically with row count.
_FORCE_FULL_WIDTH_CHART_TYPES = {
    "team_status_counts",       # vertical bars with availability counts
    "team_daily_grouped_bars",  # vertical grouped bars per day
}

# Chart types that produce long, intrinsically splittable tables.
# Wrapping these in `KeepTogether` is harmful: when reportlab decides
# the full block doesn't fit on the current page, it jumps to the next
# page even though the *table* would split fine across pages. The
# observed symptom is a near-empty page with only the section title,
# followed by the actual table on the next page. For these widgets we
# emit title + description + table as flat siblings so the table can
# start filling space on the current page and continue naturally.
_SPLITTABLE_CHART_TYPES = {
    "team_activity_log",
    "team_activity_coverage",
    "team_roster_matrix",
    "team_alerts",
    "team_active_records",
    "team_goal_progress",
}


def _forces_full_width(widget) -> bool:
    """True when this widget can't render correctly at less than full
    page width. `team_leaderboard` is conditional — its vertical-bars
    style needs full width, but the podium-list style fits half-width
    just fine."""
    if widget.chart_type in _FORCE_FULL_WIDTH_CHART_TYPES:
        return True
    if widget.chart_type == "team_leaderboard":
        style = (widget.display_config or {}).get("style")
        if style == "vertical_bars":
            return True
    return False


def render_team_pdf(
    *,
    department: Department,
    category: Category,
    position_id: UUID | None = None,
    player_ids: list[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    event_id: UUID | None = None,
) -> bytes:
    """Build the team report PDF as bytes. Same filter inputs as the
    `/reports/{slug}` HTTP endpoint so caller code can share parsing."""
    layout = (
        TeamReportLayout.objects
        .filter(department=department, category=category, is_active=True)
        .prefetch_related("sections__widgets__data_sources")
        .first()
    )

    period_label = _format_period(date_from, date_to, event_id, layout)

    cover = {
        "club_name": category.club.name.upper(),
        "club_logo": logo_image_for_club(category.club),
        "title": f"Reporte de {department.name}",
        "subtitle": "Vista de equipo",
        "category_name": category.name,
        "period_label": period_label,
        "generated_at": timezone.now().astimezone(_DISPLAY_TZ),
    }

    body_styles = styles()
    sections: list[dict[str, Any]] = []

    # --- Resumen ejecutivo: ALWAYS first, even before any layout section.
    # Designed to give a 30-second read of who's a green/red flag.
    exec_block = team_executive_summary(
        department=department,
        category=category,
        position_id=position_id,
        player_ids=player_ids,
        date_from=date_from,
        date_to=date_to,
        event_id=event_id,
    )
    sections.append({
        "title": "Resumen ejecutivo",
        "flowables": exec_block,
    })

    # --- Layout sections (when configured) -------------------------------
    if layout is not None:
        for section in layout.sections.all():
            widgets = list(section.widgets.all())
            section_flowables: list = []
            for row_widgets in _pack_widgets_into_rows(widgets):
                payloads = [
                    resolve_team_widget(
                        w, category,
                        position_id=position_id,
                        player_ids=player_ids,
                        date_from=date_from,
                        date_to=date_to,
                        event_id=event_id,
                    )
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
                    "No hay un TeamReportLayout activo para esta "
                    f"categoría en {department.name}. Configurá uno desde "
                    "el panel de administración para que aparezcan widgets.",
                    body_styles["body_muted"],
                ),
            ],
        })

    return build_pdf(
        orientation="landscape",
        cover=cover,
        sections=sections,
    )


def _pack_widgets_into_rows(widgets: list) -> list[list]:
    """Group widgets into "rows" based on their `column_span` on a
    12-column grid (mirrors the web layout). Consecutive widgets whose
    summed `column_span` fits in 12 share a row. Anything larger flushes
    the buffer first and renders on its own.

    Chart types in `_FORCE_FULL_WIDTH_CHART_TYPES` (vertical bar charts)
    are treated as span=12 regardless of their configured column_span,
    so they always end up on their own row.

    Examples (with no forced-full-width widgets):
    - [12]              → [[12]]                       (alone, 100%)
    - [6, 6]            → [[6, 6]]                     (paired, 50/50)
    - [6, 6, 12]        → [[6, 6], [12]]
    - [4, 4, 4]         → [[4, 4, 4]]                  (thirds)
    - [6, 12, 6, 6]     → [[6], [12], [6, 6]]
    """
    rows: list[list] = []
    buffer: list = []
    used = 0
    for w in widgets:
        configured_span = max(1, min(12, int(getattr(w, "column_span", 12) or 12)))
        span = 12 if _forces_full_width(w) else configured_span
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


def _widget_inner_flowables(
    widget,
    payload: dict,
    body_styles,
    *,
    max_width_cm: float | None = None,
) -> list:
    """Title + description + chart, returned as a flat flowable list."""
    flow: list = [Paragraph(widget.title, body_styles["body"])]
    if widget.description:
        flow.append(Paragraph(widget.description, body_styles["body_muted"]))
        flow.append(Spacer(1, 2 * mm))
    flow.extend(render_widget_for_pdf(widget, payload, max_width_cm=max_width_cm))
    return flow


def _render_widget_row(row_widgets: list, payloads: list[dict], body_styles) -> list:
    """Render one packed row.

    - 1 widget → wrap title+chart in `KeepTogether` so a tall chart
      can't orphan from its title across a page break.
    - 2+ widgets → wrap in a single-row reportlab Table where each cell
      gets a width proportional to its `column_span`. Cells DO NOT use
      KeepTogether — reportlab can't split a non-splittable flowable
      inside a non-splittable Table cell, and two tall charts side-by-
      side would otherwise exceed the page height. Title-orphan risk
      is low at half-width because the chart shrinks proportionally.

    The trailing `Spacer` separates this row from the next one.
    """
    if len(row_widgets) == 1:
        w = row_widgets[0]
        flow = _widget_inner_flowables(w, payloads[0], body_styles)
        if w.chart_type in _SPLITTABLE_CHART_TYPES:
            # Skip KeepTogether so the table can start on the current
            # page and split naturally. Title-orphan risk is minor for
            # these widgets — the next page's body is recognizable from
            # the column header.
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
        cell_width_cm = _LANDSCAPE_CONTENT_WIDTH_CM * (span / total_span)
        inner_width_cm = max(4.0, cell_width_cm - _CELL_HORIZONTAL_PADDING_CM)
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
    event_id: UUID | None,
    layout: TeamReportLayout | None,
) -> str:
    """Human-friendly period label for the cover page."""
    if event_id is not None:
        # When a per-match report, look up the event title for a richer
        # cover description (e.g. "Partido: vs Colo-Colo · 13/05/2026").
        from events.models import Event
        ev = Event.objects.filter(pk=event_id).first()
        if ev is not None:
            return f"Partido: {ev.title} · {ev.starts_at:%d/%m/%Y}"
    if date_from and date_to:
        return f"{date_from:%d/%m/%Y} – {date_to:%d/%m/%Y}"
    if date_from:
        return f"Desde {date_from:%d/%m/%Y}"
    if date_to:
        return f"Hasta {date_to:%d/%m/%Y}"
    return "Sin filtro de fecha"
