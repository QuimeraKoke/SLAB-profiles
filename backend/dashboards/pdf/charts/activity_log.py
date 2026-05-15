"""Renderer for `activity_log` (per-player) — same shape as
team_activity_log but no player column (player is implicit)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    entries = payload.get("entries") or []
    if payload.get("empty") or not entries:
        return [
            Paragraph(
                payload.get("error") or "Sin registros recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    rows = [["Fecha", "Plantilla", "Detalle"]]
    for e in entries:
        rows.append([
            _fmt_iso(e.get("recorded_at")),
            e.get("template_name", "") or "—",
            Paragraph(_fields_to_summary(e.get("fields") or []), body["body"]),
        ])

    tbl = Table(rows, colWidths=[2.6 * cm, 3.5 * cm, 11.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [tbl, Spacer(1, 6 * mm)]


def _fmt_iso(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso[:10]


def _fields_to_summary(fields: list[dict]) -> str:
    parts = []
    for f in fields:
        value = f.get("value")
        if value is None or value == "":
            continue
        v_str = str(value)
        if len(v_str) > 80:
            v_str = v_str[:78] + "…"
        parts.append(f"<b>{f.get('label') or f.get('key') or ''}:</b> {v_str}")
    return " · ".join(parts) or "—"


register("activity_log", _render)
