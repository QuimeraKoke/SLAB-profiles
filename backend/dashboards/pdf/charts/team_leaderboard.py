"""Renderer for `team_leaderboard` (single mode, list + vertical bars).

Multi-field mode falls back to the generic table for now (P3 if
needed). The vertical-bars style honors `reference_lines`,
`reference_bands`, `y_min`/`y_max`, and `decimals` from the payload —
same logic as the live frontend so the PDF matches what the user
sees on screen.
"""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import (
    current_widget_width_cm,
    figsize_for_current_width,
    figure_to_flowable,
    setup_axes,
    shrink_player_name,
)
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles

import matplotlib.pyplot as plt


def _render(widget, payload: dict[str, Any]) -> list:
    if payload.get("empty"):
        return _empty_block(payload)

    style = payload.get("style") or "list"
    mode = payload.get("mode") or "single"

    if mode == "multi_field":
        # Defer to a generic table — these charts are rare and the
        # data structure is per-player-per-field. P3 candidate.
        return _multi_field_table(widget, payload)

    if style == "vertical_bars":
        return _vertical_bars(widget, payload)

    # Default: list-style podium.
    return _list_table(widget, payload)


def _empty_block(payload: dict[str, Any]) -> list:
    body = styles()
    msg = payload.get("error") or "Sin datos para este widget."
    return [Paragraph(msg, body["body_muted"]), Spacer(1, 4 * mm)]


def _list_table(widget, payload: dict[str, Any]) -> list:
    """Podium-style ordered list. Compact table with rank/name/value/samples."""
    body = styles()
    field = payload.get("field") or {}
    unit = field.get("unit") or ""
    decimals = payload.get("decimals")

    rows = [["#", "Jugador", "Valor", "Tomas"]]
    style_cmds = _table_base_style()
    for r in payload.get("rows", []):
        rows.append([
            str(r.get("rank", "")),
            r.get("player_name", ""),
            _fmt(r.get("value"), unit, decimals),
            str(r.get("samples", "")),
        ])

    # Scale columns to the active widget width so the podium fits in
    # a half-row cell instead of overflowing it.
    content_cm = current_widget_width_cm(default=14.2)
    rank_w = min(1.2, content_cm * 0.085) * cm
    samples_w = min(2.0, content_cm * 0.14) * cm
    value_w = min(3.0, content_cm * 0.22) * cm
    name_w = max(3.0 * cm, content_cm * cm - rank_w - samples_w - value_w)
    tbl = Table(
        rows,
        colWidths=[rank_w, name_w, value_w, samples_w],
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


def _vertical_bars(widget, payload: dict[str, Any]) -> list:
    """Vertical bar chart with reference lines + bands + Y-axis zoom."""
    rows = payload.get("rows") or []
    field = payload.get("field") or {}
    unit = field.get("unit") or ""
    decimals = payload.get("decimals")
    ref_lines = payload.get("reference_lines") or (
        [payload["reference_line"]] if payload.get("reference_line") else []
    )
    ref_bands = payload.get("reference_bands") or []
    y_min_explicit = payload.get("y_min")
    y_max_explicit = payload.get("y_max")

    if not rows:
        return _empty_block(payload)

    names = [shrink_player_name(r.get("player_name", "")) for r in rows]
    values = [float(r.get("value") or 0) for r in rows]

    data_max = max(values) if values else 0
    for ln in ref_lines:
        data_max = max(data_max, float(ln.get("value", 0)))
    for b in ref_bands:
        if b.get("max") is not None:
            data_max = max(data_max, float(b["max"]))

    # Start from the configured y-range (gives the user-requested
    # centésima-level zoom for tight metrics like Densidad urinaria),
    # then EXTEND to fit any out-of-range data. Clipping outliers led
    # to invisible bars at the baseline and identical-looking clamped
    # bars at the top — readers couldn't distinguish 1.050 from 1.040
    # because they both rendered at the chart ceiling.
    y_min = float(y_min_explicit) if isinstance(y_min_explicit, (int, float)) else 0.0
    if isinstance(y_max_explicit, (int, float)):
        y_max = float(y_max_explicit)
    else:
        # 12% headroom above the tallest bar so the bar-end value labels
        # (e.g. "95.66") don't get clipped against the top of the frame.
        y_max = data_max * 1.12 if data_max > 0 else 1.0

    data_min_actual = min(values) if values else y_min
    data_max_actual = max(data_max, max(values) if values else y_max)
    span = max(1e-9, max(y_max, data_max_actual) - min(y_min, data_min_actual))
    pad = span * 0.05
    if data_min_actual < y_min:
        y_min = data_min_actual - pad
    if data_max_actual > y_max:
        y_max = data_max_actual + pad
    if y_max <= y_min:
        y_max = y_min + 1.0

    # The orchestrator forces this widget to full-page width regardless
    # of column_span, so target the full landscape content (~26.5cm) by
    # default. Wider canvas means more horizontal room between bars →
    # value labels (e.g. "95.66 / 92.51") stop overlapping their
    # neighbours at 25-30-player rosters.
    fig, ax = plt.subplots(figsize=figsize_for_current_width(5.0, default_cm=26.5))
    setup_axes(ax)

    # Bands first (drawn behind bars).
    for b in ref_bands:
        b_min = b.get("min")
        b_max = b.get("max")
        lo = float(b_min) if b_min is not None else y_min
        hi = float(b_max) if b_max is not None else y_max
        lo = max(lo, y_min)
        hi = min(hi, y_max)
        if hi <= lo:
            continue
        ax.axhspan(lo, hi, color=b.get("color", "#fef3c7"), alpha=0.35, zorder=0)
        if b.get("label"):
            ax.text(
                len(names) - 0.5, (lo + hi) / 2, b["label"],
                ha="right", va="center", fontsize=7,
                color="#4b5563", alpha=0.8,
            )

    # Bars. Anchor each bar to `y_min` instead of 0 so a zoomed scale
    # (e.g. Densidad urinaria: y_min=1.000) still produces visibly
    # different bar heights for close values. Otherwise a 1.000 bar
    # and a 0.980 bar both render as full-height-to-baseline rectangles
    # and the chart loses all visual signal.
    xs = list(range(len(names)))
    ax.bar(
        xs,
        [v - y_min for v in values],
        bottom=y_min,
        color="#0ea5e9", width=0.7, zorder=2,
    )
    ax.set_xticks(xs)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=7)
    ax.set_ylim(y_min, y_max)

    # Value label above each bar. Y-range is now guaranteed to include
    # every value (see auto-extend logic above), so we don't need the
    # ↑/↓ overflow markers — every label sits directly above its bar.
    for x, v in zip(xs, values):
        if v <= 0:
            continue
        ax.text(
            x, v, _fmt(v, "", decimals),
            ha="center", va="bottom", fontsize=6.5, color="#0f172a",
            clip_on=True,
        )

    # Reference lines.
    for ln in ref_lines:
        val = float(ln.get("value", 0))
        color = ln.get("color", "#0ea5e9")
        ax.axhline(val, color=color, linestyle="--", linewidth=1.0, zorder=3)
        label = ln.get("label") or _fmt(val, unit, decimals)
        ax.text(
            len(names) - 0.5, val, f"  {label}",
            ha="right", va="bottom", fontsize=7, color=color,
        )

    if unit:
        ax.set_ylabel(unit, fontsize=8, color="#6b7280")
    fig.tight_layout()

    # Place at the full landscape content width (26.5cm) so the chart
    # spans the page edge-to-edge. Height tracks the matplotlib figsize
    # (5.0 inches → ~12.7 cm) so aspect ratio is preserved and the
    # in-figure font sizes stay physically correct.
    return [
        figure_to_flowable(fig, width_cm=26.5, height_cm=5.0 * 2.54),
        Spacer(1, 6 * mm),
    ]


def _multi_field_table(widget, payload: dict[str, Any]) -> list:
    """Fallback table for multi_field — list every player × every field."""
    body = styles()
    fields = payload.get("fields") or []
    rows = [["#", "Jugador"] + [f.get("label", f.get("key", "")) for f in fields]]
    style_cmds = _table_base_style()
    for r in payload.get("rows", []):
        if "values" not in r:
            continue
        row = [str(r.get("rank", "")), r.get("player_name", "")]
        for f in fields:
            v = r["values"].get(f.get("key"))
            row.append(_fmt(v, f.get("unit", ""), None))
        rows.append(row)
    tbl = Table(rows, hAlign="LEFT")
    tbl.setStyle(TableStyle(style_cmds))
    return [tbl, Spacer(1, 6 * mm)]


def _fmt(value, unit: str, decimals: int | None) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if isinstance(decimals, int):
        return f"{v:.{decimals}f}{(' ' + unit) if unit else ''}"
    if v == int(v):
        return f"{int(v)}{(' ' + unit) if unit else ''}"
    return f"{v:.2f}{(' ' + unit) if unit else ''}"


def _table_base_style() -> list:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
    ]


register("team_leaderboard", _render)
