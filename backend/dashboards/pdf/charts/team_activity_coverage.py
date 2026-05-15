"""Renderer for `team_activity_coverage` — roster × templates table
of days since the last result, with green/yellow/red tinting."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_PRIMARY, COLOR_RULE, styles


_GREEN = "#dcfce7"
_YELLOW = "#fef9c3"
_RED = "#fee2e2"
_GRAY = "#f3f4f6"


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    columns = payload.get("columns") or []
    rows_data = payload.get("rows") or []
    thresholds = payload.get("thresholds") or {"green_max": 30, "yellow_max": 60}
    green_max = thresholds.get("green_max", 30)
    yellow_max = thresholds.get("yellow_max", 60)

    if not columns or not rows_data:
        return [
            Paragraph(
                "Sin datos de cobertura de evaluaciones.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    header = ["Jugador"] + [c.get("label", c.get("template_slug", "")) for c in columns]
    rows = [header]
    cell_tints: list[tuple[int, int, str]] = []
    for i, r in enumerate(rows_data, start=1):
        cells = r.get("cells") or {}
        line = [r.get("player_name", "")]
        for j, c in enumerate(columns, start=1):
            cell = cells.get(c.get("template_slug") or c.get("key"))
            if not cell or cell.get("status") == "never":
                line.append("—")
                cell_tints.append((j, i, _GRAY))
                continue
            days = cell.get("days_since")
            line.append(f"{days}d" if days is not None else "—")
            if isinstance(days, (int, float)):
                if days <= green_max:
                    tint = _GREEN
                elif days <= yellow_max:
                    tint = _YELLOW
                else:
                    tint = _RED
                cell_tints.append((j, i, tint))
        rows.append(line)

    content_width = current_widget_width_cm(default=26.0) * cm
    player_col = min(4.5 * cm, content_width * 0.30)
    other_col = max(1.6 * cm, (content_width - player_col) / max(1, len(columns)))

    tbl = Table(rows, colWidths=[player_col] + [other_col] * len(columns), hAlign="LEFT")
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
    ]
    for col, row, hex_color in cell_tints:
        style_cmds.append(("BACKGROUND", (col, row), (col, row), colors.HexColor(hex_color)))
    tbl.setStyle(TableStyle(style_cmds))

    as_of = payload.get("as_of") or ""
    legend = Paragraph(
        f"Verde ≤ {green_max}d · Amarillo {green_max + 1}–{yellow_max}d · "
        f"Rojo > {yellow_max}d · Gris = sin registros. As of {as_of}.",
        body["body_muted"],
    )
    return [tbl, Spacer(1, 2 * mm), legend, Spacer(1, 6 * mm)]


register("team_activity_coverage", _render)
