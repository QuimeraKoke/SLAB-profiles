"""COMET LIVE client exceptions — mirrors the catapult / api_football taxonomy
so the sync service can branch on transport/auth vs. bad-data vs. upstream."""
from __future__ import annotations


class CometError(Exception):
    """Base for every COMET client failure."""


class CometAuthError(CometError):
    """401/403 — API_KEY missing, wrong, or not scoped to this tenant.

    Also raised when the key is scoped to an organization/team and the request
    omitted `organizationIdFilter` / `teamIdFilter`; COMET documents both as
    "required if API_KEY is restricted by", so the client always sends them.
    """


class CometBadResponse(CometError):
    """Unparseable body, or a payload that isn't the documented shape."""


class CometRateLimitError(CometError):
    """429 — too many requests."""


class CometUpstreamError(CometError):
    """5xx / network — COMET-side failure, safe to retry later."""
