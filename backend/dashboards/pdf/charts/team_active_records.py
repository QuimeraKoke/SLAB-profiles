"""Renderer for `team_active_records` — list of currently-active
date-range records (e.g. active medications)."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    if payload.get("empty"):
        return [
            Paragraph(
                payload.get("error") or "Sin registros activos.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    columns = payload.get("columns") or []
    rows_data = payload.get("rows") or []
    active = payload.get("active_count") or len(rows_data)
    total = payload.get("total") or "?"
    as_of = payload.get("as_of") or ""

    header_row = ["Jugador"] + [c.get("label", c.get("key", "")) for c in columns]
    table_rows = [header_row]
    for row in rows_data:
        vals = row.get("values") or {}
        # Wrap value cells in Paragraph so long medication strings
        # word-wrap inside the column instead of overflowing.
        line = [Paragraph(row.get("player_name", ""), body["body"])]
        for c in columns:
            v = vals.get(c.get("key"))
            line.append(Paragraph(_fmt(v, c.get("unit", "")), body["body"]))
        table_rows.append(line)

    # Stretch across the active widget width — full landscape (26.5cm)
    # when alone, or the cell width when packed alongside another
    # widget. Player column scales down for narrow cells.
    content_width = current_widget_width_cm(default=26.5) * cm
    player_col = min(4.5 * cm, content_width * 0.30)
    n_value_cols = max(1, len(columns))
    value_col = (content_width - player_col) / n_value_cols
    tbl = Table(
        table_rows,
        colWidths=[player_col] + [value_col] * n_value_cols,
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
    ]))

    summary = Paragraph(
        f"<b>{active}</b> de <b>{total}</b> jugadores con registro activo "
        f"al {as_of}.",
        body["body_muted"],
    )
    return [tbl, Spacer(1, 2 * mm), summary, Spacer(1, 6 * mm)]


def _fmt(value, unit: str) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (int, float)):
        return f"{value}{(' ' + unit) if unit else ''}"
    return str(value)


register("team_active_records", _render)
