"""Renderer for `comparison_table` — per-player last-N takes side
by side, with deltas. Renders as a designed table."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    fields = payload.get("fields") or []
    takes = payload.get("takes") or payload.get("columns") or []
    rows_data = payload.get("rows") or []
    if payload.get("empty") or not rows_data:
        return [
            Paragraph(
                payload.get("error") or "Sin tomas recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    header_take_labels = [str(t.get("label") or t.get("recorded_at", "")) for t in takes]
    header = ["Campo"] + header_take_labels + ["Δ"]
    rows = [header]
    for r in rows_data:
        row = [r.get("label") or r.get("field_key") or ""]
        for cell in r.get("cells", []):
            row.append(_fmt(cell.get("value"), r.get("unit", "")))
        # Last delta column.
        delta = r.get("delta")
        row.append(_delta_label(delta, r.get("unit", "")))
        rows.append(row)

    tbl = Table(rows, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
    ]))
    return [tbl, Spacer(1, 6 * mm)]


def _fmt(value, unit: str) -> str:
    if value is None or value == "":
        return "—"
    try:
        v = float(value)
        if v == int(v):
            return f"{int(v)}{(' ' + unit) if unit else ''}"
        return f"{v:.2f}{(' ' + unit) if unit else ''}"
    except (TypeError, ValueError):
        return str(value)


def _delta_label(delta, unit: str) -> str:
    if delta is None:
        return "—"
    try:
        v = float(delta)
    except (TypeError, ValueError):
        return str(delta)
    arrow = "▲" if v > 0 else "▼" if v < 0 else "•"
    return f"{arrow} {abs(v):.2f}{(' ' + unit) if unit else ''}"


register("comparison_table", _render)
