"""Reference-band utilities shared across apps.

`TemplateField.reference_ranges` is a list of dicts shaped like
`{"label": str, "min": float?, "max": float?, "color": "#RRGGBB"?, "alert": bool?}`.
This module centralizes the two operations that multiple call sites need:

1. **band_for_value(value, bands)** — which band does a numeric reading fall
   into? Used by the team_distribution resolver (bin coloring) and the
   threshold evaluator (BAND alert rules).
2. **alert_bands(bands)** — which bands should fire an alert? Default
   heuristic picks the single "reddest" band by RGB warmth; admins can
   override per-band with `"alert": true` (to add) or `"alert": false`
   (to exclude).

Keep this module dependency-light — pure Python, no Django imports —
so it can be unit-tested without spinning up the ORM.
"""
from __future__ import annotations

from typing import Any

# Minimum red dominance (R - max(G, B)) for the heuristic to consider a
# color "alert-worthy". 50/255 ≈ 20% — high enough to filter out muted
# palettes (light yellows, beiges) but low enough that #dc2626 (the
# tailwind red-600 the seeds use) clears it comfortably.
_REDNESS_THRESHOLD = 50


def band_for_value(value: float, bands: list[Any]) -> dict[str, Any] | None:
    """Return the first reference band the value falls into, or None.

    Bands are matched in declared order (first match wins). Bounds are
    both-inclusive, matching the validator's semantics in
    `exams.models.TemplateField.clean()` where adjacent bands may share
    a boundary value (curr.min == prev.max). With first-match-wins, the
    boundary defaults to the LOWER band — predictable and stable.
    """
    for band in bands:
        if not isinstance(band, dict):
            continue
        b_min = band.get("min")
        b_max = band.get("max")
        if (b_min is None or value >= b_min) and (b_max is None or value <= b_max):
            return band
    return None


def alert_bands(bands: list[Any]) -> list[dict[str, Any]]:
    """Return the subset of `bands` that should trigger alerts.

    Resolution order:
      1. If any band has `alert: True` explicitly, return ALL such bands.
         The admin has spoken; no heuristic needed.
      2. Otherwise, pick the single "reddest" band by RGB warmth, IF its
         redness score clears `_REDNESS_THRESHOLD`. Bands explicitly
         flagged `alert: False` are excluded from this fallback.
      3. If no band qualifies (no colors set / all cool palettes), return
         an empty list — the rule simply never fires.
    """
    if not isinstance(bands, list):
        return []

    # Explicit opt-in wins outright.
    explicit_on = [
        b for b in bands
        if isinstance(b, dict) and b.get("alert") is True
    ]
    if explicit_on:
        return explicit_on

    # Heuristic fallback: redness wins. Skip explicit opt-outs.
    candidates: list[tuple[dict[str, Any], int]] = []
    for b in bands:
        if not isinstance(b, dict):
            continue
        if b.get("alert") is False:
            continue
        candidates.append((b, _redness_score(b.get("color"))))
    if not candidates:
        return []
    best, score = max(candidates, key=lambda pair: pair[1])
    if score < _REDNESS_THRESHOLD:
        return []
    return [best]


def _redness_score(hex_color: Any) -> int:
    """Return how 'warm/red' a hex color is, on a -255..255 scale.

    Positive numbers mean red dominates; negative means green or blue
    dominates. Returns 0 for any non-string / unparseable input.
    """
    if not isinstance(hex_color, str):
        return 0
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c + c for c in h)
    if len(h) != 6:
        return 0
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return 0
    return r - max(g, b)
