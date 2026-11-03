"""Which days a team played (or will play) a match — the club's sheet first.

The club's GPS sheet codes each row (`MD OFICIAL`, `MD AMISTOSO`) on the day the
match was PLAYED, and "siempre lo que use la U" (2026-11-03): that is the
source. The fixture `Event`s are a fallback only, because their dates drift —
on U20's real calendar the Colo Colo match played on Saturday 17-oct is a
Monday-19 Event, Unión Española on Sunday 25 a Monday-26 one. So an Event
counts only where the sheet has NO match within `RECONCILE_DAYS` of it: in
practice, future weeks the GPS has not reached yet.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from core.localtime import local_date
from dashboards.team_scope import season_rows

OFFICIAL = "official"
FRIENDLY = "friendly"
RECONCILE_DAYS = 2
# How far a postponed match's Event may sit from the day it was played.
POSTPONE_DAYS = 21
GPS_SLUGS = ("gps_sesion", "gps_partido")
MATCH_CODES = {"MD OFICIAL": OFFICIAL, "MD AMISTOSO": FRIENDLY, "MD": OFFICIAL}


def played_dates(event_ids) -> dict[str, date]:
    """{event_id: the day it was actually played}, from its COMET match sheets.

    A fixture keeps its SCHEDULED date when the match is postponed: U20 and
    U18 vs Cobreloa (round 12) are 12-oct Events, but their `ficha_partido`
    rows — and the club's GPS — are 22-oct, the day it was played. A match with
    sheets is dated by them; one without (not played yet) keeps `starts_at`."""
    from collections import Counter, defaultdict

    from exams.models import ExamResult

    seen: dict[str, Counter] = defaultdict(Counter)
    for event_id, rec in ExamResult.objects.filter(
        template__slug="ficha_partido", event_id__in=list(event_ids),
    ).values_list("event_id", "recorded_at"):
        seen[str(event_id)][local_date(rec)] += 1
    return {e: c.most_common(1)[0][0] for e, c in seen.items()}


def _fixture_days(club, season, bracket, lo: date, hi: date) -> list[tuple[date, object]]:
    """The team's fixtures as (effective date, Event): played date when COMET
    has its sheets, else the scheduled one. Searched a fortnight wide, since a
    postponed match's Event sits on its original date."""
    from core.models import TeamSeason
    from events.models import Event

    team_ids = TeamSeason.objects.filter(season=season, bracket=bracket,
                                         team__club=club).values_list("team_id", flat=True)
    events = list(Event.objects.filter(
        club=club, event_type=Event.TYPE_MATCH,
        starts_at__date__range=(lo - timedelta(days=POSTPONE_DAYS), hi + timedelta(days=POSTPONE_DAYS)),
    ).filter(team_fixtures_q(bracket, team_ids)).select_related("opponent_team"))
    played = played_dates(e.id for e in events)
    out = []
    for e in events:
        d = played.get(str(e.id)) or local_date(e.starts_at)
        if lo <= d <= hi:
            out.append((d, e))
    return out


def team_fixtures_q(bracket, team_ids) -> Q:
    return Q(bracket=bracket) | Q(bracket__isnull=True, category_id__in=list(team_ids))


def _gps_kind(slug: str, data: dict) -> str | None:
    code = MATCH_CODES.get(data.get("origen_codigo") or "")
    if data.get("match_type") == "friendly" or code == FRIENDLY:
        return FRIENDLY
    if slug == "gps_partido" or code == OFFICIAL or data.get("match_type") == "official":
        return OFFICIAL
    return None


def team_match_days(club, season: int, bracket, start: date, end: date) -> dict[date, str]:
    """{date: "official" | "friendly"} for the team (bracket in `season`) in
    [start, end]. An official row beats a friendly one on the same day."""
    from exams.models import ExamResult

    lo, hi = start - timedelta(days=RECONCILE_DAYS), end + timedelta(days=RECONCILE_DAYS)
    rows_q = Q()
    for year in range(lo.year, hi.year + 1):
        rows_q |= season_rows(club.id, year, bracket)
    gps: dict[date, str] = {}
    for slug, rec, data in ExamResult.objects.filter(
        rows_q, template__slug__in=GPS_SLUGS,
        recorded_at__date__gte=lo, recorded_at__date__lte=hi,
    ).values_list("template__slug", "recorded_at", "result_data"):
        kind = _gps_kind(slug, data or {})
        if kind is None:
            continue
        d = timezone.localtime(rec).date()
        if gps.get(d) != OFFICIAL:
            gps[d] = kind

    out = {d: k for d, k in gps.items() if start <= d <= end}
    for d, _event in _fixture_days(club, season, bracket, lo, hi):
        near_gps = any(abs((d - g).days) <= RECONCILE_DAYS for g in gps)
        if not near_gps and start <= d <= end:
            out.setdefault(d, OFFICIAL)
    return out


_CODE = re.compile(r"^MD([+-]\d+)?$")


def club_day_labels(club, season: int, bracket, start: date, end: date) -> dict[date, str]:
    """{date: "MD-3" | "MD+1" | "MD"} as the club's GPS sheet codes each day
    (the day's most common code). Days the sheet marks `NO MD`, or has no
    rows for, are absent."""
    from collections import Counter, defaultdict

    from exams.models import ExamResult

    rows_q = Q()
    for year in range(start.year, end.year + 1):
        rows_q |= season_rows(club.id, year, bracket)
    seen: dict[date, Counter] = defaultdict(Counter)
    for rec, code in ExamResult.objects.filter(
        rows_q, template__slug__in=GPS_SLUGS,
        recorded_at__date__gte=start, recorded_at__date__lte=end,
    ).values_list("recorded_at", "result_data__origen_codigo"):
        code = (code or "").strip().upper()
        if code in MATCH_CODES:
            code = "MD"
        if _CODE.match(code):
            seen[timezone.localtime(rec).date()][code] += 1
    return {d: c.most_common(1)[0][0] for d, c in seen.items()}


def match_links(club, season: int, bracket, kinds: dict[date, str]) -> dict[date, dict]:
    """{date: {"event_id": str | None, "opponent": str | None}} for a team's
    match days, so a plan shows WHICH match each one is and links to it.

    The GPS knows best: the ingest links each `gps_partido` row to its match by
    the team and the opponent (`formativo_gps_ingest.EventMatcher`), and every
    row carries the opponent the club wrote. Fixtures fill the gaps — a future
    week, a match the sheet has not reached — within `RECONCILE_DAYS` (their
    dates drift). A friendly has no Event: it gets its opponent, no link."""
    from collections import Counter, defaultdict

    from exams.models import ExamResult

    dates = sorted(kinds)
    if not dates:
        return {}
    rows_q = Q()
    for year in range(dates[0].year, dates[-1].year + 1):
        rows_q |= season_rows(club.id, year, bracket)
    events: dict[date, Counter] = defaultdict(Counter)
    rivals: dict[date, Counter] = defaultdict(Counter)
    for rec, event_id, opponent in ExamResult.objects.filter(
        rows_q, template__slug__in=GPS_SLUGS, recorded_at__date__in=dates,
    ).values_list("recorded_at", "event_id", "result_data__opponent"):
        d = timezone.localtime(rec).date()
        if event_id:
            events[d][str(event_id)] += 1
        if opponent:
            rivals[d][str(opponent).strip()] += 1

    fixtures = _fixture_days(club, season, bracket,
                             dates[0] - timedelta(days=RECONCILE_DAYS),
                             dates[-1] + timedelta(days=RECONCILE_DAYS))
    by_id = {str(e.id): e for _, e in fixtures}

    def event_opponent(e) -> str | None:
        if e.opponent_team_id:
            return str(e.opponent_team)
        return (e.metadata or {}).get("opponent") or e.title or None

    out = {}
    for d in dates:
        event_id = events[d].most_common(1)[0][0] if events[d] else None
        # Only an OFFICIAL day borrows a fixture: next to a friendly the nearest
        # fixture is the official match, not the friendly.
        if event_id is None and kinds[d] == OFFICIAL:
            near = sorted(((abs((fd - d).days), e.starts_at, e) for fd, e in fixtures
                           if abs((fd - d).days) <= RECONCILE_DAYS),
                          key=lambda t: (t[0], t[1]))
            if near:
                event_id = str(near[0][2].id)
                by_id.setdefault(event_id, near[0][2])
        opponent = rivals[d].most_common(1)[0][0] if rivals[d] else None
        if opponent is None and event_id and event_id in by_id:
            opponent = event_opponent(by_id[event_id])
        out[d] = {"event_id": event_id, "opponent": opponent}
    return out
