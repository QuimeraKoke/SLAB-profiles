"""HTTP client for API-Football v3.

Only the endpoints SLAB actually calls live here; adding more is a
matter of writing one method per endpoint. Keep response parsing in
`dtos.py` so this file stays focused on transport + auth + error
classification.

Auth uses the native `x-apisports-key` header. If you ever migrate to
the RapidAPI gateway, switch the header name to `x-rapidapi-key`; the
response envelope (`get / parameters / errors / results / paging /
response`) is identical.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import httpx
from django.conf import settings

from .dtos import Fixture
from .exceptions import (
    ApiFootballAuthError,
    ApiFootballBadResponse,
    ApiFootballRateLimitError,
    ApiFootballUpstreamError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
# The free tier enforces a tight PER-MINUTE limit (separate from the daily
# cap). Pace requests + back off on 429 so a multi-call sync doesn't trip it.
_MIN_INTERVAL_S = 1.2
_RETRY_ON_429 = 2
_RETRY_SLEEP_S = 20.0


class ApiFootballClient:
    """Thin, typed wrapper around the API-Football v3 REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key if api_key is not None else getattr(
            settings, "API_FOOTBALL_KEY", "",
        )
        if not self._api_key:
            # Fail fast at construction — easier to debug than getting a
            # 401 buried inside a Celery worker log.
            raise ApiFootballAuthError(
                "API_FOOTBALL_KEY is empty. Set the env var (or pass "
                "`api_key=`) to enable API-Football calls."
            )
        self._base_url = (base_url or getattr(
            settings, "API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io",
        )).rstrip("/")
        self._timeout = timeout
        self._last_request_at = 0.0

    # -- Public endpoints ----------------------------------------------------

    def list_fixtures(
        self,
        team_id: int,
        season: int,
        league_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Fixture]:
        """Return every fixture for the team in the given season.

        When `league_id` is omitted (default), API-Football returns
        fixtures across *every competition* the team played that season
        — domestic league, cups, continental, friendlies. Each fixture
        carries its own league metadata so the caller can partition
        downstream. Pass `league_id` only when you want to restrict to
        a single competition.

        `date_from` / `date_to` (inclusive, UTC) optionally narrow the
        window. API-Football accepts either or both.
        """
        params: dict[str, str | int] = {
            "team": team_id,
            "season": season,
        }
        if league_id is not None:
            params["league"] = league_id
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        payload = self._get("/fixtures", params=params)
        items = payload.get("response") or []
        fixtures: list[Fixture] = []
        for it in items:
            try:
                fixtures.append(Fixture.from_api(it))
            except (ValueError, KeyError, TypeError) as exc:
                # One malformed item shouldn't kill the whole sync. Log
                # with enough context to file an issue against upstream.
                logger.warning(
                    "Skipping malformed API-Football fixture: %s | item=%r",
                    exc, it,
                )
        return fixtures

    def list_team_leagues(self, team_id: int, season: int) -> list[dict[str, Any]]:
        """Competitions the team played in the season (league + cups +
        continental). Returns the raw `response[]` items — each carries
        `league`, `country`, and `seasons[].coverage` (which stats are
        available for that competition/season)."""
        payload = self._get("/leagues", params={"team": team_id, "season": season})
        return payload.get("response") or []

    def get_fixture_lineups(self, fixture_id: int) -> list[dict[str, Any]]:
        """Per-team lineups + formation + starting XI / substitutes for a
        fixture. Empty until the lineup is published (~40 min pre-match)."""
        return self._get("/fixtures/lineups", params={"fixture": fixture_id}).get("response") or []

    def get_fixture_events(self, fixture_id: int) -> list[dict[str, Any]]:
        """Timeline of match events (goals, cards, subs, VAR) for a fixture."""
        return self._get("/fixtures/events", params={"fixture": fixture_id}).get("response") or []

    def get_fixture_statistics(self, fixture_id: int) -> list[dict[str, Any]]:
        """Per-team match statistics (possession, shots, passes, corners…)."""
        return self._get("/fixtures/statistics", params={"fixture": fixture_id}).get("response") or []

    def get_fixture_players(self, fixture_id: int) -> list[dict[str, Any]]:
        """Per-player match statistics (rating, minutes, passes, tackles,
        shots…), grouped by team. The closest API-Football gets to
        'tactical/technical' player data — it does NOT include physical /
        GPS metrics (distance, sprints), which no public API provides."""
        return self._get("/fixtures/players", params={"fixture": fixture_id}).get("response") or []

    # -- Internals -----------------------------------------------------------

    def _throttle(self) -> None:
        """Space requests by at least `_MIN_INTERVAL_S` to respect the free
        tier's per-minute limit."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"x-apisports-key": self._api_key}

        for attempt in range(_RETRY_ON_429 + 1):
            self._throttle()
            try:
                resp = httpx.get(
                    url, params=params, headers=headers, timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                raise ApiFootballUpstreamError(
                    f"Transport error calling API-Football: {exc}"
                ) from exc
            # 429 = per-minute (or daily) limit. Back off + retry a couple
            # of times; the per-minute window clears quickly.
            if resp.status_code == 429 and attempt < _RETRY_ON_429:
                logger.info("API-Football 429; backing off %ss (attempt %d).",
                            _RETRY_SLEEP_S, attempt + 1)
                time.sleep(_RETRY_SLEEP_S)
                continue
            break

        if resp.status_code in (401, 403):
            raise ApiFootballAuthError(
                f"API-Football rejected the request ({resp.status_code}). "
                "Check API_FOOTBALL_KEY and your plan's endpoint coverage."
            )
        if resp.status_code == 429:
            raise ApiFootballRateLimitError(
                "API-Football rate limit exceeded (429) after retries. "
                "Daily quota likely reached; resume later or upgrade plan."
            )
        if resp.status_code >= 500:
            raise ApiFootballUpstreamError(
                f"API-Football {resp.status_code}: {resp.text[:200]}"
            )
        if resp.status_code != 200:
            raise ApiFootballUpstreamError(
                f"Unexpected status {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise ApiFootballUpstreamError(
                f"Non-JSON response from API-Football: {exc}"
            ) from exc

        # API-Football returns HTTP 200 even when there's a logical error.
        # `errors` can be an empty list (success) OR a dict mapping field
        # → message (e.g. {"token": "Error/Missing application key."}) OR
        # — rarely — a non-empty list. Treat any non-empty shape as a
        # failure and surface the body verbatim.
        errors = data.get("errors")
        if errors:
            has_payload = (
                (isinstance(errors, dict) and len(errors) > 0)
                or (isinstance(errors, list) and len(errors) > 0)
            )
            if has_payload:
                raise ApiFootballBadResponse(
                    f"API-Football reported errors: {errors}"
                )
        return data
