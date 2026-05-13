"""API-Football v3 integration.

Public surface:
- `ApiFootballClient` — typed wrapper around the REST API.
- `Fixture` (and friends) — parsed response DTOs.
- Exception hierarchy rooted at `ApiFootballError`.

Docs: https://www.api-football.com/documentation-v3
"""
from .client import ApiFootballClient
from .dtos import Fixture, FixtureScore, FixtureTeam
from .exceptions import (
    ApiFootballAuthError,
    ApiFootballBadResponse,
    ApiFootballError,
    ApiFootballRateLimitError,
    ApiFootballUpstreamError,
)

__all__ = [
    "ApiFootballClient",
    "Fixture",
    "FixtureScore",
    "FixtureTeam",
    "ApiFootballError",
    "ApiFootballAuthError",
    "ApiFootballRateLimitError",
    "ApiFootballUpstreamError",
    "ApiFootballBadResponse",
]
