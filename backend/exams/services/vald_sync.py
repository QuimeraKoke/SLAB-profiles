"""VALD Hub → ExamResult sync.

Pulls tests from a club's VALD tenant and writes them into the existing strength
templates as `ExamResult` rows — the same rows the manual xlsx importers
(`import_cmj/imtp/hip_adab/nordico`) produce, so dashboards/alerts need no changes.

Flow (`sync_club`):
  1. Pull profiles → upsert `ValdProfileLink`, auto-resolve to a SLAB Player
     (externalId → name+DOB → name; manual links are never overwritten).
  2. Per product (ForceDecks/ForceFrame/NordBord): pull tests since the stored
     cursor, resolve profileId→player, map metrics to the template's field_keys,
     dedup on (template family, player, day), and `ExamResult.objects.create(...)`
     (NOT bulk — fires the imbalance band-alert + player-state signals).
  3. Advance per-product cursors to the max `modifiedDateUtc` seen.

Reuses: `exams.calculations.compute_result_data` (calculated fields + snapshot),
the importers' `_norm` name matching, and the importers' dedup rule.
"""
from __future__ import annotations

import logging
import unicodedata
import uuid as uuid_lib
from datetime import datetime, timezone as dt_tz

from django.conf import settings
from django.utils import timezone

from core.models import Player
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate, ValdIntegration, ValdProfileLink
from integrations.vald_hub import ValdHubClient

logger = logging.getLogger(__name__)

# --- Test-type → template + field-key mappings -----------------------------

# ForceDecks metric NAMES (from /resultdefinitions) → template field_key, per
# testType. Names mirror the xlsx column headers the manual importer keyed on
# (minus the unit suffix). Matched via `_norm_metric` (alnum-only, lowercased)
# so spacing/punctuation drift doesn't break the mapping.
FORCEDECKS_METRIC_MAP = {
    "CMJ": {
        "Jump Height (Imp-Mom)": "jump_height",
        "Peak Power / BM": "peak_power_bodymass",
        "RSI-modified": "rsi_modified",
        "Eccentric Peak Velocity": "ecc_peak_velocity",
    },
    "IMTP": {
        "Peak Vertical Force": "peak_vertical_force",
        "Peak Vertical Force / BM": "peak_force_bodymass",
        "RFD - 200ms": "rfd_200ms",
    },
}
FORCEDECKS_TEMPLATE = {"CMJ": "cmj", "IMTP": "imtp"}

# ForceFrame: inner sensors = adduction (squeeze), outer = abduction (pull).
FORCEFRAME_FIELD_MAP = {
    "innerLeftMaxForce": "squeeze_left_max",
    "innerRightMaxForce": "squeeze_right_max",
    "outerLeftMaxForce": "pull_left_max",
    "outerRightMaxForce": "pull_right_max",
}
# Substring keywords (lowercased) that identify a Hip AD/AB test on ForceFrame.
# testTypeName/testPositionName are tenant-configured, so keep this permissive
# and tighten after the first live dry-run if the tenant runs other hip tests.
FORCEFRAME_HIP_KEYWORDS = ("hip", "ad/ab", "adduction", "abduction", "add/abd")

NORDBORD_KEYWORDS = ("nordic", "nórdico", "nordico")


def _norm_metric(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


_FD_MAP_NORM = {
    tt: {_norm_metric(k): v for k, v in m.items()}
    for tt, m in FORCEDECKS_METRIC_MAP.items()
}


def _norm_name(s: str) -> list[str]:
    """NFD strip-accents, uppercase, tokenize — same rule as the xlsx importers."""
    s = unicodedata.normalize("NFD", (s or "").upper())
    return "".join(c for c in s if not unicodedata.combining(c)).split()


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_dt(raw) -> datetime | None:
    """Parse a VALD UTC timestamp into an aware datetime (assume UTC if naive)."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_tz.utc)
    return dt


def _template(club, slug: str) -> ExamTemplate | None:
    return ExamTemplate.objects.filter(
        slug=slug, is_active_version=True, department__club=club,
    ).first()


def _max_iso(a: str | None, b: str | None) -> str | None:
    vals = [v for v in (a, b) if v]
    return max(vals) if vals else None


# --- Player matching --------------------------------------------------------

def _resolve_player(prof, active_roster, club):
    """Return (player, match_method) for a VALD profile, or (None, 'unresolved')."""
    # 1. externalId is an authoritative SLAB player UUID.
    ext = (prof.external_id or "").strip()
    if ext:
        try:
            pid = uuid_lib.UUID(ext)
        except (ValueError, AttributeError):
            pid = None
        if pid is not None:
            match = Player.objects.filter(category__club=club, id=pid).first()
            if match is not None:
                return match, ValdProfileLink.MATCH_EXTERNAL_ID

    # 2. Normalized name (every player-name token present in the VALD name).
    prof_tokens = set(_norm_name(prof.full_name))
    cands = [
        p for p in active_roster
        if set(_norm_name(f"{p.first_name} {p.last_name}")) <= prof_tokens
        and set(_norm_name(f"{p.first_name} {p.last_name}"))
    ]
    dob = prof.date_of_birth  # ISO string or None
    if len(cands) == 1:
        p = cands[0]
        if dob and p.date_of_birth and p.date_of_birth.isoformat() == dob:
            return p, ValdProfileLink.MATCH_NAME_DOB
        return p, ValdProfileLink.MATCH_NAME
    if len(cands) > 1 and dob:
        dob_matches = [p for p in cands if p.date_of_birth and p.date_of_birth.isoformat() == dob]
        if len(dob_matches) == 1:
            return dob_matches[0], ValdProfileLink.MATCH_NAME_DOB
    return None, ValdProfileLink.MATCH_UNRESOLVED


def _sync_profiles(club, profiles, *, dry_run, report) -> dict:
    """Upsert profile links + auto-resolve. Returns the in-memory
    {profile_id: Player} for profiles resolved this run (used so a dry-run —
    which persists nothing — can still preview test ingestion)."""
    roster = list(
        Player.objects.filter(category__club=club, is_active=True)
        .select_related("category")
    )
    resolved: dict[str, Player] = {}
    now = timezone.now()
    for prof in profiles:
        link = ValdProfileLink.objects.filter(
            club=club, vald_profile_id=prof.profile_id,
        ).first()
        created = link is None
        if link is None:
            link = ValdProfileLink(club=club, vald_profile_id=prof.profile_id)
        link.given_name = prof.given_name
        link.family_name = prof.family_name
        link.date_of_birth = _parse_dt(prof.date_of_birth).date() if prof.date_of_birth else None
        link.external_id = prof.external_id
        link.sync_id = prof.sync_id
        link.last_seen_at = now
        # Never overwrite a hand-fixed link.
        if link.match_method != ValdProfileLink.MATCH_MANUAL:
            player, method = _resolve_player(prof, roster, club)
            link.player = player
            link.match_method = method
        if not dry_run:
            link.save()
        if link.player_id:
            resolved[prof.profile_id] = link.player
        report["profiles_seen"] += 1
        if created:
            report["profiles_new"] += 1
        if link.player_id is None and link.match_method != ValdProfileLink.MATCH_MANUAL:
            report["profiles_unresolved"] += 1
    return resolved


# --- Result creation --------------------------------------------------------

def _create_result(template, player, recorded_at, raw, *, dry_run, report):
    if not raw or recorded_at is None:
        report["no_metrics"] += 1
        return
    day = recorded_at.date()
    exists = ExamResult.objects.filter(
        template__family_id=template.family_id, player=player, recorded_at__date=day,
    ).exists()
    if exists:
        report["skipped"] += 1
        return
    data, snapshot = compute_result_data(template, raw, player=player)
    if not dry_run:
        # .create() (not bulk_create) so post_save signals fire: player-state
        # writeback + imbalance band-alert evaluation (nordico/hip_adab).
        ExamResult.objects.create(
            player=player, template=template, recorded_at=recorded_at,
            result_data=data, inputs_snapshot=snapshot,
        )
    report["created"] += 1


# --- Per-product ingestion --------------------------------------------------

# Primary metric per ForceDecks test type — used to pick the best TEST when a
# player has several recordings on the same day (reps *within* a test are merged
# by per-metric max first). Matches the manual xlsx importers' collapse rule.
_FD_PRIMARY = {"cmj": "jump_height", "imtp": "peak_vertical_force"}


def _fd_raw_from_metrics(metrics: dict, testtype: str) -> dict:
    """Map a trial's {resultName: value} to template field_keys for `testtype`."""
    field_map = _FD_MAP_NORM.get(testtype, {})
    raw: dict[str, float] = {}
    for name, val in metrics.items():
        fk = field_map.get(_norm_metric(name))
        num = _num(val)
        if fk and num is not None:
            raw[fk] = round(num, 3)
    return raw


def _ingest_forcedecks(client, club, links, slug_map, *, modified_from, dry_run, report):
    tpl = {
        "cmj": _template(club, slug_map["cmj"]),
        "imtp": _template(club, slug_map["imtp"]),
    }
    if not any(tpl.values()):
        return None
    tests = client.list_forcedecks_tests(modified_from=modified_from)
    max_mod = None
    # Group candidates by (player, key, day) using ONLY the modern list (which
    # carries testId/profileId/testType/recordedDate — the metric values come
    # from the per-test legacy trials endpoint, fetched lazily below).
    groups: dict[tuple, dict] = {}
    for t in tests:
        max_mod = _max_iso(max_mod, t.get("modifiedDateUtc"))
        key = FORCEDECKS_TEMPLATE.get((t.get("testType") or "").upper())
        template = tpl.get(key) if key else None
        if template is None:
            continue
        player = links.get(str(t.get("profileId")))
        if player is None:
            report["unmatched"] += 1
            continue
        rec = _parse_dt(t.get("recordedDateUtc") or t.get("recordedUTC"))
        if rec is None:
            continue
        g = groups.setdefault((player, key, rec.date()), {"template": template, "tests": []})
        g["tests"].append((t.get("testId"), rec))

    for (player, key, day), g in groups.items():
        template = g["template"]
        # Skip days already ingested (incl. from the manual xlsx importers) —
        # this also avoids fetching trials for those tests.
        if ExamResult.objects.filter(
            template__family_id=template.family_id, player=player, recorded_at__date=day,
        ).exists():
            report["skipped"] += 1
            continue
        # Reconcile like the manual importers (and VALD Hub itself):
        #   • within ONE test/recording → per-metric max across its reps
        #     (Hub's per-test value; fixes multi-rep sessions);
        #   • across SEVERAL tests the same day → keep the single best test by
        #     the primary metric (don't Frankenstein across separate efforts).
        primary = _FD_PRIMARY[key]
        candidates = []  # (primary_value_or_None, test_raw, recorded_at)
        for test_id, rec in g["tests"]:
            test_raw: dict[str, float] = {}
            try:
                trials = client.forcedecks_test_trials_metrics(test_id)
            except Exception as exc:  # noqa: BLE001 — one bad test shouldn't drop the day
                logger.warning("VALD forcedecks trials fetch failed for %s: %s", test_id, exc)
                continue
            for metrics in trials:
                for fk, v in _fd_raw_from_metrics(metrics, key.upper()).items():
                    test_raw[fk] = v if fk not in test_raw else max(test_raw[fk], v)
            if test_raw:
                candidates.append((test_raw.get(primary), test_raw, rec))
        if not candidates:
            report["no_metrics"] += 1
            continue
        best = max(candidates, key=lambda c: c[0] if c[0] is not None else float("-inf"))
        _create_result(template, player, best[2], best[1], dry_run=dry_run, report=report)
    return max_mod


def _ingest_forceframe(client, club, links, slug_map, *, modified_from, dry_run, report):
    template = _template(club, slug_map["hip_adab"])
    if template is None:
        return None
    tests = client.list_forceframe_tests(modified_from=modified_from)
    groups: dict[tuple, dict] = {}
    max_mod = None
    for t in tests:
        max_mod = _max_iso(max_mod, t.get("modifiedDateUtc"))
        name = f"{t.get('testTypeName', '')} {t.get('testPositionName', '')}".lower()
        if not any(k in name for k in FORCEFRAME_HIP_KEYWORDS):
            continue
        dt = _parse_dt(t.get("testDateUtc"))
        pid = str(t.get("profileId"))
        if dt is None:
            continue
        g = groups.setdefault((pid, dt.date()), {"dt": dt, "vals": {}})
        g["dt"] = min(g["dt"], dt)
        for src, fk in FORCEFRAME_FIELD_MAP.items():
            v = _num(t.get(src))
            if v is not None:
                g["vals"][fk] = max(g["vals"].get(fk, v), v)
    for (pid, _day), g in sorted(groups.items(), key=lambda kv: kv[1]["dt"]):
        player = links.get(pid)
        if player is None:
            report["unmatched"] += 1
            continue
        _create_result(template, player, g["dt"], g["vals"], dry_run=dry_run, report=report)
    return max_mod


def _ingest_nordbord(client, club, links, slug_map, *, modified_from, dry_run, report):
    template = _template(club, slug_map["nordico"])
    if template is None:
        return None
    tests = client.list_nordbord_tests(modified_from=modified_from)
    groups: dict[tuple, dict] = {}
    max_mod = None
    for t in tests:
        max_mod = _max_iso(max_mod, t.get("modifiedDateUtc"))
        name = (t.get("testTypeName") or "").lower()
        if not any(k in name for k in NORDBORD_KEYWORDS):
            continue
        dt = _parse_dt(t.get("testDateUtc"))
        left, right = _num(t.get("leftMaxForce")), _num(t.get("rightMaxForce"))
        if dt is None or left is None or right is None:
            continue
        g = groups.setdefault(
            (str(t.get("profileId")), dt.date()),
            {"dt": dt, "left": left, "right": right},
        )
        g["dt"] = min(g["dt"], dt)
        g["left"] = max(g["left"], left)
        g["right"] = max(g["right"], right)
    for (pid, _day), g in sorted(groups.items(), key=lambda kv: kv[1]["dt"]):
        player = links.get(pid)
        if player is None:
            report["unmatched"] += 1
            continue
        raw = {"left_max": g["left"], "right_max": g["right"]}
        _create_result(template, player, g["dt"], raw, dry_run=dry_run, report=report)
    return max_mod


# --- Orchestration ----------------------------------------------------------

_PRODUCTS = ("forcedecks", "forceframe", "nordbord")
_INGESTORS = {
    "forcedecks": _ingest_forcedecks,
    "forceframe": _ingest_forceframe,
    "nordbord": _ingest_nordbord,
}
# Default template slug per test type — overridable per club on ValdIntegration.
_DEFAULT_SLUGS = {
    "cmj": "cmj", "imtp": "imtp", "hip_adab": "hip_adab", "nordico": "nordico",
}


def _slug_map(integ) -> dict:
    return {
        "cmj": integ.cmj_template_slug or _DEFAULT_SLUGS["cmj"],
        "imtp": integ.imtp_template_slug or _DEFAULT_SLUGS["imtp"],
        "hip_adab": integ.hip_adab_template_slug or _DEFAULT_SLUGS["hip_adab"],
        "nordico": integ.nordico_template_slug or _DEFAULT_SLUGS["nordico"],
    }


def _enabled_products(integ) -> tuple:
    return tuple(p for p in _PRODUCTS if getattr(integ, f"sync_{p}", True))


def _resolve_credentials(integ: ValdIntegration):
    return (
        integ.client_id or getattr(settings, "VALD_CLIENT_ID", ""),
        integ.client_secret or getattr(settings, "VALD_CLIENT_SECRET", ""),
    )


def sync_club(
    club, *, full=False, products=None, profiles_only=False, dry_run=False, since=None,
) -> dict:
    """Sync one club's VALD tenant. Returns a report dict.

    `products=None` uses the club's per-product toggles (the scheduled path).
    Passing an explicit tuple (e.g. from `--product`) bypasses the toggles for
    a deliberate manual run. `since` (ISO-UTC) overrides the incremental cursor
    for this run — used to chunk a large backfill or probe a recent window."""
    report = {
        "club": club.name, "status": "ok",
        "profiles_seen": 0, "profiles_new": 0, "profiles_unresolved": 0,
        "created": 0, "skipped": 0, "unmatched": 0, "no_metrics": 0,
    }
    integ = ValdIntegration.objects.filter(club=club).first()
    if integ is None or not integ.enabled:
        report["status"] = "skipped"
        report["reason"] = "no enabled VALD integration"
        return report
    client_id, client_secret = _resolve_credentials(integ)
    if not (client_id and client_secret and integ.tenant_id):
        report["status"] = "skipped"
        report["reason"] = "missing credentials / tenant_id"
        return report

    client = ValdHubClient(
        region=integ.region or getattr(settings, "VALD_DEFAULT_REGION", "use"),
        tenant_id=integ.tenant_id,
        client_id=client_id, client_secret=client_secret,
    )
    cursors = dict(integ.sync_cursors or {})

    # 1. Profiles — always pulled in FULL (they're cheap, and a complete link
    #    table means product ingestion never misses a player just because their
    #    profile wasn't modified in this window). `--since` can bound it for
    #    manual probes; product syncs below stay cursor-incremental.
    profiles = client.list_profiles(modified_from=since)
    resolved = _sync_profiles(club, profiles, dry_run=dry_run, report=report)

    if not profiles_only:
        # All persisted resolved links (covers profiles not modified this run),
        # overlaid with this run's in-memory resolution (so a dry-run — which
        # persists nothing — still resolves the tests it's previewing).
        links = {
            l.vald_profile_id: l.player
            for l in ValdProfileLink.objects.filter(
                club=club, player__isnull=False,
            ).select_related("player")
        }
        links.update(resolved)
        slug_map = _slug_map(integ)
        effective = products if products is not None else _enabled_products(integ)
        for product in effective:
            ingest = _INGESTORS.get(product)
            if ingest is None:
                continue
            try:
                max_mod = ingest(
                    client, club, links, slug_map,
                    modified_from=since or (None if full else cursors.get(product)),
                    dry_run=dry_run, report=report,
                )
            except Exception as exc:  # noqa: BLE001 — one product shouldn't abort the rest
                logger.exception("VALD %s ingest failed for %s: %s", product, club.name, exc)
                report.setdefault("errors", []).append(f"{product}: {exc}")
                continue
            if max_mod:
                cursors[product] = max_mod

    if not dry_run:
        integ.sync_cursors = cursors
        integ.last_synced_at = timezone.now()
        integ.save(update_fields=["sync_cursors", "last_synced_at", "updated_at"])
    return report


def sync_all_bound_clubs(*, full=False, dry_run=False) -> list[dict]:
    """Sync every club with an enabled VALD integration. Per-club try/except so
    one club's failure doesn't abort the batch."""
    reports = []
    for integ in ValdIntegration.objects.filter(enabled=True).select_related("club"):
        try:
            reports.append(sync_club(integ.club, full=full, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001
            logger.exception("VALD sync failed for club %s: %s", integ.club_id, exc)
            reports.append({"club": integ.club.name, "status": "error", "reason": str(exc)})
    return reports
