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
from .chart_data_tables import (
    CHART_TYPES_WITH_DATA_TABLE,
    build_data_table,
    expected_column_count,
)
from .injury_summary import player_injury_summary
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

# Per-player chart types that produce tall, page-spanning tables.
# These skip the title+content `KeepTogether` wrap so reportlab can
# start filling the current page instead of jumping to a fresh one.
# (Multi-column packing was also dropped on the player report — every
# widget renders at full portrait width, see `_pack_widgets_into_rows`.)
_SPLITTABLE_CHART_TYPES = {
    "activity_log",
    "comparison_table",
    "grouped_bar",      # takes × fields table, may span pages
    "body_map_heatmap", # region × count table
}


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

    # NOTE: the player-level executive summary was intentionally removed
    # per client feedback — on a per-player portrait report the team-wide
    # status columns add no signal, the KPI strip duplicates info already
    # in the layout, and the page was cluttering the report. Team PDFs
    # still emit the exec summary; only the player path skips it.

    # For Médico reports: surface the player's injury history (active +
    # recent closed) as the FIRST content block. Client feedback: the
    # doctor's primary question is "is this player injured right now?",
    # so the answer can't be buried under a layout of metrics.
    if department.slug == "medico":
        injury_block = player_injury_summary(player)
        if injury_block:
            sections.append({
                "title": "Lesiones",
                "flowables": injury_block,
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
                # Empty section titles render headerless in scaffold —
                # widgets already carry their own titles, so a fallback
                # like "Sección" was just visual noise.
                "title": section.title or "",
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
    """Player-PDF packing rule: ONE widget per row, full page width.

    The web's column_span is honored on screen, but in the printed
    per-player report the client asked for each chart/table to use the
    full portrait width — 3-across charts in a 17.5cm column rendered
    as tiny illegible thumbnails. The team report keeps the multi-row
    packing (landscape has the horizontal room)."""
    return [[w] for w in widgets]


# Chart-on-left, table-on-right cell-width split. Tuned so even the
# wide donut keeps a circular aspect and the data table has room for
# 2–3 value columns without clipping. The two cells share the portrait
# content width minus a small inter-cell gutter.
_CHART_CELL_CM = 10.5
_TABLE_CELL_CM = _PORTRAIT_CONTENT_WIDTH_CM - _CHART_CELL_CM - 0.4

# When the data table needs more than this many columns to render, the
# side-by-side layout starts squeezing each column to an unreadable
# width. In that case we switch to a stacked layout: chart at full
# portrait width on top, table at full width below.
_SIDE_BY_SIDE_MAX_COLS = 3


def _chart_with_data_twin(widget, payload: dict, body_styles):
    """Build a chart-with-data twin for a chart widget.

    Two layout modes depending on the data table's column count:
    - **Side-by-side** (≤ `_SIDE_BY_SIDE_MAX_COLS` cols): chart in the
      left cell, data table in the right cell.
    - **Stacked** (> `_SIDE_BY_SIDE_MAX_COLS` cols): chart at full
      portrait width, data table below it at full width. Wider tables
      (e.g. multi_line with 4+ series) need the room.

    Returns None when the data table couldn't be built — caller falls
    back to single-cell rendering.
    """
    n_cols = expected_column_count(widget, payload) or 0
    if n_cols > _SIDE_BY_SIDE_MAX_COLS:
        return _chart_stacked_table(widget, payload, body_styles)
    return _chart_beside_table(widget, payload, body_styles)


def _title_flowables(widget, body_styles) -> list:
    flow: list = [Paragraph(widget.title, body_styles["body"])]
    if widget.description:
        flow.append(Paragraph(widget.description, body_styles["body_muted"]))
    flow.append(Spacer(1, 2 * mm))
    return flow


def _chart_beside_table(widget, payload: dict, body_styles):
    """Side-by-side layout: chart left, data table right."""
    data_tbl = build_data_table(widget, payload, max_width_cm=_TABLE_CELL_CM)
    if data_tbl is None:
        return None

    chart_flowables = render_widget_for_pdf(
        widget, payload, max_width_cm=_CHART_CELL_CM,
    )
    # build_data_table returns either a Table or a list of flowables
    # (the donut path emits a caption + spacer + table).
    table_cell = data_tbl if isinstance(data_tbl, list) else [data_tbl]

    row = Table(
        [[chart_flowables, table_cell]],
        colWidths=[_CHART_CELL_CM * cm, _TABLE_CELL_CM * cm],
        hAlign="LEFT",
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether(_title_flowables(widget, body_styles) + [row])


def _chart_stacked_table(widget, payload: dict, body_styles):
    """Stacked layout: chart at full portrait width on top, then the
    data table at full width below. Used when the table has more than
    `_SIDE_BY_SIDE_MAX_COLS` columns and won't fit beside the chart."""
    chart_flowables = render_widget_for_pdf(
        widget, payload, max_width_cm=_PORTRAIT_CONTENT_WIDTH_CM,
    )
    data_tbl = build_data_table(
        widget, payload, max_width_cm=_PORTRAIT_CONTENT_WIDTH_CM,
    )
    if data_tbl is None:
        return None
    table_block = data_tbl if isinstance(data_tbl, list) else [data_tbl]

    # KeepTogether wraps the title block so the chart can't orphan
    # from its title; the data table is allowed to flow to the next
    # page if the chart alone fills the remainder of the current one.
    return [
        KeepTogether(_title_flowables(widget, body_styles) + chart_flowables),
        Spacer(1, 3 * mm),
        *table_block,
    ]


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
        payload = payloads[0]

        # Chart-type widgets with a data twin → render either as
        # chart-beside-table (narrow tables, ≤3 cols) or chart-on-top
        # of full-width-table (wider tables). The reader always gets
        # both the visual trend AND exact numbers.
        if w.chart_type in CHART_TYPES_WITH_DATA_TABLE and not payload.get("empty"):
            twin = _chart_with_data_twin(w, payload, body_styles)
            if twin is not None:
                # Stacked path returns a list of flowables; side-by-side
                # returns a single KeepTogether. Spread either case so
                # both layouts get the same trailing inter-widget spacer.
                if isinstance(twin, list):
                    return [*twin, Spacer(1, 8 * mm)]
                return [twin, Spacer(1, 8 * mm)]

        # Fallback: full-width single widget (table widgets, empty
        # chart payloads, etc.).
        flow = _widget_inner_flowables(
            w, payload, body_styles,
            max_width_cm=_PORTRAIT_CONTENT_WIDTH_CM,
        )
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
