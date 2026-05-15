"""Renderer for `player_alerts` (per-player) — table of active alerts
ordered by severity then fired_at."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ..scaffold import COLOR_CRIT, COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, COLOR_WARN, styles


_SEVERITY_LABELS = {"critical": "Crítica", "warning": "Adv.", "info": "Info"}
_SEVERITY_COLORS = {
    "critical": COLOR_CRIT, "warning": COLOR_WARN, "info": COLOR_MUTED,
}
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    alerts = payload.get("alerts") or []
    if payload.get("empty") or not alerts:
        return [
            Paragraph(
                payload.get("error") or "Sin alertas activas en este departamento. ✅",
                body["body"],
            ),
            Spacer(1, 4 * mm),
        ]

    sorted_alerts = sorted(
        alerts,
        key=lambda a: (
            _SEVERITY_RANK.get(a.get("severity"), 99),
            -datetime.fromisoformat(a["fired_at"]).timestamp() if a.get("fired_at") else 0,
        ),
    )
    rows = [["Severidad", "Plantilla", "Mensaje", "Fecha"]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, a in enumerate(sorted_alerts, start=1):
        sev = a.get("severity", "info")
        rows.append([
            _SEVERITY_LABELS.get(sev, sev),
            a.get("template_name", "") or "—",
            Paragraph(a.get("message", ""), body["body"]),
            _fmt_date(a.get("fired_at")),
        ])
        style_cmds.append(("TEXTCOLOR", (0, i), (0, i), _SEVERITY_COLORS.get(sev, COLOR_MUTED)))
        style_cmds.append(("FONT", (0, i), (0, i), "Helvetica-Bold", 9))

    tbl = Table(
        rows,
        colWidths=[1.8 * cm, 3.5 * cm, 9.5 * cm, 2.3 * cm],
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso[:10]


register("player_alerts", _render)
