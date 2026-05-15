"""Renderer for `team_alerts` — rendered as a compact table of
player × alert count × max severity. The detailed message list is
omitted to keep the PDF dense; the resumen-ejecutivo on page 2
already lists every critical alert."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_CRIT, COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, COLOR_WARN, styles


_SEVERITY_LABELS = {"critical": "Crítica", "warning": "Adv.", "info": "Info"}
_SEVERITY_COLORS = {
    "critical": COLOR_CRIT, "warning": COLOR_WARN, "info": COLOR_MUTED,
}


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    if payload.get("empty"):
        return [
            Paragraph(
                payload.get("error") or "Sin alertas activas en este departamento. ✅",
                body["body"],
            ),
            Spacer(1, 4 * mm),
        ]

    players = payload.get("players") or []
    if not players:
        return [
            Paragraph("Sin alertas activas en este departamento. ✅", body["body"]),
            Spacer(1, 4 * mm),
        ]

    rows = [["Jugador", "Críticas", "Total", "Última alerta"]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (1, 0), (2, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, p in enumerate(players, start=1):
        alerts_summary = ", ".join(
            [a.get("message", "")[:60] for a in (p.get("alerts") or [])[:1]]
        ) or "—"
        rows.append([
            p.get("player_name", ""),
            str(p.get("critical_count", 0)),
            str(p.get("alert_count", 0)),
            alerts_summary,
        ])
        # Color the count cells by severity.
        if p.get("critical_count", 0) > 0:
            style_cmds.append(("TEXTCOLOR", (1, i), (1, i), COLOR_CRIT))
            style_cmds.append(("FONT", (1, i), (1, i), "Helvetica-Bold", 9))

    # Player / Crit / Total / Mensajes — last column gets the slack.
    content_cm = current_widget_width_cm(default=21.2)
    player_w = min(6.0, content_cm * 0.28) * cm
    crit_w = min(2.2, content_cm * 0.11) * cm
    total_w = min(2.0, content_cm * 0.10) * cm
    msgs_w = max(3.0 * cm, content_cm * cm - player_w - crit_w - total_w)
    tbl = Table(
        rows,
        colWidths=[player_w, crit_w, total_w, msgs_w],
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


register("team_alerts", _render)
