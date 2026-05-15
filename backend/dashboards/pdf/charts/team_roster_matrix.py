"""Renderer for `team_roster_matrix` — roster × metrics latest-value
table. Rendered as a wide table; band coloring on cells when the
backend provides per-column `reference_ranges`."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


_HEADER_STYLE = ParagraphStyle(
    "roster_matrix_header",
    fontName="Helvetica-Bold",
    fontSize=7.5,
    textColor=colors.white,
    alignment=1,  # center
    leading=9,
)
_PLAYER_HEADER_STYLE = ParagraphStyle(
    "roster_matrix_player_header",
    fontName="Helvetica-Bold",
    fontSize=7.5,
    textColor=colors.white,
    alignment=0,  # left
    leading=9,
)


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    if payload.get("empty"):
        return [
            Paragraph(
                payload.get("error") or "Sin datos para este widget.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    columns = payload.get("columns") or []
    rows_data = payload.get("rows") or []
    if not columns or not rows_data:
        return [
            Paragraph("Sin datos para este widget.", body["body_muted"]),
            Spacer(1, 4 * mm),
        ]

    # Wrap each header cell in a Paragraph so long labels like
    # "Distancia total (m)" or "HSR > 19,8 km/h (m)" word-wrap inside
    # the narrow columns instead of overlapping their neighbors.
    header = [Paragraph("Jugador", _PLAYER_HEADER_STYLE)] + [
        Paragraph(
            f"{c.get('label', c.get('key', ''))}" + (
                f" ({c['unit']})" if c.get("unit") else ""
            ),
            _HEADER_STYLE,
        )
        for c in columns
    ]
    table_rows = [header]
    cell_color_overrides: list[tuple[int, int, str]] = []

    for i, row in enumerate(rows_data, start=1):
        cells = row.get("cells") or {}
        line = [row.get("player_name", "")]
        for j, c in enumerate(columns, start=1):
            cell = cells.get(c.get("key"))
            if cell is None:
                line.append("—")
                continue
            value = cell.get("value")
            line.append(_fmt(value, c.get("unit", "")))
            # Cell coloring from reference_ranges, when configured.
            band_color = _band_color_for(value, c.get("reference_ranges") or [])
            if band_color:
                cell_color_overrides.append((j, i, band_color))
        table_rows.append(line)

    # Compute column widths — full width is ~26cm landscape, but if
    # the orchestrator has packed us into a half-row we get half.
    # Player column shrinks proportionally so the value columns still
    # have breathing room.
    content_width = current_widget_width_cm(default=26.0) * cm
    player_col = min(4.5 * cm, content_width * 0.30)
    other_col = max(1.4 * cm, (content_width - player_col) / max(1, len(columns)))

    tbl = Table(
        table_rows,
        colWidths=[player_col] + [other_col] * len(columns),
        hAlign="LEFT",
    )
    # Note: header cells are Paragraphs, so their font/color/alignment
    # come from `_HEADER_STYLE`. The TableStyle FONT/TEXTCOLOR commands
    # below only apply to body rows.
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for col, row, hex_color in cell_color_overrides:
        try:
            style_cmds.append(
                ("BACKGROUND", (col, row), (col, row), colors.HexColor(hex_color)),
            )
        except (ValueError, TypeError):
            continue
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


def _band_color_for(value, ranges: list[dict]) -> str | None:
    """First-match-wins band lookup, identical to the frontend rule."""
    if value is None or not ranges:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for band in ranges:
        b_min = band.get("min")
        b_max = band.get("max")
        if (b_min is None or v >= b_min) and (b_max is None or v <= b_max):
            return band.get("color")
    return None


def _fmt(value, unit: str) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == int(v):
        return f"{int(v)}{(' ' + unit) if unit else ''}"
    return f"{v:.2f}{(' ' + unit) if unit else ''}"


register("team_roster_matrix", _render)
