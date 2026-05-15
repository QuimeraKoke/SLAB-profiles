"""Renderer for `team_trend_line` — multi-series line chart, team
mean per metric over weekly/monthly buckets. Honors
`grouping: "position"` when present."""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import figsize_for_current_width, figure_to_flowable, setup_axes
from ..scaffold import styles


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

    grouping = payload.get("grouping") or "none"
    fields = payload.get("fields") or []
    buckets = payload.get("buckets") or []
    if not buckets:
        return _render({}, {"empty": True})

    fig, ax = plt.subplots(figsize=figsize_for_current_width(4.5))
    setup_axes(ax)
    xs = list(range(len(buckets)))
    labels = [b["label"] for b in buckets]

    if grouping == "position":
        groups = payload.get("groups") or []
        for g in groups:
            gid = g["id"]
            series = []
            for b in buckets:
                v = (b.get("values_by_group") or {}).get(gid, {})
                # Plot the first field that has a value (single-line per
                # group). Matches the frontend's behaviour for selected
                # default field.
                fk = (fields[0] or {}).get("key") if fields else None
                if fk is None:
                    series.append(None)
                else:
                    series.append(v.get(fk))
            ax.plot(
                xs, [s if s is not None else float("nan") for s in series],
                marker="o", linewidth=2, label=g.get("label") or g.get("name"),
                color=g.get("color"),
            )
    else:
        for f in fields:
            fk = f["key"]
            series = [b.get("values", {}).get(fk) for b in buckets]
            ax.plot(
                xs, [s if s is not None else float("nan") for s in series],
                marker="o", linewidth=2, label=f.get("label", fk),
            )

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
    ax.legend(fontsize=7, loc="best", frameon=False)
    fig.tight_layout()
    return [figure_to_flowable(fig), Spacer(1, 6 * mm)]


register("team_trend_line", _render)
