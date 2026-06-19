"""Import scouting data about OPPONENT teams from API-Football.

For an upcoming rival we pull their recent form (results) and most recent
lineup/formation, and store it in `OpponentScouting` — saved in the app but
NOT shown in the normal player/team/Centro-de-mando surfaces (staff-only
prep). Reuses the same `ApiFootballClient`; quota-aware (each opponent is a
couple of calls, throttled by the client).
"""

from __future__ import annotations

import logging

from core.models import Category, Club
from events.models import Event, OpponentScouting
from integrations.api_football.client import ApiFootballClient
from integrations.api_football.exceptions import ApiFootballRateLimitError

logger = logging.getLogger(__name__)

_RECENT_FORM = 6


def sync_opponent(
    club: Club, team_id: int, team_name: str, season: int,
    *, client: ApiFootballClient | None = None, with_lineup: bool = True,
) -> OpponentScouting:
    """Fetch + store one opponent's recent form (+ last lineup). Idempotent
    per (club, team_id, season)."""
    client = client or ApiFootballClient()

    fixtures = client.list_fixtures(team_id=team_id, season=season)
    # Most recent first; keep the played ones for "form".
    played = sorted(
        (f for f in fixtures if f.status_short in ("FT", "AET", "PEN")),
        key=lambda f: f.date, reverse=True,
    )[:_RECENT_FORM]

    recent_form = []
    for f in played:
        opp_home = f.home.id == team_id
        gf = f.home_goals if opp_home else f.away_goals
        ga = f.away_goals if opp_home else f.home_goals
        result = "E"
        if gf is not None and ga is not None:
            result = "G" if gf > ga else ("P" if gf < ga else "E")
        recent_form.append({
            "date": f.date.date().isoformat(),
            "competition": f.league_name,
            "vs": f.away.name if opp_home else f.home.name,
            "home": opp_home,
            "score": f"{f.home_goals}-{f.away_goals}",
            "result": result,
            "fixture_id": f.id,
        })

    last_lineup: dict = {}
    if with_lineup and played:
        try:
            lus = client.get_fixture_lineups(played[0].id)
            last_lineup = next(
                (l for l in lus if (l.get("team") or {}).get("id") == team_id), {},
            )
        except ApiFootballRateLimitError:
            logger.warning("Quota hit fetching opponent lineup for %s.", team_name)

    scout, _ = OpponentScouting.objects.update_or_create(
        club=club, team_id=team_id, season=season,
        defaults={
            "team_name": team_name, "source": "api_football",
            "recent_form": recent_form, "last_lineup": last_lineup,
        },
    )
    return scout


def scout_category_opponents(
    category: Category, *, upcoming_only: bool = True,
    client: ApiFootballClient | None = None, limit: int | None = None,
) -> dict:
    """Scout the opponents of a category's matches (distinct teams).

    `upcoming_only` restricts to future matches (the rivals you're about to
    play). `limit` caps how many opponents are fetched this run (quota)."""
    from django.utils import timezone

    cfg = category.external_config or {}
    season = cfg.get("season")
    if not season:
        return {"category": category.name, "skipped": "no season in external_config"}

    qs = Event.objects.filter(
        club_id=category.club_id, event_type=Event.TYPE_MATCH,
        category=category, metadata__opponent_team_id__isnull=False,
    )
    if upcoming_only:
        qs = qs.filter(starts_at__gte=timezone.now())

    # Distinct opponents (team_id → name), preferring the soonest match.
    seen: dict[int, str] = {}
    for ev in qs.order_by("starts_at"):
        tid = ev.metadata.get("opponent_team_id")
        if tid and tid not in seen:
            seen[tid] = ev.metadata.get("opponent") or str(tid)

    client = client or ApiFootballClient()
    scouted = 0
    rate_limited = False
    for tid, name in list(seen.items())[: (limit or len(seen))]:
        try:
            sync_opponent(category.club, int(tid), name, int(season), client=client)
            scouted += 1
        except ApiFootballRateLimitError:
            rate_limited = True
            logger.warning("Quota hit scouting opponents; stopping.")
            break
        except Exception:  # noqa: BLE001
            logger.exception("Failed to scout opponent %s (%s).", name, tid)

    return {
        "category": category.name, "opponents_found": len(seen),
        "scouted": scouted, "rate_limited": rate_limited,
    }
