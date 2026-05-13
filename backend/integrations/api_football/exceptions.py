"""Exception hierarchy for the API-Football integration.

Callers catch `ApiFootballError` for "any integration failure", or the
specific subclasses when they want to react differently to (e.g.) a
rate-limit vs. a bad-key.
"""
from __future__ import annotations


class ApiFootballError(Exception):
    """Base for every API-Football integration failure."""


class ApiFootballAuthError(ApiFootballError):
    """401 / 403 — bad or missing API key, or the plan doesn't include
    the requested endpoint."""


class ApiFootballRateLimitError(ApiFootballError):
    """429 — exceeded the per-minute or per-day quota for the current plan."""


class ApiFootballUpstreamError(ApiFootballError):
    """5xx, transport error, or unparseable response from API-Football."""


class ApiFootballBadResponse(ApiFootballError):
    """200 OK but the response body's `errors` field reports a logical
    error (bad parameters, unknown team id, etc.)."""
