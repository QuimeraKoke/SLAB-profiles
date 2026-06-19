"""Renderer for `training_radar` — entrenamiento vs carga crónica (% partido).

The on-screen widget is a radar; in the PDF/Word report we render the same data
as a compact table (Variable · Entrenamiento · Crónica · %), which reads better
on a printed page than a polar plot.

Resolver payload: `{axes: [{label, unit, training_value, reference_value, pct}],
session_date, empty}`.
"""

from __future__ import annotations

from typing import Any

from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    axes = payload.get("axes") or []
    if payload.get("empty") or not axes:
        return [
            Paragraph("Sin sesión de entrenamiento para comparar.", body["body_muted"]),
            Spacer(1, 4 * mm),
        ]

    rows: list[list] = [["Variable", "Entren.", "Crónica", "%"]]
    for a in axes:
        unit = f" {a['unit']}" if a.get("unit") else ""
        rows.append([
            str(a.get("label", "")),
            f"{_fmt(a.get('training_value'))}{unit}",
            f"{_fmt(a.get('reference_value'))}{unit}",
            f"{_fmt(a.get('pct'))}%",
        ])

    w = current_widget_width_cm(default=17.5) * cm
    tbl = Table(
        rows,
        colWidths=[w * 0.46, w * 0.20, w * 0.20, w * 0.14],
        hAlign="LEFT",
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_MUTED),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    out: list = []
    sd = payload.get("session_date")
    if sd:
        out.append(Paragraph(
            f"Sesión {str(sd)[:10]} · % de la carga crónica de partido",
            body["body_muted"],
        ))
        out.append(Spacer(1, 1.5 * mm))
    out += [tbl, Spacer(1, 6 * mm)]
    return out


def _fmt(value) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{int(v)}" if v == int(v) else f"{v:.1f}"


register("training_radar", _render)
