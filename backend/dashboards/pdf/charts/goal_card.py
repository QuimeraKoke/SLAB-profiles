"""Renderer for `goal_card` — per-player active goals."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ..scaffold import COLOR_MUTED, COLOR_OK, COLOR_PRIMARY, COLOR_RULE, COLOR_WARN, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    cards = payload.get("cards") or []
    if payload.get("empty") or not cards:
        return [
            Paragraph(
                "Sin objetivos activos en este departamento.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    rows = [["Métrica", "Objetivo", "Actual", "Vence", "Estado"]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
    ]
    for i, c in enumerate(cards, start=1):
        op = c.get("operator") or ""
        target = c.get("target_value")
        current = c.get("current_value")
        unit = c.get("field_unit") or ""
        progress = c.get("progress") or {}
        achieved = progress.get("achieved")
        rows.append([
            c.get("field_label") or c.get("field_key") or "",
            f"{op} {_fmt(target, unit)}",
            _fmt(current, unit),
            c.get("due_date", ""),
            "Logrado ✓" if achieved else "En progreso",
        ])
        if achieved:
            style_cmds.append(("TEXTCOLOR", (4, i), (4, i), COLOR_OK))
        else:
            style_cmds.append(("TEXTCOLOR", (4, i), (4, i), COLOR_WARN))

    tbl = Table(rows, hAlign="LEFT")
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


def _fmt(value, unit: str) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
        if v == int(v):
            return f"{int(v)}{(' ' + unit) if unit else ''}"
        return f"{v:.2f}{(' ' + unit) if unit else ''}"
    except (TypeError, ValueError):
        return str(value)


register("goal_card", _render)
