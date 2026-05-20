"""Renderer for `comparison_table` — última toma · variación · semáforo.

Resolver payload shape:
- `columns`: `[{result_id, recorded_at}]` — one per take, oldest first
- `rows`:    `[{key, label, unit, direction_of_good, reference_ranges,
                values: [v1, v2], deltas: [None, delta]}]`

PDF renders:
- Date header columns formatted `dd/mm/yyyy`
- One value per column, semáforo background per band
- A trailing Δ column with arrow + signed delta against the previous take
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
    columns: list[dict] = payload.get("columns") or []
    rows_data: list[dict] = payload.get("rows") or []
    if payload.get("empty") or not rows_data or not columns:
        return [
            Paragraph(
                payload.get("error") or "Sin tomas recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    header_labels = (
        ["Campo"]
        + [_fmt_date(c.get("recorded_at")) for c in columns]
        + ["Δ"]
    )
    table_rows: list[list] = [wrap_header_cells(header_labels, font_size=8.5)]

    # Track per-cell tint based on the row's reference_ranges + value.
    cell_tints: list[tuple[int, int, str]] = []

    for ri, r in enumerate(rows_data, start=1):
        unit = r.get("unit") or ""
        values = r.get("values") or []
        deltas = r.get("deltas") or []
        ref_ranges = r.get("reference_ranges") or []

        line: list = [_field_label(r)]
        for col_idx in range(len(columns)):
            v = values[col_idx] if col_idx < len(values) else None
            line.append(_fmt_value(v, unit))
            band_color = _band_color_for(v, ref_ranges)
            if band_color:
                # First value column is at table-column index 1.
                cell_tints.append((1 + col_idx, ri, band_color))

        # Delta uses the LAST entry — that's the most recent change.
        delta = deltas[-1] if deltas else None
        line.append(_delta_label(delta, unit, r.get("direction_of_good")))
        table_rows.append(line)

    # Width budget — portrait by default, half-width when packed.
    content_cm = current_widget_width_cm(default=17.5)
    label_w = min(5.0, content_cm * 0.32) * cm
    delta_w = min(2.4, content_cm * 0.16) * cm
    value_w = max(2.0 * cm, (content_cm * cm - label_w - delta_w) / max(1, len(columns)))

    tbl = Table(
        table_rows,
        colWidths=[label_w] + [value_w] * len(columns) + [delta_w],
        hAlign="LEFT",
    )

    # Header cells are Paragraphs (so long date labels can wrap); their
    # font/color comes from the Paragraph style, not from these table
    # style commands. Row-0 commands here only set the background.
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
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
    ]
    for col, row, hex_color in cell_tints:
        try:
            style_cmds.append(
                ("BACKGROUND", (col, row), (col, row), colors.HexColor(hex_color)),
            )
            # Light bands need dark text; dark bands invert.
            if _is_dark(hex_color):
                style_cmds.append(("TEXTCOLOR", (col, row), (col, row), colors.white))
        except (ValueError, TypeError):
            continue
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


# --- helpers --------------------------------------------------------------


def _field_label(row: dict) -> str:
    label = row.get("label") or row.get("key", "")
    unit = row.get("unit")
    return f"{label} ({unit})" if unit else str(label)


def _fmt_date(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)[:10]


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


def _delta_label(delta, unit: str, direction_of_good: str | None = None) -> str:
    if delta is None:
        return "—"
    try:
        v = float(delta)
    except (TypeError, ValueError):
        return str(delta)
    arrow = "▲" if v > 0 else "▼" if v < 0 else "•"
    sign = "+" if v > 0 else ""
    return f"{arrow} {sign}{v:.2f}{(' ' + unit) if unit else ''}"


def _band_color_for(value, ranges: list[dict]) -> str | None:
    """First-match-wins band lookup. Matches the frontend rule."""
    if value is None or not ranges:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for band in ranges:
        b_min = band.get("min")
        b_max = band.get("max")
        if (b_min is None or v >= b_min) and (b_max is None or v <= b_max):
            return band.get("color")
    return None


def _is_dark(hex_color: str) -> bool:
    """Rough luminance check so we flip text to white on dark bands."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # Perceived brightness, common formula.
        return (0.299 * r + 0.587 * g + 0.114 * b) < 110
    except (ValueError, IndexError):
        return False


register("comparison_table", _render)
