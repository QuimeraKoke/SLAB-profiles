"""Renderer for `multi_line` — overlaid line chart, one line per series.

The resolver returns data under the `series` key (NOT `points` —
that's a leftover from an early prototype). Each series is
`{key, label, unit, color, points: [{recorded_at, value}]}`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import matplotlib.pyplot as plt
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from . import register
from ._mpl import figsize_for_current_width, figure_to_flowable, setup_axes
from ..scaffold import styles


def _render(widget, payload: dict[str, Any]) -> list:
    body = styles()
    series_list = payload.get("series") or []
    if payload.get("empty") or not series_list:
        return [
            Paragraph(
                payload.get("error") or "Sin lecturas en el período.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # Build the union of timestamps across every series so all lines
    # share an X axis even when a field has sparser readings.
    all_ts = sorted({
        p.get("recorded_at")
        for s in series_list
        for p in s.get("points", [])
        if p.get("recorded_at")
    })
    if not all_ts:
        return [
            Paragraph("Sin lecturas en el período.", body["body_muted"]),
            Spacer(1, 4 * mm),
        ]

    fig, ax = plt.subplots(figsize=figsize_for_current_width(4.0, default_cm=17.5))
    setup_axes(ax)

    xs = list(range(len(all_ts)))
    ts_index = {ts: i for i, ts in enumerate(all_ts)}
    for s in series_list:
        ys = [float("nan")] * len(all_ts)
        for p in s.get("points", []):
            ts = p.get("recorded_at")
            v = p.get("value")
            if ts in ts_index and v is not None:
                try:
                    ys[ts_index[ts]] = float(v)
                except (TypeError, ValueError):
                    pass
        ax.plot(
            xs, ys,
            marker="o", linewidth=2,
            color=s.get("color") or None,
            label=s.get("label") or s.get("key", ""),
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(
        [_fmt_date(ts) for ts in all_ts],
        fontsize=7, rotation=30, ha="right",
    )
    ax.legend(fontsize=7, loc="best", frameon=False)
    fig.tight_layout()
    return [figure_to_flowable(fig), Spacer(1, 6 * mm)]


def _fmt_date(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m")
    except (ValueError, TypeError):
        return str(value)[:10]


register("multi_line", _render)
