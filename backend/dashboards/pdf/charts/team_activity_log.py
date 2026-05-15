"""Renderer for `team_activity_log` — timeline list of recent
ExamResults across the roster (newest first)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    entries = payload.get("entries") or []
    if payload.get("empty") or not entries:
        return [
            Paragraph(
                payload.get("error") or "Sin registros en el período.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    body = styles()
    # Detail cells contain inline <b>...</b> markup — wrap them in a
    # Paragraph so reportlab parses the HTML and word-wraps long text
    # to the column width (raw strings would overflow + show literal tags).
    rows = [["Fecha", "Jugador", "Plantilla", "Detalle"]]
    for e in entries:
        date_str = _fmt_iso(e.get("recorded_at"))
        detail = _fields_to_summary(e.get("fields") or [])
        rows.append([
            date_str,
            e.get("player_name", "") or "—",
            e.get("template_name", "") or "—",
            Paragraph(detail, body["body"]),
        ])

    # Detail column gets the leftover width so long values wrap.
    content_cm = current_widget_width_cm(default=25.4)
    date_w = min(2.6, content_cm * 0.11) * cm
    player_w = min(4.5, content_cm * 0.20) * cm
    tmpl_w = min(3.8, content_cm * 0.16) * cm
    detail_w = max(4.0 * cm, content_cm * cm - date_w - player_w - tmpl_w)
    tbl = Table(
        rows,
        colWidths=[date_w, player_w, tmpl_w, detail_w],
        hAlign="LEFT",
    )
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
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
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
    """Collapse the field list into one compact "Label: value · Label2: value2"
    line that fits the timeline table. Long values get truncated."""
    parts = []
    for f in fields:
        value = f.get("value")
        if value is None or value == "":
            continue
        label = f.get("label") or f.get("key") or ""
        v_str = str(value)
        if len(v_str) > 80:
            v_str = v_str[:78] + "…"
        parts.append(f"<b>{label}:</b> {v_str}")
    return " · ".join(parts) or "—"


register("team_activity_log", _render)
