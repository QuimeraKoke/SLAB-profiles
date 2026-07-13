"""Per-player rolling statistics for intra-individual monitoring.

Pure numeric helpers — the caller supplies the ordered value series (oldest →
newest); there is no DB access here, so this is trivially unit-testable and
shared by:

  * the AlertRule ``zscore`` kind — GPS/load "desviación vs. su basal" (§1.2), and
  * the CK traffic-light widget — colour-by-individual-deviation (§4).

The *baseline* is the player's own recent history (the **prior** readings,
excluding the value under test). Centre = moving average or EWMA; spread =
sample standard deviation of the prior window. A z-score needs ≥2 prior
readings and non-zero spread; otherwise it returns ``None`` (caller shows
"sin basal suficiente").
"""

from __future__ import annotations

import math
from typing import Sequence


def _clean(xs: Sequence[float]) -> list[float]:
    return [float(x) for x in xs if x is not None]


def mean(xs: Sequence[float]) -> float | None:
    xs = _clean(xs)
    return sum(xs) / len(xs) if xs else None


def stdev(xs: Sequence[float]) -> float | None:
    """Sample standard deviation (n-1). None if fewer than 2 values."""
    xs = _clean(xs)
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def ewma(xs: Sequence[float], span: int | None = None) -> float | None:
    """Exponentially weighted moving average, ``xs`` oldest → newest.
    ``span`` maps to alpha = 2/(span+1) (pandas convention); defaults to the
    series length."""
    xs = _clean(xs)
    if not xs:
        return None
    if not span or span < 1:
        span = len(xs)
    alpha = 2.0 / (span + 1.0)
    acc = xs[0]
    for x in xs[1:]:
        acc = alpha * x + (1 - alpha) * acc
    return acc


def baseline(prior: Sequence[float], method: str = "moving_avg", span: int | None = None) -> float | None:
    """Centre of the prior window: EWMA (``method='ewma'``) or plain mean."""
    if method == "ewma":
        return ewma(prior, span)
    return mean(prior)


def cv(xs: Sequence[float]) -> float | None:
    """Coefficient of variation (%) — sd / mean × 100. CK's CV mode."""
    m = mean(xs)
    s = stdev(xs)
    if not m or s is None:
        return None
    return s / m * 100.0


def deviation(value, prior, *, method: str = "moving_avg", span: int | None = None) -> dict | None:
    """Describe ``value`` against its own prior window.

    Returns ``{"centre", "sd", "z", "pct", "cv"}`` or ``None`` when there is no
    baseline at all (empty prior / non-numeric value).

    - ``z``   = (value - centre) / sd           — intra-individual z-score
    - ``pct`` = (value - centre) / centre × 100 — % deviation from basal
    - ``cv``  = sd / centre × 100               — coefficient of variation

    ``z`` is ``None`` when there is <2 prior readings or zero spread; ``pct`` /
    ``cv`` are ``None`` when the centre is zero. The caller decides what to do
    with a partial result (e.g. fall back to an absolute band).
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    c = baseline(prior, method, span)
    if c is None:
        return None
    s = stdev(prior)
    return {
        "centre": c,
        "sd": s,
        "z": (value - c) / s if s not in (None, 0) else None,
        "pct": (value - c) / c * 100.0 if c else None,
        "cv": s / c * 100.0 if (s is not None and c) else None,
    }
