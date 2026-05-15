"""Chart renderers for the PDF builder.

Each function takes a resolver payload (the SAME shape the live
frontend consumes) and returns a list of reportlab flowables (usually
an Image of a matplotlib chart + an optional summary table).

Adding a new chart type:
1. Write a function `render_<chart_type>(widget, payload) -> list`.
2. Register it in `_RENDERERS` below.
3. The orchestrator (team_report.py / player_report.py) auto-routes.

Unregistered chart_types fall back to `_render_generic_table` which
emits a key/value dump of the payload — always SOMETHING readable,
never an empty box.

P1: only the generic fallback exists. P2/P3 register matplotlib
renderers per chart_type.
"""

from __future__ import annotations

from typing import Any, Callable

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from dashboards.pdf.charts._mpl import widget_content_width
from dashboards.pdf.scaffold import (
    COLOR_MUTED,
    COLOR_PRIMARY,
    COLOR_RULE,
    styles,
)


_RENDERERS: dict[str, Callable[..., list]] = {}


def render_widget_for_pdf(
    widget,
    payload: dict[str, Any],
    *,
    max_width_cm: float | None = None,
) -> list:
    """Dispatch entry — picks a renderer by `widget.chart_type` or
    falls back to a generic table.

    `max_width_cm` (optional) sets a content-width budget for this
    widget. The orchestrator passes it when packing two widgets onto
    the same row so each chart/table renders inside half (or less) of
    the page width. Renderers read it via
    `_mpl.current_widget_width_cm()`."""
    renderer = _RENDERERS.get(widget.chart_type, _render_generic_table)
    with widget_content_width(max_width_cm):
        try:
            return renderer(widget, payload)
        except Exception as exc:  # noqa: BLE001 — never let one widget kill the PDF
            body = styles()
            return [
                Paragraph(
                    f"<i>Error renderizando '{widget.chart_type}': "
                    f"{type(exc).__name__}.</i>",
                    body["body_muted"],
                ),
                Spacer(1, 4 * mm),
            ]


# --- Fallback ------------------------------------------------------------


def _render_generic_table(widget, payload: dict[str, Any]) -> list:
    """Tabular dump of the payload so a chart_type without a dedicated
    renderer still produces SOMETHING the reader can glean info from.
    Skips internal noise (`chart_type`, `empty`, `title`)."""
    body = styles()
    rows: list[tuple[str, str]] = []
    skip = {"chart_type", "empty", "title", "error", "description"}
    for key, value in payload.items():
        if key in skip:
            continue
        if isinstance(value, list):
            rows.append((key, f"{len(value)} elementos"))
        elif isinstance(value, dict):
            rows.append((key, f"{len(value)} claves"))
        else:
            rows.append((key, str(value)[:80]))

    if not rows:
        return [
            Paragraph(
                "Sin datos para este widget en el período seleccionado.",
                body["body_muted"],
            ),
            Spacer(1, 4 * mm),
        ]

    tbl = Table(rows, colWidths=[55 * mm, None])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), COLOR_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), COLOR_PRIMARY),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, COLOR_RULE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [tbl, Spacer(1, 4 * mm)]


def register(chart_type: str, renderer: Callable[..., list]) -> None:
    """Used by per-chart modules to plug themselves in. Keeps the
    fallback table available for everything else."""
    _RENDERERS[chart_type] = renderer


# Side-effect import so every per-chart module registers itself. Order
# doesn't matter — each module owns its own register() call. Added
# *after* `register()` is defined so the modules can import it without
# circularity.
from . import (  # noqa: E402, F401
    # Team-side renderers
    team_active_records as _team_active_records,
    team_activity_coverage as _team_activity_coverage,
    team_activity_log as _team_activity_log,
    team_alerts as _team_alerts,
    team_daily_grouped_bars as _team_daily_grouped_bars,
    team_distribution as _team_distribution,
    team_goal_progress as _team_goal_progress,
    team_horizontal_comparison as _team_horizontal_comparison,
    team_leaderboard as _team_leaderboard,
    team_match_summary as _team_match_summary,
    team_roster_matrix as _team_roster_matrix,
    team_stacked_bars as _team_stacked_bars,
    team_status_counts as _team_status_counts,
    team_trend_line as _team_trend_line,
    # Per-player renderers
    activity_log as _activity_log,
    body_map_heatmap as _body_map_heatmap,
    comparison_table as _comparison_table,
    donut_per_result as _donut_per_result,
    goal_card as _goal_card,
    grouped_bar as _grouped_bar,
    line_with_selector as _line_with_selector,
    multi_line as _multi_line,
    player_alerts as _player_alerts,
)
