"""Renderer for `team_match_summary` — compact stat-card strip with
SUM / AVG / STD / MIN / MAX / N per configured field."""

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
    cards = payload.get("cards") or []
    if payload.get("empty") or not cards:
        return [
            Paragraph(
                payload.get("error") or "Sin datos para este partido.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # Header cells get word-wrapping via Paragraph so long field
    # labels don't overlap into the next column.
    from reportlab.lib.styles import ParagraphStyle
    header_style = ParagraphStyle(
        "header_white", fontName="Helvetica-Bold", fontSize=7.5,
        textColor=colors.white, alignment=1, leading=9,
    )

    # Table: rows = stat names, columns = fields. Lets the reader scan
    # any single stat horizontally and any single field vertically.
    header = ["Métrica"] + [
        Paragraph(c.get("label", c.get("field_key", "")), header_style)
        for c in cards
    ]
    stat_rows = [
        ("SUM",  [_fmt(c.get("sum"), c.get("unit", "")) for c in cards]),
        ("AVG",  [_fmt(c.get("avg"), c.get("unit", "")) for c in cards]),
        ("STD",  [_fmt(c.get("std"), c.get("unit", "")) for c in cards]),
        ("MIN",  [_fmt(c.get("min"), c.get("unit", "")) for c in cards]),
        ("MAX",  [_fmt(c.get("max"), c.get("unit", "")) for c in cards]),
        ("N",    [str(c.get("n", 0)) for c in cards]),
    ]
    rows = [header] + [[name, *vals] for name, vals in stat_rows]

    content_cm = current_widget_width_cm(default=24.0)
    col0_width = min(2.0 * cm, content_cm * cm * 0.12)
    other_width = (content_cm * cm - col0_width) / max(1, len(cards))

    tbl = Table(
        rows,
        colWidths=[col0_width] + [other_width] * len(cards),
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 8.5),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
        # Highlight the SUM row — it's usually the headline number.
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f9fafb")),
        ("FONT", (1, 1), (-1, 1), "Helvetica-Bold", 9.5),
    ]))
    return [tbl, Spacer(1, 6 * mm)]


def _fmt(value, unit: str) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == int(v):
        return f"{int(v):,}{(' ' + unit) if unit else ''}"
    return f"{v:.2f}{(' ' + unit) if unit else ''}"


register("team_match_summary", _render)
