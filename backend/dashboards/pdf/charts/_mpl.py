"""matplotlib helpers shared across chart renderers.

Centralizes:
- Headless backend setup so matplotlib never tries to open a window
  in the docker container (would crash on import).
- Common figure sizing + style.
- `figure_to_flowable()` — render a matplotlib Figure to PNG bytes
  and wrap it as a reportlab Image with the right physical width so
  it lands nicely inside the page frame.
"""

from __future__ import annotations

import contextlib
import contextvars
import io
from typing import Any

# IMPORTANT: set the backend before importing pyplot. "Agg" = no GUI.
import matplotlib
matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, Spacer  # noqa: E402


# Landscape A4 content width (PAGE_MARGIN-trimmed) ~ 27cm.
# Portrait ~ 18cm. The default `image_width_cm=22` works for landscape
# pages with a small horizontal margin; portrait callers pass 18.
DEFAULT_LANDSCAPE_WIDTH_CM = 22.0
DEFAULT_PORTRAIT_WIDTH_CM = 17.5

# Maximum cm a single widget can use for its content. Reduced when the
# orchestrator packs two (or more) widgets onto the same row by setting
# this context for the duration of the widget render.
#
# Default (None) means "use the renderer's natural width" — i.e. the
# old behavior for code paths that don't set it.
_WIDGET_CONTENT_WIDTH_CM: contextvars.ContextVar[float | None] = (
    contextvars.ContextVar("pdf_widget_content_width_cm", default=None)
)


@contextlib.contextmanager
def widget_content_width(width_cm: float | None):
    """Set the per-widget content width budget for the duration of a
    `render_widget_for_pdf(...)` call. Renderers read it via
    `current_widget_width_cm()` or by leaving `width_cm` off the
    `figure_to_flowable(...)` call."""
    token = _WIDGET_CONTENT_WIDTH_CM.set(width_cm)
    try:
        yield
    finally:
        _WIDGET_CONTENT_WIDTH_CM.reset(token)


def current_widget_width_cm(default: float | None = None) -> float | None:
    """Returns the currently-active per-widget content width in cm, or
    `default` when no orchestrator has set one (full-width path)."""
    value = _WIDGET_CONTENT_WIDTH_CM.get()
    return value if value is not None else default


def setup_axes(ax) -> None:
    """Apply a consistent, print-friendly style. Subtle grid, no top
    or right spines, muted tick color."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#9ca3af")
    ax.spines["bottom"].set_color("#9ca3af")
    ax.tick_params(colors="#6b7280", labelsize=8)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.5, zorder=0)


def figure_to_flowable(
    fig,
    *,
    width_cm: float | None = None,
    height_cm: float | None = None,
):
    """Render `fig` to PNG bytes, return as a reportlab Image.

    Width-selection priority (highest first):
    1. Explicit `width_cm` argument — but clamped to the active
       widget-content-width context when the chart would overflow its
       cell (e.g. a "24cm wide" chart placed into a half-width row).
       Height is scaled proportionally on clamp so the aspect ratio
       is preserved.
    2. Active widget-content-width context (set by the orchestrator
       when packing widgets into multi-column rows).
    3. `DEFAULT_LANDSCAPE_WIDTH_CM` fallback.

    Default height is the 2.2:1 width/height aspect ratio. Pass
    `height_cm` explicitly when the chart benefits from a different
    one — e.g. tall horizontal bar charts that should fill the page
    top-to-bottom.
    """
    ctx_width = current_widget_width_cm()
    if width_cm is None:
        final_width = ctx_width if ctx_width is not None else DEFAULT_LANDSCAPE_WIDTH_CM
        final_height = height_cm if height_cm is not None else (final_width / 2.2)
    else:
        if ctx_width is not None and ctx_width < width_cm:
            scale = ctx_width / width_cm
            final_width = ctx_width
            final_height = (height_cm * scale) if height_cm is not None else (final_width / 2.2)
        else:
            final_width = width_cm
            final_height = height_cm if height_cm is not None else (final_width / 2.2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf, width=final_width * cm, height=final_height * cm)
    img._restrictSize(final_width * cm, final_height * cm)
    return img


def figsize_for_current_width(
    height_in: float = 4.5,
    *,
    default_cm: float = DEFAULT_LANDSCAPE_WIDTH_CM,
    min_width_in: float = 4.5,
) -> tuple[float, float]:
    """Matplotlib figsize tuned to the active widget cell width.

    When the orchestrator packs two widgets onto a row, the cell is
    only ~half the page width. If the matplotlib figsize stays fixed
    at e.g. (11, 4.5) inches but the PNG gets placed at half width,
    the text labels effectively shrink in half and become unreadable.
    Tracking the figsize to the target width keeps font sizes physical.

    `height_in` is the chart height in inches — pass the renderer's
    preferred aspect ratio. `min_width_in` clamps the lower bound so
    matplotlib doesn't refuse to lay out at tiny sizes.
    """
    target_cm = current_widget_width_cm(default=default_cm) or default_cm
    return (max(min_width_in, target_cm / 2.54), height_in)


def shrink_player_name(name: str) -> str:
    """Same convention as the frontend: 'Juan Pérez' → 'J. Pérez'.
    Keeps the bar-chart X-axis legible at 25-30 player labels wide."""
    parts = name.strip().split()
    if len(parts) <= 1:
        return name
    return f"{parts[0][0]}. {parts[-1]}"
