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
from ..scaffold import (
    COLOR_MUTED,
    COLOR_PRIMARY,
    COLOR_RULE,
    styles,
    wrap_header_cells,
)


# Spanish translations for body-region keys. Mirrors `REGION_LABEL`
# in `frontend/src/components/dashboards/widgets/BodyMapHeatmap.tsx`
# so the PDF reads the same as the web Mapa de lesiones widget.
# Keep this list in sync if a new region is added on either side.
_REGION_LABEL_ES: dict[str, str] = {
    "head": "Cabeza",
    "neck": "Cuello",
    "chest": "Pecho",
    "abdomen": "Abdomen",
    "upper_back": "Espalda alta",
    "lower_back": "Espalda baja",
    "pelvis": "Pelvis",
    "left_shoulder": "Hombro izq.",
    "right_shoulder": "Hombro der.",
    "left_arm": "Brazo izq.",
    "right_arm": "Brazo der.",
    "left_forearm": "Antebrazo izq.",
    "right_forearm": "Antebrazo der.",
    "left_hand": "Mano izq.",
    "right_hand": "Mano der.",
    "left_thigh": "Muslo izq.",
    "right_thigh": "Muslo der.",
    "left_knee": "Rodilla izq.",
    "right_knee": "Rodilla der.",
    "left_calf": "Pantorrilla izq.",
    "right_calf": "Pantorrilla der.",
    "left_foot": "Pie izq.",
    "right_foot": "Pie der.",
}


def _region_label(item: dict) -> str:
    """Prefer an explicit `label` from the payload (the resolver may
    one day attach one); otherwise translate the canonical English
    region key via `_REGION_LABEL_ES`; fall back to the raw key when
    we don't have a translation."""
    label = item.get("label")
    if label:
        return str(label)
    region = item.get("region") or ""
    return _REGION_LABEL_ES.get(region, region)


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

    rows = [wrap_header_cells(["Región", "Cantidad", "%"], align="left")]
    for it in ranked:
        count = it.get("count", 0)
        pct = (count / total * 100) if total else 0
        rows.append([
            _region_label(it),
            str(count),
            f"{pct:.1f}%",
        ])

    tbl = Table(rows, colWidths=[7 * cm, 2.5 * cm, 2.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
    ]))

    summary = Paragraph(
        f"Total acumulado: <b>{total}</b> registros · "
        f"{len(items)} regiones afectadas.",
        body["body_muted"],
    )
    return [tbl, Spacer(1, 2 * mm), summary, Spacer(1, 6 * mm)]


register("body_map_heatmap", _render)
