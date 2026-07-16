"""Exception hierarchy for the VALD Hub integration.

Callers catch `ValdError` for "any integration failure", or the specific
subclasses when they want to react differently (e.g. bad creds vs. rate limit).
Mirrors `integrations/api_football/exceptions.py`.
"""
from __future__ import annotations


class ValdError(Exception):
    """Base for every VALD Hub integration failure."""


class ValdAuthError(ValdError):
    """OAuth token request failed, or the API returned 401/403 — bad
    client credentials, or the token/tenant is wrong for the region host."""


class ValdRateLimitError(ValdError):
    """429 — VALD throttled the request after retries."""


class ValdUpstreamError(ValdError):
    """5xx, transport error, or an unparseable response from VALD."""


class ValdBadResponse(ValdError):
    """200 OK but the response body isn't the shape we expect."""
