"""Lightweight per-call LLM usage + cost telemetry.

Emits one structured INFO line per Anthropic Messages call so we can see real
token volumes, prompt-cache hit rates, and an estimated $ per feature — the
visibility the cost audit flagged as missing. Grep prod logs for `llm_usage`.

The `dashboards.llm_usage` logger is wired to the console at INFO in
`settings.LOGGING`; without that it would be filtered (app loggers default to
WARNING+). Never raises — telemetry must not break a request.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("dashboards.llm_usage")

# USD per 1M tokens (input, output). Rough, for a log-line estimate only — keep
# roughly in sync with platform pricing. Cache read ≈ 0.1× input, cache write
# ≈ 1.25× input (default 5-min TTL). Prefix-match so dated IDs resolve.
_PRICE = {
    "claude-fable-5":   (10.0, 50.0),
    "claude-opus-4-8":  (5.0, 25.0),
    "claude-opus-4-7":  (5.0, 25.0),
    "claude-opus-4-6":  (5.0, 25.0),
    "claude-sonnet-5":  (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _rate(model: str) -> tuple[float, float]:
    for key, rate in _PRICE.items():
        if (model or "").startswith(key):
            return rate
    return (0.0, 0.0)


def log_usage(site: str, model: str, response) -> None:
    """Log token usage + an estimated cost for one Messages call. Never raises."""
    try:
        u = getattr(response, "usage", None)
        if u is None:
            return
        inp = getattr(u, "input_tokens", 0) or 0
        out = getattr(u, "output_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        in_rate, out_rate = _rate(model)
        est = (
            inp * in_rate + cw * in_rate * 1.25 + cr * in_rate * 0.1 + out * out_rate
        ) / 1_000_000
        logger.info(
            "llm_usage site=%s model=%s in=%d out=%d cache_w=%d cache_r=%d est_usd=%.5f",
            site, model, inp, out, cw, cr, est,
        )
    except Exception:  # noqa: BLE001 — telemetry must never break a request
        logger.debug("llm_usage logging failed", exc_info=True)
