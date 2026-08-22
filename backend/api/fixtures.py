"""Upcoming fixtures, sorted by how relevant they actually are.

Past and future are different questions, and answering them the same way is
what makes a planning calendar useless:

  * **Past** is a fact — you appeared or you didn't. `EventParticipant` settles
    it, whatever category the fixture was filed under.
  * **Future** is a plan. Nobody has played yet, so relevance has to be derived,
    and the derivation has to say how sure it is.

Three layers, from certain to probable:

  1. `own`     — my team competes in that competition (`TeamSeason.bracket`).
  2. `likely`  — I have been playing in that competition this season, even
                 though my team doesn't compete in it. 37 players at this club
                 do (339 appearances), in BOTH directions: 8 Primer Equipo
                 players regularly turn out for Sub 20, and 6 Sub 20 players for
                 Sub 18. Leaving this out makes the calendar wrong for exactly
                 the players whose week is hardest to plan.
  3. `context` — the rest of the club's fixtures, for a coordinator who wants
                 the whole weekend. Separated so a UI can collapse it: the club
                 has 100 fixtures in a four-month window across nine
                 competitions, so an unlayered list is noise.

**Never resolve relevance through `Event.category`.** It carries the club's
legacy label, which is a frozen 2025 snapshot: the Sub 11 Clausura 2026 fixtures
land under the category named `SUB-11`, but that team is the 2014 cohort, which
plays Sub 12 in 2026 — those fixtures belong to the 2015 cohort, who aren't in
SLAB at all. The bracket is right; the category is not. See
PRD_EQUIPO_TEMPORADA.md.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from django.utils import timezone

from core.models import TeamSeason
from events.models import Event, EventParticipant

# Appearances in a competition before we'll call a future fixture there
# "likely". Same floor the development analysis uses: below it, one guest
# appearance would start driving someone's calendar.
MIN_APPEARANCES = 3

LAYER_LABELS = {
    "own": "Mi equipo compite acá",
    "likely": "Vengo jugando acá",
    "context": "Otros partidos del club",
}


def team_bracket_ids(team, season: int) -> set:
    """Bracket ids `team` competes in for `season`. Empty when undeclared."""
    return set(
        TeamSeason.objects
        .filter(team=team, season=season)
        .values_list("bracket_id", flat=True)
    )


def played_bracket_ids(player, season: int, *, minimum: int = MIN_APPEARANCES) -> set:
    """Brackets the player has actually appeared in this season, ≥ `minimum`.

    Evidence, not entitlement — this is what makes layer 2 measured rather than
    guessed, and it's the same signal `api.development` reports on.
    """
    counts = Counter(
        EventParticipant.objects
        .filter(
            player=player, event__event_type="match",
            event__starts_at__year=season, event__bracket__isnull=False,
        )
        .values_list("event__bracket_id", flat=True)
    )
    return {bid for bid, n in counts.items() if n >= minimum}


def _serialize(event: Event, layer: str) -> dict[str, Any]:
    meta = event.metadata or {}
    return {
        "event_id": str(event.id),
        "title": event.title,
        "starts_at": event.starts_at,
        "bracket": event.bracket.name if event.bracket else None,
        "competition": meta.get("competition"),
        "round": meta.get("round"),
        "is_home": meta.get("is_home"),
        "opponent": meta.get("opponent"),
        "venue": meta.get("venue") or event.location or None,
        "status": meta.get("status_long") or meta.get("status"),
        "layer": layer,
        "layer_label": LAYER_LABELS[layer],
    }


def upcoming(
    *, club_id, season: int | None = None, team=None, player=None,
    days: int = 45, include_context: bool = True, now=None,
) -> dict[str, Any]:
    """Upcoming fixtures for a team and/or player, split into the three layers.

    `team` defaults to the player's own team when only `player` is given, which
    is the common case: a profile page asking "what's coming up for him".
    """
    now = now or timezone.now()
    horizon = now + timezone.timedelta(days=days)
    season = season or now.year
    if team is None and player is not None:
        team = player.category

    own_ids = team_bracket_ids(team, season) if team is not None else set()
    likely_ids = played_bracket_ids(player, season) - own_ids if player else set()

    qs = (
        Event.objects
        .filter(
            club_id=club_id, event_type=Event.TYPE_MATCH,
            starts_at__gt=now, starts_at__lte=horizon,
        )
        .select_related("bracket")
        .order_by("starts_at")
    )

    layers: dict[str, list] = {"own": [], "likely": [], "context": []}
    for ev in qs:
        bid = ev.bracket_id
        if bid and bid in own_ids:
            layers["own"].append(_serialize(ev, "own"))
        elif bid and bid in likely_ids:
            layers["likely"].append(_serialize(ev, "likely"))
        elif include_context:
            layers["context"].append(_serialize(ev, "context"))

    return {
        "season": season,
        "from": now,
        "to": horizon,
        "team": team.name if team is not None else None,
        # Surfaced so a UI can explain WHY something is in `likely`, and so a
        # team with no declared TeamSeason is visibly unconfigured rather than
        # silently empty.
        "own_brackets": sorted(
            {r["bracket"] for r in layers["own"] if r["bracket"]}
        ),
        "likely_brackets": sorted(
            {r["bracket"] for r in layers["likely"] if r["bracket"]}
        ),
        "counts": {k: len(v) for k, v in layers.items()},
        "layers": [
            {"key": k, "label": LAYER_LABELS[k], "fixtures": v}
            for k, v in layers.items() if v or k != "context"
        ],
    }


def past_for_player(player, *, limit: int = 20) -> list[dict[str, Any]]:
    """Matches the player actually took part in, newest first.

    Participation only — no category or bracket filtering. Where he played is
    part of the answer, not a condition on it, so a Sub 20 appearance by a Sub 18
    player belongs in his history exactly as it happened.
    """
    eps = (
        EventParticipant.objects
        .filter(player=player, event__event_type="match")
        .select_related("event", "event__bracket")
        .order_by("-event__starts_at")[:limit]
    )
    out = []
    for ep in eps:
        row = _serialize(ep.event, "own")
        row.pop("layer"), row.pop("layer_label")
        row["match_role"] = ep.match_role
        row["minutes_played"] = ep.minutes_played
        out.append(row)
    return out
