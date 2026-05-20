"""Renderer for `line_with_selector`.

The web UI exposes a dropdown so the user picks one field at a time;
in print we render every `available_field` as an overlaid line since
there's no interaction. The resolver returns `available_fields` plus
a `series` *dict* keyed by field_key (one entry per option).
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
    available = payload.get("available_fields") or []
    series_by_field: dict = payload.get("series") or {}
    if payload.get("empty") or not available or not series_by_field:
        return [
            Paragraph(
                payload.get("error") or "Sin lecturas en el período.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    # `series_by_field` maps field_key → list-of-points DIRECTLY
    # (the live API doesn't wrap them in a `{points: ...}` dict).
    # Union of all timestamps across every available field, sorted.
    all_ts = sorted({
        p.get("recorded_at")
        for points in series_by_field.values()
        for p in (points if isinstance(points, list) else [])
        if isinstance(p, dict) and p.get("recorded_at")
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
    for f in available:
        fk = f["key"]
        points = series_by_field.get(fk) or []
        if not isinstance(points, list):
            continue
        ys = [float("nan")] * len(all_ts)
        for p in points:
            if not isinstance(p, dict):
                continue
            ts = p.get("recorded_at")
            v = p.get("value")
            if ts in ts_index and v is not None:
                try:
                    ys[ts_index[ts]] = float(v)
                except (TypeError, ValueError):
                    pass
        # Skip a series that has no values at all — would draw a flat
        # NaN line and pollute the legend.
        if all(y != y for y in ys):  # NaN check (NaN != NaN)
            continue
        unit = f" ({f.get('unit')})" if f.get("unit") else ""
        ax.plot(
            xs, ys,
            marker="o", linewidth=2,
            label=f"{f.get('label', fk)}{unit}",
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


register("line_with_selector", _render)
