"""Renderer for `team_horizontal_comparison`. Single-mode renders as
horizontal bars per player (one row = N bars across recent readings,
or one bar per configured field in multi_field mode)."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
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


_SERIES_COLORS = ["#6d28d9", "#9061f9", "#b5a0ff", "#d4caff", "#e9e3ff"]
_FIELD_COLORS = ["#dc2626", "#0ea5e9", "#16a34a", "#f59e0b", "#8b5cf6", "#ec4899"]


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

    mode = payload.get("mode") or "by_reading"
    rows = payload.get("rows") or []
    fields = payload.get("fields") or []
    if not rows or not fields:
        return _render({}, {"empty": True})

    # The "player rows" share name; for the simpler implementation
    # we only handle non-grouped (no position) here. Grouped variant
    # falls back to the generic table.
    if payload.get("grouping") == "position":
        from . import _render_generic_table
        return _render_generic_table(widget, payload)

    default_field_key = payload.get("default_field_key") or fields[0]["key"]

    # Horizontal bars chart fills the landscape page top-to-bottom.
    # With 30 players × 0.5cm per bar + padding ≈ 16cm — leaves a
    # narrow strip for header / footer. Smaller rosters get the chart
    # scaled down proportionally so it doesn't look stretched.
    # Cap at 14.5cm so the chart + its title + description fit in
    # the ~17cm landscape content frame after KeepTogether wraps them.
    # 16cm was right at the page-content limit and caused reportlab to
    # eject a blank page when the title-spacer pushed past the frame.
    target_height_cm = min(14.5, max(7.0, 0.48 * len(rows) + 2))
    # Width: full landscape (24cm) by default; honor the orchestrator
    # cell width when packed alongside another widget. Figsize tracks
    # the physical width so label fonts stay readable at half-width.
    target_width_cm = current_widget_width_cm(default=24.0)
    fig_width_in = max(4.5, target_width_cm / 2.54)
    fig, ax = plt.subplots(figsize=(fig_width_in, target_height_cm / 2.54))
    setup_axes(ax)
    ax.spines["bottom"].set_visible(False)
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.5, zorder=0)
    ax.tick_params(axis="y", labelsize=7)
    ax.tick_params(axis="x", labelsize=7)

    names = [shrink_player_name(r.get("player_name", "")) for r in rows]
    y_positions = list(range(len(names)))

    if mode == "multi_field":
        # Each field on its own subplot — different units (meters vs
        # m/min) can't share an X axis. Reuses the existing `fig`'s
        # axes only for the first field then adds twin-axes for the
        # rest, but cleaner: throw away `fig` and start fresh with
        # subplots(1, n_fields).
        plt.close(fig)
        n_fields = len(fields)
        fig, axes = plt.subplots(
            1, n_fields,
            figsize=(fig_width_in, target_height_cm / 2.54),
            sharey=True,
        )
        if n_fields == 1:
            axes = [axes]
        for i, (f, sub_ax) in enumerate(zip(fields, axes)):
            setup_axes(sub_ax)
            sub_ax.spines["bottom"].set_visible(False)
            sub_ax.grid(axis="x", color="#e5e7eb", linewidth=0.5, zorder=0)
            sub_ax.tick_params(labelsize=7)
            fk = f["key"]
            color = _FIELD_COLORS[i % len(_FIELD_COLORS)]
            values = []
            for r in rows:
                series = r.get("values", {}).get(fk) or []
                values.append(series[0]["value"] if series else 0)
            sub_ax.barh(y_positions, values, color=color, height=0.7)
            unit = f" ({f['unit']})" if f.get("unit") else ""
            sub_ax.set_title(
                f"{f.get('label', fk)}{unit}",
                fontsize=8, color="#374151", pad=4,
            )
            # Show player-name labels on EVERY subplot so each chart
            # is readable on its own — `sharey=True` would otherwise
            # hide them on all but the leftmost subplot, which makes
            # the right-hand chart hard to scan in print (you'd have
            # to track the row across two charts to find a name).
            sub_ax.set_yticks(y_positions)
            sub_ax.set_yticklabels(names)
            sub_ax.tick_params(axis="y", labelleft=True)
            if i == 0:
                sub_ax.invert_yaxis()
        fig.tight_layout()
    else:
        # by_reading: bars within a row = recent readings (most recent first).
        limit = payload.get("limit_per_player") or 3
        bar_height = 0.8 / max(1, limit)
        for j, r in enumerate(rows):
            series = r.get("values", {}).get(default_field_key) or []
            for k, v in enumerate(series[:limit]):
                offset = (k - (limit - 1) / 2) * bar_height
                ax.barh(
                    j + offset, v["value"],
                    height=bar_height,
                    color=_SERIES_COLORS[k % len(_SERIES_COLORS)],
                )
        ax.set_yticks(y_positions)
        ax.set_yticklabels(names)
        ax.invert_yaxis()

    fig.tight_layout()
    return [
        figure_to_flowable(fig, width_cm=target_width_cm, height_cm=target_height_cm),
        Spacer(1, 6 * mm),
    ]


register("team_horizontal_comparison", _render)
