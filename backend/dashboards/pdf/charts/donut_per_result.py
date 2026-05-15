"""Renderer for `donut_per_result` — one donut per take, slices per field."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import figure_to_flowable, setup_axes
from ..scaffold import styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    fields = payload.get("fields") or []
    takes = payload.get("takes") or payload.get("results") or []
    if payload.get("empty") or not takes or not fields:
        return [
            Paragraph(
                payload.get("error") or "Sin tomas recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    n_takes = len(takes)
    cols = min(n_takes, 3)
    rows_layout = (n_takes + cols - 1) // cols
    fig, axes = plt.subplots(rows_layout, cols, figsize=(9, 3.5 * rows_layout))
    if rows_layout == 1 and cols == 1:
        axes = [[axes]]
    elif rows_layout == 1:
        axes = [axes]
    elif cols == 1:
        axes = [[ax] for ax in axes]

    for i, take in enumerate(takes):
        ax = axes[i // cols][i % cols]
        cells = take.get("cells") or take.get("values") or {}
        labels = []
        sizes = []
        for f in fields:
            fk = f["key"]
            v = cells.get(fk) if isinstance(cells, dict) else None
            if isinstance(v, dict):
                v = v.get("value")
            try:
                fv = float(v) if v is not None else 0
            except (TypeError, ValueError):
                fv = 0
            if fv > 0:
                labels.append(f.get("label", fk))
                sizes.append(fv)
        if sizes:
            ax.pie(
                sizes, labels=labels, autopct="%1.1f%%",
                textprops={"fontsize": 7},
                wedgeprops=dict(width=0.4),
            )
        ax.set_title(
            str(take.get("label") or take.get("recorded_at", ""))[:16],
            fontsize=8, color="#374151",
        )

    # Hide unused subplots.
    for k in range(n_takes, rows_layout * cols):
        axes[k // cols][k % cols].axis("off")
    fig.tight_layout()
    return [figure_to_flowable(fig, width_cm=17.5), Spacer(1, 6 * mm)]


register("donut_per_result", _render)
