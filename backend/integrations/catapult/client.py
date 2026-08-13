"""HTTP client for the Catapult OpenField Cloud API (v6).

Only the endpoints the GPS sync actually calls live here. Auth is a Bearer
JWT (per-tenant, long-lived); the region is encoded in the token's issuer, so
the base URL is stored per-integration (default: US backend).

Confirmed request shapes (2026-08, against the U. de Chile test tenant):
  * GET  /activities                         → list; fields name/start_time/
                                               tag_list/periods/game_id/…
  * GET  /activities/{id}/athletes           → the session roster (name + DOB)
  * GET  /teams   /athletes   /parameters    → lists
  * POST /stats   {parameters:[<slug>,…],    → per-athlete metric values,
                   group_by:["athlete"],       one row per athlete with the
                   filters:[{name,comparison,  requested slug fields.
                            values}]}
    NB: `parameters` are plain slug STRINGS — an object or a slug containing a
    "." is rejected 422.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .exceptions import (
    CatapultAuthError,
    CatapultBadResponse,
    CatapultRateLimitError,
    CatapultUpstreamError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://backend-us.openfield.catapultsports.com/api/v6"
DEFAULT_TIMEOUT = 60.0  # /stats can be slow; keep generous.


class CatapultClient:
    """Thin, typed wrapper around the Catapult OpenField v6 REST API."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if not token:
            raise CatapultAuthError("Catapult API token is empty.")
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    # ── transport ─────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kw) -> Any:
        url = f"{self._base}/{path.lstrip('/')}"
        try:
            resp = self._client.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise CatapultUpstreamError(f"{method} {path}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise CatapultAuthError(f"{method} {path}: {resp.status_code} {resp.text[:200]}")
        if resp.status_code == 429:
            raise CatapultRateLimitError(f"{method} {path}: 429")
        if resp.status_code == 422:
            raise CatapultBadResponse(f"{method} {path}: 422 {resp.text[:300]}")
        if resp.status_code >= 500:
            raise CatapultUpstreamError(f"{method} {path}: {resp.status_code}")
        if resp.status_code >= 400:
            raise CatapultBadResponse(f"{method} {path}: {resp.status_code} {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise CatapultBadResponse(f"{method} {path}: non-JSON body") from exc

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_body: dict) -> Any:
        return self._request("POST", path, json=json_body)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CatapultClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── endpoints ─────────────────────────────────────────────────────────

    def teams(self) -> list[dict]:
        return self._get("/teams") or []

    def athletes(self) -> list[dict]:
        """All athletes in the tenant (carries current_team_id, DOB, is_deleted/demo)."""
        return self._get("/athletes") or []

    def parameters(self) -> list[dict]:
        """Metric catalogue (slug, name, unit_type) — for mapping to gps fields."""
        return self._get("/parameters") or []

    def activities(self) -> list[dict]:
        """All activities (sessions). Filter by team/date on the caller side —
        the endpoint returns the full list and is cheap relative to /stats."""
        return self._get("/activities") or []

    def activity_athletes(self, activity_id: str) -> list[dict]:
        """The roster for one activity — first_name/last_name/date_of_birth_date
        for player matching."""
        return self._get(f"/activities/{activity_id}/athletes") or []

    def stats(
        self,
        activity_id: str,
        parameter_slugs: list[str],
        group_by: str = "athlete",
    ) -> list[dict]:
        """Per-athlete metric values for one activity. Returns one row per
        athlete carrying `athlete_id`, `athlete_name`, and each requested slug
        as a key. `parameter_slugs` must be plain slug strings."""
        if not parameter_slugs:
            return []
        body = {
            "parameters": list(parameter_slugs),
            "group_by": [group_by],
            "filters": [
                {"name": "activity_id", "comparison": "=", "values": [activity_id]}
            ],
        }
        return self._post("/stats", body) or []
