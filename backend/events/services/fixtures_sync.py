"""Sync a category's match calendar + results from API-Football.

Pulls every fixture the bound team played in a season (all competitions),
upserts each as a match `Event` (idempotent via the fixture id), and — for
completed matches — imports the tactical data (lineups, events, team &
per-player stats) into `MatchData`.

Binding lives on `Category.external_config`:
    {"provider": "api_football", "team_id": N, "season": YYYY,
     "department_slug": "tactico"}   # department_slug optional

Categories without an `api_football` config are skipped silently (youth
categories aren't covered by API-Football). Never partially corrupts: one
bad fixture is logged and skipped; a stats fetch failure leaves the Event.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction

from core.models import Category, Department
from events.models import Event, MatchData
from integrations.api_football.client import ApiFootballClient
from integrations.api_football.dtos import Fixture
from integrations.api_football.exceptions import ApiFootballRateLimitError

logger = logging.getLogger(__name__)

# Fixture statuses we treat as "played" → worth importing tactical data.
_COMPLETED = {"FT", "AET", "PEN"}
# Department slugs that own the match calendar, in preference order.
_MATCH_DEPT_PREFERENCE = ("tactico", "tecnico", "fisico")


def sync_category_fixtures(
    category: Category,
    *,
    client: ApiFootballClient | None = None,
    with_stats: bool = True,
    stats_limit: int | None = None,
) -> dict:
    """Sync one category. Returns a summary dict (also when skipped).

    `stats_limit` caps how many completed matches get their tactical data
    fetched this run, and only targets matches that don't have it yet — so
    on the free tier (100 req/day, 4 calls per match) the backlog fills
    over several runs instead of blowing the quota. None = no cap.
    """
    cfg = category.external_config or {}
    if cfg.get("provider") != "api_football":
        return {"category": category.name, "skipped": "no api_football binding"}
    team_id, season = cfg.get("team_id"), cfg.get("season")
    if not team_id or not season:
        return {"category": category.name, "skipped": "missing team_id/season"}

    department = _resolve_match_department(category, cfg)
    if department is None:
        return {"category": category.name, "skipped": "no department for matches"}

    client = client or ApiFootballClient()
    fixtures = client.list_fixtures(team_id=int(team_id), season=int(season))

    # 0) Refresh competition + rival reference data (date windows + teams) so
    # the match-create dropdowns work offline. Additive — never block fixtures.
    competitions_synced = 0
    try:
        competitions_synced = _sync_competitions_and_teams(client, int(team_id), int(season))
    except ApiFootballRateLimitError:
        logger.warning("Hit quota syncing competitions/teams; skipping this run.")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to sync competitions/teams.")

    # 1) Upsert every fixture as a match Event (cheap — 1 list call total).
    created = updated = 0
    completed: list[tuple[Event, int]] = []
    for fx in fixtures:
        event, was_created = _upsert_event(category, department, int(team_id), fx)
        created += was_created
        updated += (not was_created)
        if fx.status_short in _COMPLETED:
            completed.append((event, fx.id))

    # 2) Tactical data for completed matches (4 calls each) — quota-aware.
    stats_synced = 0
    rate_limited = False
    if with_stats:
        targets = completed
        if stats_limit is not None:
            targets = [
                (ev, fid) for (ev, fid) in completed
                if not MatchData.objects.filter(event=ev).exists()
            ][:stats_limit]
        for event, fid in targets:
            try:
                _sync_match_data(client, event, fid)
                stats_synced += 1
            except ApiFootballRateLimitError:
                rate_limited = True
                logger.warning("Hit API-Football daily quota; stopping stats sync.")
                break
            except Exception:  # noqa: BLE001 — stats are additive; never block the calendar
                logger.exception("Failed to sync MatchData for fixture %s.", fid)

    return {
        "category": category.name, "fixtures": len(fixtures),
        "created": created, "updated": updated,
        "competitions_synced": competitions_synced,
        "stats_synced": stats_synced, "stats_pending": len(completed) - stats_synced,
        "rate_limited": rate_limited,
    }


def _parse_date(s):
    from datetime import date as _date
    if not s:
        return None
    try:
        y, m, d = (int(x) for x in str(s)[:10].split("-"))
        return _date(y, m, d)
    except (ValueError, TypeError):
        return None


def _upsert_external_team(external_id: int, name: str, *, country="", code="", logo="") -> "ExternalTeam":
    from events.models import ExternalTeam
    team, _ = ExternalTeam.objects.update_or_create(
        provider="api_football", external_id=int(external_id),
        defaults={"name": name, **({"country": country} if country else {}),
                  **({"code": code} if code else {}), **({"logo_url": logo} if logo else {})},
    )
    return team


def _sync_competitions_and_teams(client: ApiFootballClient, team_id: int, season: int) -> int:
    """Upsert Competition rows (date windows) + their ExternalTeam rosters from
    `/leagues?team` and `/teams?league`. Returns the competition count."""
    from events.models import Competition

    leagues = client.list_team_leagues(team_id, season)
    n = 0
    for item in leagues:
        lg = item.get("league") or {}
        if not lg.get("id"):
            continue
        country = (item.get("country") or {}).get("name") or ""
        sea = next((s for s in (item.get("seasons") or []) if s.get("year") == season), {})
        comp, _ = Competition.objects.update_or_create(
            provider="api_football", external_id=int(lg["id"]), season=season,
            defaults={
                "name": lg.get("name") or "", "country": country,
                "logo_url": lg.get("logo") or "",
                "start_date": _parse_date(sea.get("start")),
                "end_date": _parse_date(sea.get("end")),
            },
        )
        teams_resp = client.list_league_teams(int(lg["id"]), season)
        # Pseudo-leagues like "Friendlies Clubs" return every club worldwide
        # (~thousands) — not a real roster. Skip the team list for those; the
        # UI falls back to a free-text rival for such competitions.
        if len(teams_resp) > _MAX_COMPETITION_TEAMS:
            comp.teams.clear()
            logger.info("Competition %s has %d teams (global bucket) — roster skipped.",
                        comp.name, len(teams_resp))
            n += 1
            continue
        teams = []
        for it in teams_resp:
            t = it.get("team") or {}
            if not t.get("id"):
                continue
            teams.append(_upsert_external_team(
                t["id"], t.get("name") or "", country=t.get("country") or "",
                code=t.get("code") or "", logo=t.get("logo") or "",
            ))
        comp.teams.set(teams)
        n += 1
    return n


# A real domestic/continental competition has at most a few dozen teams; far
# above this is a global aggregate league (e.g. Friendlies) with no fixed roster.
_MAX_COMPETITION_TEAMS = 100


def sync_all_bound_categories(
    *, with_stats: bool = True, stats_limit: int | None = None,
) -> list[dict]:
    """Sync every category bound to API-Football. Used by the Celery beat
    task / management command."""
    bound = Category.objects.filter(external_config__provider="api_football")
    out = []
    for cat in bound:
        try:
            out.append(sync_category_fixtures(
                cat, with_stats=with_stats, stats_limit=stats_limit,
            ))
        except Exception:  # noqa: BLE001 — one category failing mustn't stop the rest
            logger.exception("Fixture sync failed for category %s.", cat.id)
            out.append({"category": cat.name, "error": True})
    return out


# ─── Internals ────────────────────────────────────────────────────────


def _resolve_match_department(category: Category, cfg: dict) -> Department | None:
    qs = Department.objects.filter(club_id=category.club_id)
    slug = cfg.get("department_slug")
    if slug:
        d = qs.filter(slug=slug).first()
        if d:
            return d
    for s in _MATCH_DEPT_PREFERENCE:
        d = qs.filter(slug=s).first()
        if d:
            return d
    return qs.first()


@transaction.atomic
def _upsert_event(
    category: Category, department: Department, team_id: int, fx: Fixture,
) -> tuple[Event, bool]:
    """Create or update the match Event for this fixture. Idempotent on
    `metadata.api_football_fixture_id` within the club."""
    is_home = fx.home.id == team_id
    opponent = fx.away.name if is_home else fx.home.name
    opponent_team_id = fx.away.id if is_home else fx.home.id
    title = f"{fx.home.name} vs {fx.away.name}"
    metadata = {
        "api_football_fixture_id": fx.id,
        "competition": fx.league_name,
        "league_id": fx.league_id,
        "season": fx.season,
        "round": fx.round,
        "status": fx.status_short,
        "status_long": fx.status_long,
        "venue": fx.venue_name,
        "is_home": is_home,
        "opponent": opponent,
        "opponent_team_id": opponent_team_id,
        "score": {"home": fx.home_goals, "away": fx.away_goals},
    }

    event = (
        Event.objects
        .filter(club_id=category.club_id, metadata__api_football_fixture_id=fx.id)
        .first()
    )
    if event is None:
        # Reconcile with a match Event already created for this match-day by
        # another source — the GPS importer keys its events by date, not by
        # fixture id, so without this the API sync would create a duplicate
        # match for every GPS-loaded game. The ±16h window tolerates the
        # noon-vs-kickoff + timezone offset; we only adopt events not yet
        # bound to a fixture. The reconciled event keeps its GPS results.
        window = timedelta(hours=16)
        event = (
            Event.objects
            .filter(
                club_id=category.club_id, category_id=category.id,
                event_type=Event.TYPE_MATCH,
                starts_at__range=(fx.date - window, fx.date + window),
            )
            .exclude(metadata__has_key="api_football_fixture_id")
            .order_by("starts_at")
            .first()
        )
        if event is not None:
            logger.info("Reconciling fixture %s onto existing event %s (%s).",
                        fx.id, event.id, event.starts_at.date())
    if event is None:
        event = Event(
            club_id=category.club_id, department=department,
            event_type=Event.TYPE_MATCH, scope=Event.SCOPE_CATEGORY,
            category=category,
        )
        created = True
    else:
        created = False

    event.title = title
    event.starts_at = fx.date
    event.location = fx.venue_name
    # Preserve any non-provider keys staff may have added.
    event.metadata = {**(event.metadata or {}), **metadata}
    if opponent_team_id:
        event.opponent_team = _upsert_external_team(opponent_team_id, opponent)
    event.save()
    return event, created


def _sync_match_data(client: ApiFootballClient, event: Event, fixture_id: int) -> None:
    MatchData.objects.update_or_create(
        event=event,
        defaults={
            "source": "api_football",
            "fixture_id": fixture_id,
            "lineups": client.get_fixture_lineups(fixture_id),
            "events": client.get_fixture_events(fixture_id),
            "team_statistics": client.get_fixture_statistics(fixture_id),
            "player_statistics": client.get_fixture_players(fixture_id),
        },
    )
