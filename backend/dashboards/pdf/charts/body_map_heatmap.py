"""Renderer for `body_map_heatmap` — body silhouette with region
shading. The frontend uses a custom SVG body; in PDF we render as a
compact table of region:count rows ranked by count desc, which keeps
the information density without needing to ship the SVG body."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    items = payload.get("items") or []
    if payload.get("empty") or not items:
        return [
            Paragraph(
                payload.get("error") or "Sin lesiones registradas.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # Top regions first.
    ranked = sorted(items, key=lambda x: -(x.get("count") or 0))[:20]
    total = sum(it.get("count", 0) for it in items)

    rows = [["Región", "Cantidad", "%"]]
    for it in ranked:
        count = it.get("count", 0)
        pct = (count / total * 100) if total else 0
        rows.append([
            it.get("label", it.get("region", "")),
            str(count),
            f"{pct:.1f}%",
        ])

    tbl = Table(rows, colWidths=[7 * cm, 2.5 * cm, 2.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
    ]))

    summary = Paragraph(
        f"Total acumulado: <b>{total}</b> registros · "
        f"{len(items)} regiones afectadas.",
        body["body_muted"],
    )
    return [tbl, Spacer(1, 2 * mm), summary, Spacer(1, 6 * mm)]


register("body_map_heatmap", _render)
