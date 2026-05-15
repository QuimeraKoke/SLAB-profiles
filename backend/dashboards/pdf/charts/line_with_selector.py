"""Renderer for `line_with_selector` — single line chart of the
default field over time. The dropdown UX collapses in print, so we
render every field as overlaid lines on the same axes."""

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
    points = payload.get("points") or []
    if payload.get("empty") or not points or not fields:
        return [
            Paragraph(
                payload.get("error") or "Sin lecturas en el período.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # `points` is a list of {recorded_at, values: {field_key: number}}.
    # We plot one line per field — gives readers the full picture
    # since the print version can't expose the dropdown.
    fig, ax = plt.subplots(figsize=(9, 4))
    setup_axes(ax)

    iso_labels = [p.get("recorded_at", "")[:10] for p in points]
    xs = list(range(len(points)))
    for f in fields:
        fk = f["key"]
        ys = []
        for p in points:
            v = (p.get("values") or {}).get(fk)
            ys.append(float(v) if v is not None else float("nan"))
        ax.plot(
            xs, ys, marker="o", linewidth=2,
            label=f.get("label", fk),
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(iso_labels, fontsize=7, rotation=30, ha="right")
    ax.legend(fontsize=7, loc="best", frameon=False)
    fig.tight_layout()
    return [
        figure_to_flowable(fig, width_cm=17.5),
        Spacer(1, 6 * mm),
    ]


register("line_with_selector", _render)
