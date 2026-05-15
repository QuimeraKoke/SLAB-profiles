"""Renderer for `team_daily_grouped_bars` — N bars per day + optional
total-line overlay (e.g. Check-IN's Total Bienestar)."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import figsize_for_current_width, figure_to_flowable, setup_axes
from ..scaffold import styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    buckets = payload.get("buckets") or []
    fields = payload.get("fields") or []
    if payload.get("empty") or not buckets or not fields:
        return [
            Paragraph(
                payload.get("error") or "Sin datos en el período.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    n_buckets = len(buckets)
    n_fields = len(fields)
    bar_width = 0.8 / n_fields
    xs = np.arange(n_buckets)

    fig, ax = plt.subplots(figsize=figsize_for_current_width(4.5))
    setup_axes(ax)

    for i, f in enumerate(fields):
        offsets = xs + (i - (n_fields - 1) / 2) * bar_width
        values = [b.get("values", {}).get(f["key"]) for b in buckets]
        # Use np.nan for missing so matplotlib leaves a gap.
        cleaned = [float(v) if v is not None else np.nan for v in values]
        ax.bar(
            offsets, cleaned,
            width=bar_width, color=f.get("color") or "#6366f1",
            label=f.get("label", f["key"]), zorder=2,
        )

    ax.set_xticks(xs)
    ax.set_xticklabels([b["label"] for b in buckets], fontsize=8, rotation=0)

    y_min = payload.get("y_min")
    y_max = payload.get("y_max")
    if isinstance(y_min, (int, float)) and isinstance(y_max, (int, float)):
        ax.set_ylim(y_min, y_max)

    # Optional total-line overlay on a secondary Y axis (sums can have a
    # different scale than per-field — e.g. Check-IN bars 1-5 + total 5-25).
    if payload.get("show_total_line"):
        totals = [b.get("total") for b in buckets]
        if any(t is not None for t in totals):
            ax2 = ax.twinx()
            ax2.spines["top"].set_visible(False)
            ax2.tick_params(colors="#6b7280", labelsize=8)
            total_color = payload.get("total_color") or "#111827"
            ax2.plot(
                xs,
                [float(t) if t is not None else np.nan for t in totals],
                marker="o", linewidth=2, color=total_color,
                label=payload.get("total_label") or "Total",
                zorder=4,
            )
            ty_min = payload.get("total_y_min")
            ty_max = payload.get("total_y_max")
            if isinstance(ty_min, (int, float)) and isinstance(ty_max, (int, float)):
                ax2.set_ylim(ty_min, ty_max)

    ax.legend(fontsize=7, loc="upper left", frameon=False, ncol=min(n_fields, 5))
    fig.tight_layout()
    return [figure_to_flowable(fig), Spacer(1, 6 * mm)]


register("team_daily_grouped_bars", _render)
