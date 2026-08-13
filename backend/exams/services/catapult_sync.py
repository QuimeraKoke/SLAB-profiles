"""Catapult OpenField → ExamResult GPS sync.

Fills each day of a category's recent window: if a match fixture exists that day
the activity is ingested as **gps_partido** (linked to that Event, which the
template requires); otherwise as **gps_sesion**. Gap-fill + idempotent — an
activity already ingested (same Catapult `activity_id`, stashed in
`result_data["catapult_activity_id"]`) is skipped, so two distinct sessions on
the same day stay as two separate rows.

Phase 1 exposes the read-only **planner** (`dry_run=True`): it fetches, classifies,
resolves athletes and previews the `ExamResult` rows it *would* write — touching
nothing. The commit path (`dry_run=False`) reuses the same plan and creates rows
via `ExamResult.objects.create()` (per-row, so GPS post-save signals fire) plus
auto-creates `CatapultAthleteLink`s (never overwriting a manual link).

Classification signals (from the U. de Chile test tenant, 2026-08):
  * `game_id` is present on EVERY activity → NOT a match signal.
  * DayCode tag `MD` (exactly) = match day; `MD-1`/`MD+2`/`Other`/… = training.
  * Match activity names carry " vs "; trainings are "Sesión <dd-mm-yy>".

Metric mapping (gps field_key → /stats slug) is verified against real match data
— see CATAPULT_INTEGRATION_STRATEGY.md §6.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.utils import timezone as djtz

from core.models import Player, PlayerAlias
from events.models import Event
from exams.calculations import compute_result_data
from exams.models import (
    CatapultAthleteLink,
    CatapultIntegration,
    ExamResult,
    ExamTemplate,
)
from integrations.catapult.client import CatapultClient
from integrations.catapult.exceptions import CatapultBadResponse, CatapultError

logger = logging.getLogger(__name__)

# gps template field_key → Catapult /stats parameter slug (plain strings; a slug
# with a "." is rejected 422). Verified against F18 vs Palestino (2026-08).
SLUG_MAP = {
    "tot_dist": "total_distance",
    "mpm": "meterage_per_minute",
    "hsr": "distancia_mai_-_sprint_>_22km/h",
    "max_vel": "max_vel",
    "acc": "gen2_acceleration_band7plus_total_effort_count",
    "dec": "gen2_acceleration_band2plus_total_effort_count",
    "dist_acc": "gen2_acceleration_band7plus_total_distance",
    "dist_dec": "gen2_acceleration_band2plus_total_distance",
    "hmld": "distancia_alta_potencia_metabolica_x_session",
    "sprints": "gen2_velocity_band5_total_effort_count",   # tentative — confirm band
    "sprint_dist": "gen2_velocity_band5_total_distance",   # tentative — confirm band
}
DURATION_SLUG = "total_duration"  # SECONDS → tot_dur is MINUTES (÷60)

# Slugs guaranteed valid on any tenant — the fallback set if the full request
# 422s on a tenant-specific slug, so one bad slug never zeroes an activity.
CORE_SLUGS = ["total_distance", "meterage_per_minute", DURATION_SLUG]

MATCH_DAYCODE = "MD"

# Per-category commit lock TTL (seconds) — longer than any real run, shorter
# than the hourly beat interval so a crashed run self-heals within one tick.
_COMMIT_LOCK_TTL = 1800


# ── normalization ──────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """NFD strip-accents, uppercase, single-spaced — the importer name rule."""
    s = unicodedata.normalize("NFD", (s or "").upper())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


_DATE_RE = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")


def _activity_day(activity: dict) -> date:
    """The staff-meaningful day: parse the dd-mm-yy embedded in a training name
    (how the club labels sessions), else fall back to the UTC start date."""
    m = _DATE_RE.search(activity.get("name") or "")
    if m:
        d, mo, y = (int(x) for x in m.groups())
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            pass
    ts = activity.get("start_time")
    if ts:
        return datetime.fromtimestamp(ts, tz=dt_timezone.utc).date()
    return djtz.now().date()


def _daycode(activity: dict) -> str | None:
    for t in activity.get("tag_list") or []:
        if isinstance(t, dict) and t.get("tag_type_name") == "DayCode":
            return t.get("name")
    return None


# ── plan structures ────────────────────────────────────────────────────────

@dataclass
class PlannedRow:
    athlete_id: str
    athlete_name: str
    player_id: str | None
    player_name: str | None
    match_method: str | None       # how the athlete resolved (None = unresolved)
    data: dict                     # mapped field_key → value (schema fields only)
    status: str                    # new | exists | unresolved | no_metrics | short


@dataclass
class PlannedActivity:
    activity_id: str
    name: str
    day: str
    tipo: str                      # "partido" | "entrenamiento"
    template_slug: str
    event_id: str | None
    signal: str                    # human-readable classification rationale
    athlete_count: int
    note: str = ""
    rows: list[PlannedRow] = field(default_factory=list)


@dataclass
class CategoryPlan:
    category: str
    strategy: str
    window_days: int
    activities: list[PlannedActivity] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def totals(self) -> dict:
        rows = [r for a in self.activities for r in a.rows]
        by = lambda st: sum(1 for r in rows if r.status == st)  # noqa: E731
        return {
            "activities": len(self.activities),
            "partidos": sum(1 for a in self.activities if a.tipo == "partido"),
            "entrenamientos": sum(1 for a in self.activities if a.tipo == "entrenamiento"),
            "rows_new": by("new"),
            "rows_exists": by("exists"),
            "rows_unresolved": by("unresolved"),
            "rows_no_metrics": by("no_metrics"),
            "rows_short": by("short"),
        }


# ── roster resolution ──────────────────────────────────────────────────────

def _roster_index(category):
    players = list(Player.objects.filter(category=category))
    by_dob: dict[str, list] = {}
    by_name: dict[str, object] = {}
    for p in players:
        if p.date_of_birth:
            by_dob.setdefault(p.date_of_birth.isoformat(), []).append(p)
        by_name[_norm(f"{p.first_name} {p.last_name}")] = p
    for a in PlayerAlias.objects.filter(player__in=players):
        by_name[_norm(a.value)] = a.player
    return players, by_dob, by_name


def _resolve_athlete(athlete: dict, by_dob, by_name, link_cache):
    """(player, match_method) — existing link (incl. manual) wins, then
    name+unique-DOB, then name. Returns (None, None) if unresolved."""
    aid = athlete.get("id")
    link = link_cache.get(aid)
    if link is not None:
        return link.player, link.match_method
    dob = athlete.get("date_of_birth_date")
    nm = _norm(f"{athlete.get('first_name', '')} {athlete.get('last_name', '')}")
    if dob and len(by_dob.get(dob, [])) == 1:
        return by_dob[dob][0], CatapultAthleteLink.MATCH_NAME_DOB
    if nm in by_name:
        return by_name[nm], CatapultAthleteLink.MATCH_NAME
    return None, None


# ── fixture (match Event) lookup ───────────────────────────────────────────

def _match_event_index(category, since_day: date, until_day: date) -> dict:
    qs = Event.objects.filter(
        club_id=category.club_id,
        event_type=Event.TYPE_MATCH,
        starts_at__date__gte=since_day - timedelta(days=1),
        starts_at__date__lte=until_day + timedelta(days=1),
    )
    idx: dict[date, list] = {}
    for e in qs:
        d = (djtz.localtime(e.starts_at) if djtz.is_aware(e.starts_at) else e.starts_at).date()
        idx.setdefault(d, []).append(e)
    return idx


def _pick_event(idx: dict, day: date, category, *, tolerance: int):
    """The match Event for `day`, preferring one scoped to this category, then
    club-wide. `tolerance=0` = exact day (used for the *decision*); `tolerance=1`
    also checks ±1 day to absorb the tz/midnight boundary (used for the *attach*,
    since a match kicking off in the evening can land on the next UTC day)."""
    deltas = [0] if tolerance == 0 else [0, -1, 1]
    for delta in deltas:
        cands = idx.get(day + timedelta(days=delta))
        if not cands:
            continue
        same_cat = [e for e in cands if e.category_id == category.id]
        club_wide = [e for e in cands if e.category_id is None]
        return (same_cat or club_wide or cands)[0]
    return None


# ── /stats → gps field mapping ─────────────────────────────────────────────

def _fetch_stats(client, activity_id, report_errors: list) -> dict:
    """athlete_id → {slug: value}. Full slug set first; on 422 (a tenant-specific
    slug is unknown) retry with the guaranteed-valid CORE set, degraded."""
    slugs = sorted(set(SLUG_MAP.values()) | {DURATION_SLUG})
    try:
        rows = client.stats(activity_id, slugs)
    except CatapultBadResponse as exc:
        report_errors.append(f"{activity_id}: full /stats 422 ({str(exc)[:80]}) → CORE only")
        try:
            rows = client.stats(activity_id, CORE_SLUGS)
        except CatapultError as exc2:
            report_errors.append(f"{activity_id}: CORE /stats failed ({str(exc2)[:80]})")
            return {}
    return {r.get("athlete_id"): r for r in rows}


def _map_row(stats: dict) -> dict:
    """Catapult /stats row → gps field_key values (schema fields only)."""
    data: dict[str, float] = {}
    for fk, slug in SLUG_MAP.items():
        v = _num(stats.get(slug))
        if v is not None:
            data[fk] = round(v, 2)
    dur = _num(stats.get(DURATION_SLUG))
    if dur is not None:
        data["tot_dur"] = round(dur / 60.0, 1)
    return data


# ── the planner ────────────────────────────────────────────────────────────

def plan_category(integ: CatapultIntegration, *, dry_run: bool = True, now=None) -> CategoryPlan:
    """Public entry. On a committing run, hold a per-category cache lock so a
    manual `--commit` and the hourly beat can't overlap — the dedup is
    check-then-create, so two concurrent writers would duplicate rows. Dry-runs
    never lock. Cache backend down → proceed rather than block ingestion."""
    if dry_run or not getattr(integ, "category_id", None):
        return _plan_category(integ, dry_run=dry_run, now=now)
    from django.core.cache import cache

    key = f"lock:catapult_sync:{integ.category_id}"
    try:
        got = cache.add(key, "1", _COMMIT_LOCK_TTL)
    except Exception:  # pragma: no cover — cache unavailable
        got, key = True, None
    if not got:
        plan = CategoryPlan(category=str(integ.category), strategy=integ.classify_strategy,
                            window_days=integ.lookback_days)
        plan.errors.append("otra sincronización en curso (lock) — omitido")
        logger.info("Catapult sync skipped for %s: another run holds the lock", integ.category)
        return plan
    try:
        return _plan_category(integ, dry_run=dry_run, now=now)
    finally:
        if key:
            try:
                cache.delete(key)
            except Exception:  # pragma: no cover
                pass


def _plan_category(integ: CatapultIntegration, *, dry_run: bool = True, now=None) -> CategoryPlan:
    category = integ.category
    plan = CategoryPlan(
        category=str(category), strategy=integ.classify_strategy,
        window_days=integ.lookback_days,
    )
    client = CatapultClient(integ.api_token, base_url=integ.base_url)
    now = now or djtz.now()
    since = now - timedelta(days=integ.lookback_days)
    since_ts = since.timestamp()

    try:
        acts = [a for a in client.activities() if (a.get("start_time") or 0) >= since_ts]
        athletes = client.athletes()
    except CatapultError as exc:
        plan.errors.append(f"Catapult API: {exc}")
        return plan

    # athlete_id → current_team_id, to scope activities to this category's team.
    team_of = {a.get("id"): a.get("current_team_id") for a in athletes}
    team_id = (integ.catapult_team_id or "").strip()

    players, by_dob, by_name = _roster_index(category)
    link_cache = {
        l.athlete_id: l
        for l in CatapultAthleteLink.objects.filter(player__in=players).select_related("player")
    }
    acts.sort(key=lambda a: a.get("start_time") or 0)
    days = [_activity_day(a) for a in acts]
    event_idx = _match_event_index(category, min(days), max(days)) if days else {}

    partido_t = _template(integ.partido_template_slug, category)
    sesion_t = _template(integ.sesion_template_slug, category)

    for a in acts:
        roster = client.activity_athletes(a["id"])
        # Team scoping: keep only athletes belonging to this Catapult team (if a
        # team is configured). Skip the whole activity when none belong.
        if team_id:
            roster = [r for r in roster if team_of.get(r.get("id")) == team_id]
        if not roster:
            continue

        day = _activity_day(a)
        daycode = _daycode(a)
        name = a.get("name") or ""
        event = _pick_event(event_idx, day, category, tolerance=1)        # attach (±1)
        fixture_on_day = _pick_event(event_idx, day, category, tolerance=0) is not None

        is_match = _decide(integ.classify_strategy, daycode=daycode, name=name,
                           fixture_on_day=fixture_on_day)
        if is_match and not integ.sync_matches:
            continue
        if not is_match and not integ.sync_training:
            continue

        tipo = "partido" if is_match else "entrenamiento"
        template = partido_t if is_match else sesion_t
        signal = f"DayCode={daycode or '—'} · fixture={'✓' if fixture_on_day else '✗'}"
        pa = PlannedActivity(
            activity_id=a["id"], name=name, day=day.isoformat(), tipo=tipo,
            template_slug=(template.slug if template else (integ.partido_template_slug
                           if is_match else integ.sesion_template_slug)),
            event_id=(str(event.id) if event else None), signal=signal,
            athlete_count=len(roster),
        )
        if template is None:
            pa.note = "plantilla no encontrada — omitido"
            plan.activities.append(pa)
            continue
        if is_match and event is None:
            # gps_partido requires an Event FK; we can't write it without one.
            pa.note = ("clasificado partido pero sin fixture en SLAB — creá el "
                       "partido (Event) ese día para poder ingerir gps_partido")

        stats = _fetch_stats(client, a["id"], plan.errors)
        for r in roster:
            player, method = _resolve_athlete(r, by_dob, by_name, link_cache)
            aname = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
            if player is None:
                pa.rows.append(PlannedRow(
                    r.get("id"), aname, None, None, None, {}, "unresolved"))
                continue
            data = _map_row(stats.get(r.get("id"), {}))
            data["fecha"] = day.isoformat()
            data["sesion"] = name
            data["catapult_activity_id"] = a["id"]
            if not is_match:
                data["tipo_sesion"] = daycode or "Entrenamiento"
            metric_keys = [k for k in data if k in SLUG_MAP or k == "tot_dur"]
            if not metric_keys:
                status = "no_metrics"
            elif (not is_match and integ.min_training_minutes
                  and (data.get("tot_dur") or 0) < integ.min_training_minutes):
                status = "short"
            elif is_match and event is None:
                status = "no_metrics"  # can't write partido without event
            else:
                status = _row_status(template, player, day, a["id"])
            pa.rows.append(PlannedRow(
                r.get("id"), aname, str(player.id),
                f"{player.first_name} {player.last_name}", method, data, status))

        if not dry_run:
            _commit_activity(pa, template, event, integ, link_cache, by_dob, by_name, roster)
        plan.activities.append(pa)

    if not dry_run:
        integ.last_synced_at = now
        integ.save(update_fields=["last_synced_at", "updated_at"])
    return plan


def _decide(strategy, *, daycode, name, fixture_on_day) -> bool:
    """Is THIS activity a match? The per-activity signal (DayCode==MD or a
    " vs " name) is the accurate discriminator; the fixture is exact-day only,
    so an adjacent-day training (MD-1 / MD+1) near a match is NOT promoted."""
    signal = daycode == MATCH_DAYCODE or " vs " in name.lower()
    if strategy == CatapultIntegration.NAME:
        return " vs " in name.lower()
    if strategy == CatapultIntegration.FIXTURE:
        return fixture_on_day
    if strategy == CatapultIntegration.HYBRID:
        return signal or fixture_on_day
    return signal  # TAG (default) — Catapult's own DayCode/name signal


def _template(slug: str, category) -> ExamTemplate | None:
    return (
        ExamTemplate.objects.filter(
            slug=slug, is_active_version=True, department__club_id=category.club_id,
        ).first()
        or ExamTemplate.objects.filter(slug=slug, is_active_version=True).first()
    )


def _row_status(template, player, day: date, activity_id: str) -> str:
    exists = ExamResult.objects.filter(
        template__family_id=template.family_id, player=player,
        result_data__catapult_activity_id=activity_id,
    ).exists()
    return "exists" if exists else "new"


def _commit_activity(pa, template, event, integ, link_cache, by_dob, by_name, roster):
    """Persist the plan's `new` rows + auto-create athlete links. Called only
    when dry_run=False and (for partidos) an Event is present."""
    if pa.tipo == "partido" and event is None:
        return
    roster_by_id = {r.get("id"): r for r in roster}
    for row in pa.rows:
        if row.status != "new" or not row.player_id:
            continue
        player = Player.objects.get(id=row.player_id)
        recorded_at = datetime.combine(
            date.fromisoformat(row.data["fecha"]),
            datetime.min.time().replace(hour=12), tzinfo=dt_timezone.utc)
        data, snapshot = compute_result_data(template, row.data, player=player)
        ExamResult.objects.create(
            player=player, template=template, recorded_at=recorded_at,
            result_data=data, inputs_snapshot=snapshot,
            event=event if pa.tipo == "partido" else None,
        )
        # Auto-link the athlete (never overwrite an existing/manual link).
        if row.match_method and row.match_method != CatapultAthleteLink.MATCH_MANUAL \
                and row.athlete_id not in link_cache:
            src = roster_by_id.get(row.athlete_id, {})
            link, created = CatapultAthleteLink.objects.get_or_create(
                athlete_id=row.athlete_id,
                defaults=dict(
                    player=player, athlete_name=row.athlete_name,
                    match_method=row.match_method),
            )
            if created:
                link_cache[row.athlete_id] = link


def plan_all_enabled(*, dry_run: bool = True) -> list[CategoryPlan]:
    plans = []
    for integ in CatapultIntegration.objects.filter(enabled=True).select_related("category"):
        try:
            plans.append(plan_category(integ, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001 — one category shouldn't kill the run
            logger.exception("Catapult sync failed for %s", integ.category)
            cp = CategoryPlan(category=str(integ.category), strategy=integ.classify_strategy,
                              window_days=integ.lookback_days)
            cp.errors.append(str(exc))
            plans.append(cp)
    return plans
