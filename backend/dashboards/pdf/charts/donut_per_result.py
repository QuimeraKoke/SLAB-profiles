"""Renderer for `donut_per_result` — one donut per take.

The resolver returns the per-take breakdown under the key `donuts`
(NOT `takes`/`results` — those keys never existed in the live API
payload). Each donut has its own `recorded_at` + `slices` list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import matplotlib.pyplot as plt
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import current_widget_width_cm, figure_to_flowable
from ..scaffold import styles


# A single donut is a circle; if we give the figure a wide-rectangle
# aspect (e.g. 17.5 × 6cm) matplotlib renders the circle constrained
# by the smaller dimension, so it sits small in the middle with empty
# space on the sides. Cap per-donut height at this value so a roomy
# portrait page still gets a generous-but-not-page-eating donut.
_MAX_DONUT_CELL_CM = 11.0


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    donuts = payload.get("donuts") or []
    if payload.get("empty") or not donuts:
        return [
            Paragraph(
                payload.get("error") or "Sin tomas recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # Limit to the most recent N takes so a year of weekly readings
    # doesn't produce a 50-donut sheet. Latest first.
    donuts = sorted(donuts, key=lambda d: d.get("recorded_at") or "", reverse=True)[:6]

    n = len(donuts)
    cols = min(n, 3)
    rows_layout = (n + cols - 1) // cols

    # Size each donut cell roughly square — a circle in a wide rectangle
    # ends up small with empty side margins, and the user reads it as
    # "the chart got squashed". Per-cell width comes from the available
    # widget content width / number of columns; height matches width
    # (capped) so the donut fills the cell.
    content_cm = current_widget_width_cm(default=17.5) or 17.5
    per_cell_cm = min(_MAX_DONUT_CELL_CM, content_cm / cols)
    fig_width_in = content_cm / 2.54
    fig_height_in = (per_cell_cm * rows_layout) / 2.54
    target_height_cm = per_cell_cm * rows_layout
    fig, axes = plt.subplots(rows_layout, cols, figsize=(fig_width_in, fig_height_in))

    # Normalize axes shape to a 2D list so the index math below works
    # for every (rows, cols) combo without special cases.
    if rows_layout == 1 and cols == 1:
        axes_grid = [[axes]]
    elif rows_layout == 1:
        axes_grid = [list(axes)]
    elif cols == 1:
        axes_grid = [[ax] for ax in axes]
    else:
        axes_grid = [list(row) for row in axes]

    for i, donut in enumerate(donuts):
        ax = axes_grid[i // cols][i % cols]
        slices = donut.get("slices") or []
        labels: list[str] = []
        sizes: list[float] = []
        colors_list: list[str] = []
        for s in slices:
            try:
                v = float(s.get("value") or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                labels.append(s.get("label", s.get("key", "")))
                sizes.append(v)
                colors_list.append(s.get("color") or "#6b7280")
        if sizes:
            ax.pie(
                sizes,
                labels=labels,
                colors=colors_list,
                autopct="%1.1f%%",
                textprops={"fontsize": 7},
                wedgeprops=dict(width=0.4),
            )
        ax.set_title(_fmt_date(donut.get("recorded_at")), fontsize=8, color="#374151")

    # Hide unused subplots in the trailing slots.
    for k in range(n, rows_layout * cols):
        axes_grid[k // cols][k % cols].axis("off")

    fig.tight_layout()
    return [
        figure_to_flowable(fig, height_cm=target_height_cm),
        Spacer(1, 6 * mm),
    ]


def _fmt_date(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)[:10]


register("donut_per_result", _render)
