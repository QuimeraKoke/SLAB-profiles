"""Renderer for `grouped_bar` — grouped bars per recent take."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import figure_to_flowable, setup_axes
from ..scaffold import styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    fields = payload.get("fields") or []
    takes = payload.get("takes") or payload.get("columns") or []
    if payload.get("empty") or not takes or not fields:
        return [
            Paragraph(
                payload.get("error") or "Sin tomas recientes.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    n_takes = len(takes)
    n_fields = len(fields)
    bar_w = 0.8 / n_fields if n_fields else 0.4
    xs = np.arange(n_takes)
    take_labels = [str(t.get("label") or t.get("recorded_at", "")) for t in takes]

    fig, ax = plt.subplots(figsize=(9, 4))
    setup_axes(ax)
    for i, f in enumerate(fields):
        fk = f["key"]
        values = []
        for t in takes:
            cells = t.get("cells") or t.get("values") or {}
            v = cells.get(fk) if isinstance(cells, dict) else None
            if isinstance(v, dict):
                v = v.get("value")
            values.append(float(v) if v is not None else 0)
        offsets = xs + (i - (n_fields - 1) / 2) * bar_w
        ax.bar(offsets, values, width=bar_w, label=f.get("label", fk))
    ax.set_xticks(xs)
    ax.set_xticklabels(take_labels, fontsize=7, rotation=30, ha="right")
    ax.legend(fontsize=7, loc="best", frameon=False)
    fig.tight_layout()
    return [figure_to_flowable(fig, width_cm=17.5), Spacer(1, 6 * mm)]


register("grouped_bar", _render)
