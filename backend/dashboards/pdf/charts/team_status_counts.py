"""Renderer for `team_status_counts` — squad availability bars."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import figsize_for_current_width, figure_to_flowable, setup_axes
from ..scaffold import styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    stages = payload.get("stages") or []
    if payload.get("empty") or not stages:
        return [
            Paragraph(
                payload.get("error") or "Sin datos de disponibilidad.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    labels = [s["label"] for s in stages]
    counts = [s["count"] for s in stages]
    bar_colors = [s.get("color") or "#6b7280" for s in stages]

    fig, ax = plt.subplots(figsize=figsize_for_current_width(3.0, default_cm=18.0))
    setup_axes(ax)
    bars = ax.bar(labels, counts, color=bar_colors, zorder=2)
    for bar, count in zip(bars, counts):
        if count > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2, count,
                str(count), ha="center", va="bottom",
                fontsize=10, fontweight="bold", color="#0f172a",
            )
    ax.set_ylabel("Jugadores", fontsize=8, color="#6b7280")
    ax.set_ylim(0, max(counts) * 1.18 if counts else 1)
    fig.tight_layout()

    elements = [figure_to_flowable(fig)]

    total = payload.get("total") or sum(counts)
    available = payload.get("available_count") or 0
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        f"<b>{available}</b> de <b>{total}</b> jugadores disponibles para entrenar/jugar.",
        body["body"],
    ))
    elements.append(Spacer(1, 6 * mm))
    return elements


register("team_status_counts", _render)
