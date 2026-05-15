"""Renderer for `team_goal_progress` — roster × goals matrix with
achieved / in-progress / missed badges. Rendered as a wide table
with per-cell tint by status."""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import current_widget_width_cm
from ..scaffold import COLOR_MUTED, COLOR_OK, COLOR_PRIMARY, COLOR_RULE, COLOR_WARN, styles


_STATUS_TINTS = {
    "achieved":    "#dcfce7",  # light green
    "in_progress": "#fef9c3",  # light yellow
    "missed":      "#fee2e2",  # light red
    "no_data":     "#f3f4f6",  # neutral gray
}


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    columns = payload.get("columns") or []
    rows_data = payload.get("rows") or []
    summary = payload.get("summary") or {}
    if not columns or not rows_data:
        return [
            Paragraph(
                "Sin metas activas en este departamento.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    header = ["Jugador"] + [c.get("label", c.get("key", "")) for c in columns]
    rows = [header]
    cell_tints: list[tuple[int, int, str]] = []
    for i, r in enumerate(rows_data, start=1):
        cells = r.get("cells") or {}
        line = [r.get("player_name", "")]
        for j, c in enumerate(columns, start=1):
            cell = cells.get(c.get("key"))
            if cell is None:
                line.append("—")
                continue
            badge = cell.get("status") or "no_data"
            current = cell.get("current_value")
            target = c.get("target_value") or cell.get("target_value")
            label_parts = []
            if current is not None:
                label_parts.append(_fmt(current))
            if target is not None:
                label_parts.append(f"/ {_fmt(target)}")
            line.append(" ".join(label_parts) or _badge_label(badge))
            tint = _STATUS_TINTS.get(badge)
            if tint:
                cell_tints.append((j, i, tint))
        rows.append(line)

    content_width = current_widget_width_cm(default=26.0) * cm
    player_col = min(4.5 * cm, content_width * 0.30)
    other_col = max(1.8 * cm, (content_width - player_col) / max(1, len(columns)))

    tbl = Table(rows, colWidths=[player_col] + [other_col] * len(columns), hAlign="LEFT")
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
    ]
    for col, row, hex_color in cell_tints:
        try:
            style_cmds.append(("BACKGROUND", (col, row), (col, row), colors.HexColor(hex_color)))
        except (ValueError, TypeError):
            continue
    tbl.setStyle(TableStyle(style_cmds))

    elements = [tbl, Spacer(1, 2 * mm)]
    if summary:
        elements.append(Paragraph(
            f"<b>{summary.get('achieved', 0)}</b> logradas · "
            f"<b>{summary.get('in_progress', 0)}</b> en progreso · "
            f"<b>{summary.get('missed', 0)}</b> incumplidas · "
            f"<b>{summary.get('no_data', 0)}</b> sin datos · "
            f"total {summary.get('total', 0)}.",
            body["body_muted"],
        ))
    elements.append(Spacer(1, 6 * mm))
    return elements


def _fmt(value) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def _badge_label(status: str) -> str:
    return {
        "achieved": "✓",
        "in_progress": "•",
        "missed": "✗",
        "no_data": "—",
    }.get(status, "—")


register("team_goal_progress", _render)
