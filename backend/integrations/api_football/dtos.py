"""Typed data-transfer objects for API-Football v3 responses.

We deliberately keep only the fields we use downstream. The full raw
payload is preserved on `Fixture.raw` so debugging / future fields cost
zero migration — drop a new field on the dataclass and read from `raw`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FixtureTeam:
    """One side of a fixture."""
    id: int
    name: str
    winner: bool | None  # None until the match is FT/AET/PEN.


@dataclass(frozen=True)
class FixtureScore:
    """Half-time and full-time scores. Extra-time / penalties are
    available on the raw payload if needed later."""
    halftime_home: int | None
    halftime_away: int | None
    fulltime_home: int | None
    fulltime_away: int | None


@dataclass(frozen=True)
class Fixture:
    """A single fixture as returned by GET /fixtures.

    `status_short` is the canonical 2-3 letter code (NS, 1H, HT, 2H, FT,
    AET, PEN, PST, CANC, ABD, AWD, WO, ...). The dashboard treats
    anything other than NS/TBD/PST/CANC as "completed" for stats-sync.
    """
    id: int
    date: datetime  # timezone-aware (API-Football returns ISO 8601 w/ offset).
    status_short: str
    status_long: str
    venue_name: str
    referee: str
    league_id: int
    league_name: str
    season: int
    round: str
    home: FixtureTeam
    away: FixtureTeam
    home_goals: int | None
    away_goals: int | None
    score: FixtureScore
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> "Fixture":
        """Parse one item from `response[]`. Raises `ValueError` if the
        item is missing the irreducible fields (id, date)."""
        f = item.get("fixture") or {}
        league = item.get("league") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        score = item.get("score") or {}
        ht = score.get("halftime") or {}
        ft = score.get("fulltime") or {}
        venue = f.get("venue") or {}
        status = f.get("status") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}

        fixture_id = f.get("id")
        date_str = f.get("date")
        if fixture_id is None or not date_str:
            raise ValueError(
                f"Fixture payload missing id/date: {item!r}"
            )

        # API-Football returns "2026-05-20T22:00:00+00:00". fromisoformat
        # handles that natively on 3.11+.
        date = datetime.fromisoformat(date_str)

        return cls(
            id=int(fixture_id),
            date=date,
            status_short=str(status.get("short") or ""),
            status_long=str(status.get("long") or ""),
            venue_name=str(venue.get("name") or ""),
            referee=str(f.get("referee") or ""),
            league_id=int(league.get("id") or 0),
            league_name=str(league.get("name") or ""),
            season=int(league.get("season") or 0),
            round=str(league.get("round") or ""),
            home=FixtureTeam(
                id=int(home.get("id") or 0),
                name=str(home.get("name") or ""),
                winner=home.get("winner"),
            ),
            away=FixtureTeam(
                id=int(away.get("id") or 0),
                name=str(away.get("name") or ""),
                winner=away.get("winner"),
            ),
            home_goals=goals.get("home"),
            away_goals=goals.get("away"),
            score=FixtureScore(
                halftime_home=ht.get("home"),
                halftime_away=ht.get("away"),
                fulltime_home=ft.get("home"),
                fulltime_away=ft.get("away"),
            ),
            raw=item,
        )
