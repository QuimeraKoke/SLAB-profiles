"""HTTP client for the VALD Hub external APIs (ForceDecks / ForceFrame /
NordBord / Profiles / Tenants).

Auth is OAuth2 client-credentials: POST client_id+client_secret+audience to the
token endpoint, cache the bearer token until it expires, send it on every call.
Each VALD product lives on its own regional host
(`https://prd-{region}-api-{segment}.valdperformance.com`).

Incremental sync everywhere: pass `TenantId` + `ModifiedFromUtc`, advance the
cursor to the max `modifiedDateUtc` returned, and loop until HTTP 204 (= no more
data — NOT an error). Verified against VALD's live Swagger specs (2026-07-16).

Mirrors `integrations/api_football/client.py` in structure (transport + auth +
error classification here; per-product mapping lives in the sync service).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from django.conf import settings

from .dtos import ValdProfile
from .exceptions import (
    ValdAuthError,
    ValdBadResponse,
    ValdRateLimitError,
    ValdUpstreamError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
_MIN_INTERVAL_S = 0.25  # be polite; VALD's exact limit is undocumented
_RETRY_ON_429 = 2
_RETRY_SLEEP_S = 10.0
_TOKEN_SKEW_S = 60  # refresh this many seconds before real expiry
_MAX_PAGES = 1000  # runaway-loop backstop for the ModifiedFromUtc pagination
# Far-past start for a "full" pull (VALD data doesn't predate this).
_EPOCH_START = "2015-01-01T00:00:00Z"

# VALD host segment per product (note the irregular naming: `ext` vs
# `external`, singular `profile`). Confirmed from the live specs.
_SEGMENTS = {
    "tenants": "externaltenants",
    "profiles": "externalprofile",
    "forcedecks": "extforcedecks",
    "forceframe": "externalforceframe",
    "nordbord": "externalnordbord",
}


class ValdHubClient:
    """Thin, typed wrapper around the VALD Hub external REST APIs for one tenant."""

    def __init__(
        self,
        *,
        region: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        token_url: str | None = None,
        audience: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not (client_id and client_secret):
            raise ValdAuthError(
                "VALD client_id / client_secret are empty. Set env VALD_CLIENT_ID / "
                "VALD_CLIENT_SECRET (or per-club overrides) to enable VALD calls."
            )
        if not tenant_id:
            raise ValdAuthError("VALD tenant_id is required.")
        self.region = (region or "use").strip().lower()
        self.tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url or getattr(
            settings, "VALD_TOKEN_URL", "https://auth.prd.vald.com/oauth/token",
        )
        self._audience = audience or getattr(
            settings, "VALD_AUDIENCE", "vald-api-external",
        )
        self._timeout = timeout
        self._token: str | None = None
        self._token_expiry = 0.0  # time.monotonic() deadline
        self._last_request_at = 0.0
        self._result_definitions: dict[int, dict[str, Any]] | None = None

    # -- Public: profiles ----------------------------------------------------

    def list_profiles(self, modified_from: str | None = None) -> list[ValdProfile]:
        items = self._paginate_by_modified(
            "profiles", "/profiles", list_key="profiles",
            id_key="profileId", modified_from=modified_from,
        )
        out: list[ValdProfile] = []
        for it in items:
            try:
                out.append(ValdProfile.from_api(it))
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("Skipping malformed VALD profile: %s | %r", exc, it)
        return out

    # -- Public: per-product tests -------------------------------------------

    def list_forcedecks_tests(self, modified_from: str | None = None) -> list[dict[str, Any]]:
        return self._paginate_by_modified(
            "forcedecks", "/tests", list_key="tests",
            id_key="testId", modified_from=modified_from,
        )

    def list_forceframe_tests(self, modified_from: str | None = None) -> list[dict[str, Any]]:
        return self._paginate_by_modified(
            "forceframe", "/tests/v2", list_key="tests",
            id_key="testId", modified_from=modified_from,
        )

    def list_nordbord_tests(self, modified_from: str | None = None) -> list[dict[str, Any]]:
        return self._paginate_by_modified(
            "nordbord", "/tests/v2", list_key="tests",
            id_key="testId", modified_from=modified_from,
        )

    def get_forcedecks_result_definitions(self) -> dict[int, dict[str, Any]]:
        """`resultId -> {name, scale, unit}` map, cached per client instance.

        ForceDecks metrics arrive as `resultId`+`value` pairs; this catalog
        turns them into named, display-unit metrics (`value * scale`)."""
        if self._result_definitions is not None:
            return self._result_definitions
        data = self._get("forcedecks", "/resultdefinitions", params={})
        defs = data if isinstance(data, list) else (data or {}).get("resultDefinitions") or []
        out: dict[int, dict[str, Any]] = {}
        for d in defs:
            try:
                rid = int(d["resultId"])
            except (KeyError, TypeError, ValueError):
                continue
            out[rid] = {
                "name": d.get("resultName") or d.get("resultIdString") or "",
                "scale": float(d.get("resultUnitScaleFactor") or 1.0),
                "unit": d.get("resultUnitName") or d.get("resultUnit") or "",
            }
        self._result_definitions = out
        return out

    def forcedecks_test_trials_metrics(self, test_id: str) -> list[dict[str, float]]:
        """Resolved test-level metrics per trial for one ForceDecks test.

        The modern `/tests` list carries no metric values — they live on the
        legacy per-test trials endpoint. Returns one `{resultName: value×scale}`
        dict per trial (using only `limb == "Trial"` overall results). Usually a
        single trial; multiple means repeated jumps in one recording."""
        defs = self.get_forcedecks_result_definitions()
        trials = self._get(
            "forcedecks",
            f"/v2019q3/teams/{self.tenant_id}/tests/{test_id}/trials",
            params={},
        )
        out: list[dict[str, float]] = []
        for tr in (trials or []):
            metrics: dict[str, float] = {}
            for r in (tr.get("results") or []):
                if r.get("limb") != "Trial":
                    continue
                rid, val = r.get("resultId"), r.get("value")
                if rid is None or val is None:
                    continue
                try:
                    defn = defs.get(int(rid))
                except (TypeError, ValueError):
                    defn = None
                if not defn:
                    continue
                metrics[defn["name"]] = float(val) * defn["scale"]
            if metrics:
                out.append(metrics)
        return out

    def list_tenants(self) -> list[dict[str, Any]]:
        """Tenants the credentials can access — handy to confirm region/tenant_id."""
        data = self._get("tenants", "/tenants", params={})
        if isinstance(data, list):
            return data
        return (data or {}).get("tenants") or []

    # -- Internals: auth -----------------------------------------------------

    def _get_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expiry:
            return self._token
        try:
            resp = httpx.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "audience": self._audience,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ValdUpstreamError(f"Transport error requesting VALD token: {exc}") from exc
        if resp.status_code != 200:
            raise ValdAuthError(
                f"VALD token request failed ({resp.status_code}): {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ValdAuthError(f"Non-JSON token response from VALD: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise ValdAuthError(f"VALD token response missing access_token: {payload}")
        expires_in = int(payload.get("expires_in") or 3600)
        self._token = token
        self._token_expiry = time.monotonic() + max(0, expires_in - _TOKEN_SKEW_S)
        return token

    # -- Internals: transport ------------------------------------------------

    def _base(self, segment: str) -> str:
        seg = _SEGMENTS[segment]
        return f"https://prd-{self.region}-api-{seg}.valdperformance.com"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()

    def _get(
        self, segment: str, path: str, params: dict[str, Any], *, allow_204: bool = False,
    ) -> Any:
        """GET a VALD endpoint. Returns parsed JSON, or None on 204 when
        `allow_204` (end-of-data sentinel for the pagination loop)."""
        url = f"{self._base(segment)}{path}"
        for attempt in range(_RETRY_ON_429 + 1):
            self._throttle()
            headers = {
                "Authorization": f"Bearer {self._get_token()}",
                "Accept": "application/json",
            }
            try:
                resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
            except httpx.HTTPError as exc:
                raise ValdUpstreamError(f"Transport error calling VALD {path}: {exc}") from exc
            if resp.status_code == 429 and attempt < _RETRY_ON_429:
                logger.info("VALD 429 on %s; backing off %ss (attempt %d).",
                            path, _RETRY_SLEEP_S, attempt + 1)
                time.sleep(_RETRY_SLEEP_S)
                continue
            break

        if allow_204 and resp.status_code == 204:
            return None
        if resp.status_code in (401, 403):
            raise ValdAuthError(
                f"VALD rejected the request ({resp.status_code}) on {path}. Check "
                "client credentials, tenant_id, and that the region host matches "
                "the tenant's data region."
            )
        if resp.status_code == 429:
            raise ValdRateLimitError(f"VALD rate limit (429) after retries on {path}.")
        if resp.status_code >= 500:
            raise ValdUpstreamError(f"VALD {resp.status_code} on {path}: {resp.text[:200]}")
        if resp.status_code != 200:
            raise ValdUpstreamError(
                f"Unexpected VALD status {resp.status_code} on {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ValdBadResponse(f"Non-JSON response from VALD {path}: {exc}") from exc

    def _paginate_by_modified(
        self, segment: str, path: str, *, list_key: str, id_key: str,
        modified_from: str | None,
    ) -> list[dict[str, Any]]:
        """Loop the incremental endpoint, advancing `ModifiedFromUtc` to the max
        `modifiedDateUtc` seen, deduping by `id_key`, until 204 / no new rows."""
        cursor = modified_from or _EPOCH_START
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for _ in range(_MAX_PAGES):
            data = self._get(
                segment, path,
                params={"TenantId": self.tenant_id, "ModifiedFromUtc": cursor},
                allow_204=True,
            )
            if data is None:  # 204 → end of data
                break
            items = (data or {}).get(list_key) or []
            new = [it for it in items if str(it.get(id_key)) not in seen]
            if not new:
                break
            for it in new:
                seen.add(str(it.get(id_key)))
                out.append(it)
            max_mod = max(
                (it.get("modifiedDateUtc") for it in items if it.get("modifiedDateUtc")),
                default=None,
            )
            if not max_mod or max_mod == cursor:
                break
            cursor = max_mod
        else:
            logger.warning("VALD pagination hit _MAX_PAGES on %s; stopping.", path)
        return out
