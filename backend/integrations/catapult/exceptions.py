"""Catapult OpenField client exceptions — mirror the api_football taxonomy so
the sync service can branch on transport/auth vs. bad-data vs. upstream."""
from __future__ import annotations


class CatapultError(Exception):
    """Base for every Catapult client failure."""


class CatapultAuthError(CatapultError):
    """401/403 — token missing, expired, or lacking scope."""


class CatapultBadResponse(CatapultError):
    """422 or unparseable body — the request shape or a parameter slug is wrong."""


class CatapultRateLimitError(CatapultError):
    """429 — too many requests."""


class CatapultUpstreamError(CatapultError):
    """5xx / network — Catapult-side failure, safe to retry later."""
