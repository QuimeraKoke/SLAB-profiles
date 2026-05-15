"""Renderer for `team_stacked_bars` — horizontal stacked bars per
player (Acc + Dec + Acc&Dec breakdown style)."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import (
    current_widget_width_cm,
    figure_to_flowable,
    setup_axes,
    shrink_player_name,
)
from ..scaffold import styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    rows = payload.get("rows") or []
    fields = payload.get("fields") or []
    if payload.get("empty") or not rows or not fields:
        return [
            Paragraph(
                payload.get("error") or "Sin datos para este widget.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    names = [shrink_player_name(r.get("player_name", "")) for r in rows]
    n_rows = len(rows)

    # Same full-page-height treatment as team_horizontal_comparison —
    # stacked bars need room to breathe at 25-30 players. Capped at
    # 14.5cm so the block (title + chart) fits in the ~17cm landscape
    # content frame under KeepTogether wrapping.
    target_height_cm = min(14.5, max(7.0, 0.48 * n_rows + 2))
    # Track the active widget width so the chart shrinks cleanly when
    # packed alongside another widget. Matplotlib figsize follows so
    # the per-segment labels and player names stay readable.
    target_width_cm = current_widget_width_cm(default=24.0)
    fig_width_in = max(4.5, target_width_cm / 2.54)
    fig, ax = plt.subplots(figsize=(fig_width_in, target_height_cm / 2.54))
    setup_axes(ax)
    ax.spines["bottom"].set_visible(False)
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.5, zorder=0)

    y_positions = np.arange(n_rows)
    # Stack: each segment is offset by the running sum of previous segments
    # in the same row.
    cumulative = np.zeros(n_rows)
    for f in fields:
        fk = f["key"]
        color = f.get("color") or "#6366f1"
        segment = np.array([
            float((r.get("values") or {}).get(fk) or 0)
            for r in rows
        ])
        ax.barh(
            y_positions, segment,
            left=cumulative, color=color, label=f.get("label", fk),
            height=0.7, zorder=2,
        )
        # Per-segment numeric label if the segment is wide enough.
        for j, v in enumerate(segment):
            if v <= 0:
                continue
            ax.text(
                cumulative[j] + v / 2, j, f"{int(v) if v == int(v) else f'{v:.1f}'}",
                ha="center", va="center", fontsize=7, color="#ffffff",
            )
        cumulative += segment

    # Total at the end of each bar.
    for j, total in enumerate(cumulative):
        if total > 0:
            ax.text(
                total, j, f"  {int(total) if total == int(total) else f'{total:.1f}'}",
                ha="left", va="center", fontsize=8, fontweight="bold",
                color="#0f172a",
            )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(names, fontsize=7)
    ax.invert_yaxis()
    ax.legend(fontsize=7, loc="lower right", frameon=False)
    fig.tight_layout()
    return [
        figure_to_flowable(fig, width_cm=target_width_cm, height_cm=target_height_cm),
        Spacer(1, 6 * mm),
    ]


register("team_stacked_bars", _render)
