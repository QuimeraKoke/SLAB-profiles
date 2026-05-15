"""Renderer for `team_distribution` — distribution of latest values
across the roster.

On the web this is an interactive vertical histogram (hover to see
per-bin count). In the PDF there's no hover, so we render the same
data as a **horizontal** bar chart: each row is a bin labeled with
its range, bar length = number of players, color = band color. Easier
to read on paper: bin ranges are written out (not inferred from X-axis
ticks) and the count sits at the end of each bar."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from . import register
from ._mpl import (
    current_widget_width_cm,
    figsize_for_current_width,
    figure_to_flowable,
    setup_axes,
)
from ..scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles


def _render(widget, payload: dict[str, Any]) -> list:
    if payload.get("empty"):
        body = styles()
        return [
            Paragraph(
                payload.get("error") or "Sin datos para este widget.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    bins = payload.get("bins") or []
    if not bins:
        return _render({}, {"empty": True})

    field = payload.get("field") or {}
    unit = field.get("unit") or ""

    counts = [b["count"] for b in bins]
    colors_per_bin = [b.get("color") or "#6d28d9" for b in bins]
    labels = [_bin_label(b, unit) for b in bins]
    n_bins = len(bins)

    # Modest height: distributions are usually 5-10 bins. ~0.6cm per
    # bin keeps bars chunky without consuming a whole page.
    target_height_cm = max(5.0, min(11.0, 0.6 * n_bins + 2.5))
    fig, ax = plt.subplots(
        figsize=figsize_for_current_width(target_height_cm / 2.54),
    )
    setup_axes(ax)
    ax.spines["bottom"].set_visible(False)
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.5, zorder=0)

    y_positions = list(range(n_bins))
    ax.barh(y_positions, counts, color=colors_per_bin, height=0.72, zorder=2)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()  # lowest bin on top → reads top-to-bottom
    ax.tick_params(axis="x", labelsize=7)
    ax.set_xlabel("Jugadores", fontsize=8, color="#6b7280")

    # Count label at the end of each bar.
    max_count = max(counts) if counts else 0
    pad = max(0.15, max_count * 0.02)
    for j, count in enumerate(counts):
        if count > 0:
            ax.text(
                count + pad, j, str(count),
                va="center", ha="left",
                fontsize=8, fontweight="bold", color="#0f172a",
            )
    # Add a little headroom on the right for the bar-end labels so they
    # never get clipped against the frame.
    if max_count > 0:
        ax.set_xlim(0, max_count * 1.12)

    fig.tight_layout()

    elements: list = [figure_to_flowable(fig, height_cm=target_height_cm)]

    # Band-counts chip strip below the histogram.
    band_counts = payload.get("band_counts") or []
    if band_counts:
        elements.append(Spacer(1, 4 * mm))
        elements.append(_band_chips(band_counts))

    # Stats summary (N, media, mediana, min, max).
    stats = payload.get("stats") or {}
    if stats:
        elements.append(Spacer(1, 3 * mm))
        elements.append(_stats_row(stats, unit))

    elements.append(Spacer(1, 6 * mm))
    return elements


def _bin_label(b: dict, unit: str) -> str:
    """Format a bin's range as a y-axis label.

    Picks 0, 1, or 2 decimals heuristically: if both edges are whole
    numbers we drop the decimals; if the bin is narrower than 1 we
    show 2 decimals; otherwise 1. Unit is appended once at the end.
    """
    low = b.get("low")
    high = b.get("high")
    if low is None or high is None:
        return str(b.get("label", ""))
    width = high - low
    if low == int(low) and high == int(high):
        lo_s, hi_s = f"{int(low)}", f"{int(high)}"
    elif width < 1:
        lo_s, hi_s = f"{low:.2f}", f"{high:.2f}"
    else:
        lo_s, hi_s = f"{low:.1f}", f"{high:.1f}"
    suffix = f" {unit}" if unit else ""
    return f"{lo_s} – {hi_s}{suffix}"


def _band_chips(band_counts: list) -> Any:
    rows = [
        [b.get("label", "") for b in band_counts],
        [str(b.get("count", 0)) for b in band_counts],
    ]
    style_cmds: list = [
        ("FONT", (0, 0), (-1, 0), "Helvetica", 7),
        ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 11),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_MUTED),
        ("TEXTCOLOR", (0, 1), (-1, 1), COLOR_PRIMARY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Per-column color swatch on the label row.
    for i, b in enumerate(band_counts):
        color = b.get("color")
        if color:
            try:
                style_cmds.append(
                    ("BACKGROUND", (i, 0), (i, 0), colors.HexColor(color)),
                )
                style_cmds.append(("TEXTCOLOR", (i, 0), (i, 0), colors.white))
            except (ValueError, TypeError):
                pass
    # Span the chip strip across the active widget width so the chips
    # don't overflow a half-width cell.
    content_cm = current_widget_width_cm(default=20.0)
    width = max(1.6 * cm, content_cm * cm / max(1, len(band_counts)))
    tbl = Table(rows, colWidths=[width] * len(band_counts), hAlign="CENTER")
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _stats_row(stats: dict, unit: str) -> Any:
    fmt = lambda v: "—" if v is None else f"{float(v):.2f}{(' ' + unit) if unit else ''}"
    items = [
        ("N", str(stats.get("n", 0))),
        ("Media", fmt(stats.get("mean"))),
        ("Mediana", fmt(stats.get("median"))),
        ("Min", fmt(stats.get("min"))),
        ("Max", fmt(stats.get("max"))),
    ]
    rows = [[label for label, _ in items], [value for _, value in items]]
    # Match the cell width when packed alongside another widget.
    content_cm = current_widget_width_cm(default=15.0)
    col_w = max(1.6 * cm, (content_cm * cm) / len(items))
    tbl = Table(rows, colWidths=[col_w] * len(items), hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica", 7),
        ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 10),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_MUTED),
        ("TEXTCOLOR", (0, 1), (-1, 1), COLOR_PRIMARY),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


register("team_distribution", _render)
