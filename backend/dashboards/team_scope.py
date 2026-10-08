"""A category's TEAM, for match-based layouts: whose matches, and who played.

A category is a cohort (Serie 2008); a match is played by a TEAM — the U18 —
and in 2026 that team is two cohorts, Serie 2008 and Serie 2009
(`TeamSeason`: season × bracket → categories). Players of other cohorts play
for it too: a Serie 2010 kid playing up in the U18 match. The club's GPS sheet
is per team (`origen_hoja` = "U18"), so the team's match rows are exactly:

    sheet U<bracket> in a season the category entered that bracket
    (or, for a row with no sheet, linked to that bracket's match that season)

A layout that opts in (`match_selector_config.team = true`) reads only those
rows, and its roster is the category's own players PLUS everyone who appears
in them — shown flagged, like a call-up (`PlayerCallUp`), when their home
category is not one of the team's cohorts. Unlike a call-up they DO count in
the match numbers: they played the match, and leaving them out would
understate its load.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from django.db.models import Q

from core.models import Category, TeamSeason
from exams.models import ExamResult


@dataclass(frozen=True)
class TeamScope:
    rows: Q                                   # the team's match rows
    players: frozenset = field(default_factory=frozenset)   # everyone in them
    own_categories: frozenset = field(default_factory=frozenset)  # its cohorts


def _hoja(bracket_name: str) -> str | None:
    m = re.fullmatch(r"Sub (\d{2})", bracket_name or "")
    return f"U{m.group(1)}" if m else None


def for_category(category: Category, template_slug: str = "gps_partido") -> TeamScope | None:
    """None when the category never entered a youth bracket (nothing to scope)."""
    seasons = list(TeamSeason.objects.filter(team=category).select_related("bracket"))
    q = Q()
    own: set[UUID] = {category.id}
    for ts in seasons:
        hoja = _hoja(ts.bracket.name)
        if hoja is None:
            continue
        q |= Q(result_data__origen_hoja=hoja, recorded_at__year=ts.season)
        q |= Q(result_data__origen_hoja__isnull=True, event__bracket=ts.bracket,
               event__starts_at__year=ts.season)
        own |= set(TeamSeason.objects.filter(season=ts.season, bracket=ts.bracket,
                                             team__club_id=category.club_id)
                   .values_list("team_id", flat=True))
    if not q:
        return None
    # The club, always: a sheet name ("U18") and a bracket ("Sub 18") are not
    # club-specific, and without it a demo club's GPS partido listed the real
    # club's matches and pulled its players into the roster (2026-10-08).
    rows = q & Q(template__slug=template_slug,
                 player__category__club_id=category.club_id)
    players = frozenset(ExamResult.objects.filter(rows)
                        .values_list("player_id", flat=True).distinct())
    return TeamScope(rows=rows, players=players, own_categories=frozenset(own))
