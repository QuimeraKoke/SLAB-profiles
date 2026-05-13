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

    # -- Internals -----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"x-apisports-key": self._api_key}
        try:
            resp = httpx.get(
                url, params=params, headers=headers, timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ApiFootballUpstreamError(
                f"Transport error calling API-Football: {exc}"
            ) from exc

        if resp.status_code in (401, 403):
            raise ApiFootballAuthError(
                f"API-Football rejected the request ({resp.status_code}). "
                "Check API_FOOTBALL_KEY and your plan's endpoint coverage."
            )
        if resp.status_code == 429:
            raise ApiFootballRateLimitError(
                "API-Football rate limit exceeded (429). Slow down or "
                "upgrade plan."
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
