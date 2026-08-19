"""HTTP client for the COMET LIVE REST API (Analyticom, FIFA/confederation
match-management platform — ANFP tenant for Chile).

Only the endpoints the played-match sync calls live here. Verified live against
the ANFP tenant, 2026-08 (team 40017 = Universidad de Chile):

  * GET /api/live/{tenant}/team/{teamId}/matches/paginated/past/{utcOffset}
        → {result: [match…], size: N}. Paginated; `size` is the TOTAL.
          ONE team id returns matches for EVERY category the club enters
          (Primera División through Sub 11) — the category lives in the
          match's competition, not in the team id.
  * GET /api/live/{tenant}/match/{matchId}            → score, round, facility
  * GET /api/live/{tenant}/match/{matchId}/lineups    → {home,away}:
          {players: [{personId, fifaId, shirtNumber, starting, captain,
                      position}…], officials: [...]}
  * GET /api/live/{tenant}/match/{matchId}/events     → typed timeline

Auth + scoping, all four values on EVERY request (the two filters are
documented as "required if API_KEY is restricted by organization/team", and the
ANFP key is):
  * `API_KEY` header
  * `tenant` path segment
  * `organizationIdFilter` + `teamIdFilter` query params

Two field-level traps, both confirmed against real data:
  * `minuteFull` is the MATCH minute; `minute` is the minute within the phase
    (a 64' substitution reads minute=19, minuteFull=64 in the 2nd half). Always
    read `minuteFull` — `minute` silently produces nonsense minutes-played.
  * On a Substitution event, `player` is the one coming ON and `player2` the one
    going OFF (cross-checked against the lineup's `starting` flags).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .exceptions import (
    CometAuthError,
    CometBadResponse,
    CometRateLimitError,
    CometUpstreamError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api-latam.analyticom.de"
DEFAULT_TENANT = "ANFP"
DEFAULT_TIMEOUT = 45.0
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 200  # runaway-loop backstop


class CometClient:
    """Thin wrapper around the COMET LIVE endpoints the sync needs."""

    def __init__(
        self,
        api_key: str,
        *,
        tenant: str = DEFAULT_TENANT,
        team_id: int | str,
        organization_id: int | str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if not api_key:
            raise CometAuthError("COMET API_KEY is empty.")
        if not tenant:
            raise CometAuthError("COMET tenant is empty (e.g. 'ANFP').")
        if not team_id:
            raise CometAuthError("COMET team id is empty.")
        self._base = base_url.rstrip("/")
        self.tenant = tenant
        self.team_id = str(team_id)
        # Sent on every call; blank organization would 401 a restricted key.
        self._filters = {
            "organizationIdFilter": str(organization_id or ""),
            "teamIdFilter": str(team_id),
        }
        self._client = httpx.Client(
            timeout=timeout,
            headers={"API_KEY": api_key, "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── transport ─────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}/api/live/{self.tenant}{path}"
        merged = {**self._filters, **(params or {})}
        try:
            resp = self._client.get(url, params=merged)
        except httpx.HTTPError as exc:
            raise CometUpstreamError(f"Transport error calling COMET {path}: {exc}") from exc

        if resp.status_code in (401, 403):
            raise CometAuthError(
                f"COMET rejected the request ({resp.status_code}) on {path}. Check the "
                "API_KEY, the tenant, and that organizationIdFilter / teamIdFilter "
                "match the key's scope."
            )
        if resp.status_code == 429:
            raise CometRateLimitError(f"COMET rate limit (429) on {path}.")
        if resp.status_code >= 500:
            raise CometUpstreamError(f"COMET {resp.status_code} on {path}: {resp.text[:200]}")
        if resp.status_code != 200:
            raise CometUpstreamError(
                f"Unexpected COMET status {resp.status_code} on {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise CometBadResponse(f"Non-JSON response from COMET {path}: {exc}") from exc

    # ── public ────────────────────────────────────────────────────────────

    def team(self) -> dict[str, Any]:
        """Team details — used to confirm the configured id is the right club."""
        data = self._get(f"/team/{self.team_id}")
        if not isinstance(data, dict):
            raise CometBadResponse("Expected an object from /team.")
        return data

    def past_matches(
        self, *, utc_offset: int = -4, page_size: int = DEFAULT_PAGE_SIZE,
        max_matches: int | None = None,
    ) -> list[dict[str, Any]]:
        """Played + today's matches for the configured team, newest first.

        Walks the pagination until `size` is exhausted (or `max_matches`). The
        endpoint spans every category, so callers must resolve each match's
        competition to a SLAB category themselves.
        """
        return self._paginate(
            f"/team/{self.team_id}/matches/paginated/past/{utc_offset}",
            page_size=page_size, max_items=max_matches,
        )

    def iter_past_matches(
        self, *, utc_offset: int = -4, page_size: int = DEFAULT_PAGE_SIZE,
    ):
        """Lazy page-by-page version of `past_matches`, newest first.

        Lets a caller with a date window stop as soon as it reads past the
        cutoff instead of paging the club's entire history — this team has 2 800+
        played matches, so a 30-day sync would otherwise pull ~29 pages to use
        one.
        """
        path = f"/team/{self.team_id}/matches/paginated/past/{utc_offset}"
        seen = 0
        for page in range(1, MAX_PAGES + 1):
            data = self._get(path, {"page": page, "pageSize": page_size})
            if not isinstance(data, dict):
                raise CometBadResponse(f"Expected an object from {path}.")
            batch = data.get("result") or []
            if not batch:
                return
            yield from batch
            seen += len(batch)
            total = data.get("size")
            if isinstance(total, int) and seen >= total:
                return
        logger.warning("COMET pagination hit MAX_PAGES on %s; stopping.", path)

    def future_matches(
        self, *, utc_offset: int = -4, page_size: int = DEFAULT_PAGE_SIZE,
        max_matches: int | None = None,
    ) -> list[dict[str, Any]]:
        """Scheduled matches. Not used by the played-match sync — kept so the
        fixture/calendar slice can reuse the same client."""
        return self._paginate(
            f"/team/{self.team_id}/matches/paginated/future/{utc_offset}",
            page_size=page_size, max_items=max_matches,
        )

    def _paginate(
        self, path: str, *, page_size: int, max_items: int | None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._get(path, {"page": page, "pageSize": page_size})
            if not isinstance(data, dict):
                raise CometBadResponse(f"Expected an object from {path}.")
            batch = data.get("result") or []
            out.extend(batch)
            total = data.get("size")
            if not batch:
                break
            if max_items is not None and len(out) >= max_items:
                return out[:max_items]
            if isinstance(total, int) and len(out) >= total:
                break
        else:
            logger.warning("COMET pagination hit MAX_PAGES on %s; stopping.", path)
        return out

    def match(self, match_id: int | str) -> dict[str, Any]:
        """Match record. Unlike the list payload this includes `facility`."""
        return self._get(f"/match/{match_id}")

    def match_officials(self, match_id: int | str) -> list[dict[str, Any]]:
        """The REFEREES (`/match/{id}/info` → matchOfficials).

        Not to be confused with `lineups[side]["officials"]`, which is the
        team's own coaching staff (head coach, doctor, physio) — a different
        thing entirely, and the reason a naive read leaves `referee` null.
        """
        data = self._get(f"/match/{match_id}/info")
        if not isinstance(data, dict):
            raise CometBadResponse("Expected an object from /match/{id}/info.")
        return data.get("matchOfficials") or []

    def match_lineups(self, match_id: int | str) -> dict[str, Any]:
        """{"home": {...}, "away": {...}} — each with `players` and `officials`."""
        data = self._get(f"/match/{match_id}/lineups")
        if not isinstance(data, dict):
            raise CometBadResponse("Expected an object from /lineups.")
        return data

    def match_events(self, match_id: int | str) -> list[dict[str, Any]]:
        data = self._get(f"/match/{match_id}/events")
        if not isinstance(data, list):
            raise CometBadResponse("Expected a list from /events.")
        return data

    def match_standings(self, match_id: int | str) -> list[dict[str, Any]]:
        """Official competition table around this match (one row per team)."""
        data = self._get(f"/match/{match_id}/standings")
        return data if isinstance(data, list) else []

    def match_head_to_head(
        self, match_id: int | str, *, utc_offset: int = -4, page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """Recent meetings between the two teams of this match."""
        data = self._get(
            f"/match/{match_id}/h2h/{utc_offset}",
            {"page": 1, "pageSize": page_size},
        )
        if isinstance(data, dict):
            return data.get("result") or []
        return data if isinstance(data, list) else []
