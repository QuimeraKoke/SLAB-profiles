"""Renderer for `grouped_bar` — recent takes × fields matrix.

PDF version is intentionally tabular, not graphical. Per-player PDFs
were too noisy with one matplotlib bar chart per metric; coaches
asked for dense tables they can scan. Each row is one take (most
recent first); each column is a configured field. Cells show the
numeric value with its unit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import (
    COLOR_MUTED,
    COLOR_PRIMARY,
    COLOR_RULE,
    styles,
    wrap_header_cells,
)


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    fields = payload.get("fields") or []
    takes = payload.get("takes") or payload.get("columns") or []
    if payload.get("empty") or not takes or not fields:
        return [
            Paragraph(
                payload.get("error") or "Sin tomas recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # Header row: "Fecha" + each field's display label (with unit).
    # Wrapped in Paragraphs so long labels (e.g. "HSR > 19.8 km/h (m)")
    # break to a second line instead of overflowing the column.
    header_labels = ["Fecha"] + [_field_header(f) for f in fields]
    rows: list[list] = [wrap_header_cells(header_labels, font_size=8)]

    # Most-recent take first — easier to scan when checking the latest
    # reading. The resolver typically returns oldest-first.
    for t in reversed(takes):
        cells = t.get("cells") or t.get("values") or {}
        line: list = [_fmt_date(t)]
        for f in fields:
            v = cells.get(f["key"]) if isinstance(cells, dict) else None
            if isinstance(v, dict):
                v = v.get("value")
            line.append(_fmt_value(v, f.get("unit", "")))
        rows.append(line)

    content_cm = current_widget_width_cm(default=17.5)
    date_w = min(2.8, content_cm * 0.20) * cm
    other_w = max(1.5 * cm, (content_cm * cm - date_w) / max(1, len(fields)))

    tbl = Table(
        rows,
        colWidths=[date_w] + [other_w] * len(fields),
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle([
        # Header background; the header cells themselves are Paragraphs
        # so the white-bold styling lives on the Paragraph, not here.
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("FONT", (0, 1), (0, -1), "Helvetica", 8.5),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [tbl, Spacer(1, 6 * mm)]


def _field_header(field: dict) -> str:
    label = field.get("label") or field.get("key", "")
    unit = field.get("unit")
    return f"{label} ({unit})" if unit else str(label)


def _fmt_date(take: dict) -> str:
    raw = take.get("label") or take.get("recorded_at") or take.get("date") or ""
    if not raw:
        return "—"
    try:
        return datetime.fromisoformat(str(raw)).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        # `label` from the resolver is sometimes already formatted.
        return str(raw)[:10]


def _fmt_value(value, unit: str) -> str:
    if value is None or value == "":
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == int(v):
        return f"{int(v)}{(' ' + unit) if unit else ''}"
    return f"{v:.2f}{(' ' + unit) if unit else ''}"


register("grouped_bar", _render)
