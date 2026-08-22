"""Fixture relevance layers.

The behaviour worth protecting is that relevance comes from the BRACKET via
`TeamSeason`, never from `Event.category`. The club's category labels are a
frozen 2025 snapshot, so a calendar built on them shows each youth team the
wrong competition — the team labelled SUB-11 must see Sub 12 fixtures.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from api.fixtures import MIN_APPEARANCES, past_for_player, upcoming
from core.models import (
    Bracket, Category, Club, Department, Player, TeamSeason,
)
from events.models import Event, EventParticipant


class FixtureLayerTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.season = self.now.year
        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="T", slug="t")

        self.sub14 = Bracket.objects.create(
            code="sub_14", name="Sub 14", age=14, order=3)
        self.sub15 = Bracket.objects.create(
            code="sub_15", name="Sub 15", age=15, order=4)
        self.sub18 = Bracket.objects.create(
            code="sub_18", name="Sub 18", age=18, order=6)

        # The label says SUB-13; the team competes in Sub 14. That gap is the
        # whole point — it's the 2025 label on the 2012 cohort.
        self.team = Category.objects.create(
            club=self.club, name="SUB-13", cohort_year=self.season - 14)
        TeamSeason.objects.create(
            team=self.team, season=self.season, bracket=self.sub14)

        self.player = Player.objects.create(
            category=self.team, first_name="Kid", last_name="Uno",
            is_active=True, date_of_birth=None,
        )

    def _fixture(self, bracket, *, days: int):
        return Event.objects.create(
            club=self.club, department=self.dept, category=self.team,
            bracket=bracket, event_type=Event.TYPE_MATCH,
            scope=Event.SCOPE_CATEGORY, title=f"vs Rival {bracket.name}",
            starts_at=self.now + timedelta(days=days),
        )

    def _appearances(self, bracket, n):
        for i in range(n):
            ev = Event.objects.create(
                club=self.club, department=self.dept, category=self.team,
                bracket=bracket, event_type=Event.TYPE_MATCH,
                scope=Event.SCOPE_CATEGORY, title=f"pasado {i}",
                starts_at=self.now - timedelta(days=10 + i),
            )
            EventParticipant.objects.create(
                event=ev, player=self.player,
                attendance=EventParticipant.Attendance.ATTENDED,
            )

    # --- layer 1: entitlement -----------------------------------------
    def test_own_layer_follows_the_bracket_not_the_label(self):
        self._fixture(self.sub14, days=3)
        self._fixture(self.sub15, days=4)
        r = upcoming(club_id=self.club.id, team=self.team, now=self.now)
        self.assertEqual(r["own_brackets"], ["Sub 14"])
        self.assertEqual(r["counts"]["own"], 1)
        self.assertEqual(r["counts"]["context"], 1)

    def test_a_team_with_no_declared_season_has_no_own_fixtures(self):
        # Visibly unconfigured beats silently wrong: without a TeamSeason we
        # cannot know what the team entered, so nothing is claimed as theirs.
        TeamSeason.objects.all().delete()
        self._fixture(self.sub14, days=3)
        r = upcoming(club_id=self.club.id, team=self.team, now=self.now)
        self.assertEqual(r["counts"]["own"], 0)
        self.assertEqual(r["own_brackets"], [])

    # --- layer 2: evidence --------------------------------------------
    def test_playing_up_puts_that_competition_in_likely(self):
        self._appearances(self.sub15, MIN_APPEARANCES)
        self._fixture(self.sub14, days=3)
        self._fixture(self.sub15, days=4)
        r = upcoming(club_id=self.club.id, player=self.player, now=self.now)
        self.assertEqual(r["own_brackets"], ["Sub 14"])
        self.assertEqual(r["likely_brackets"], ["Sub 15"])
        self.assertEqual(r["counts"]["own"], 1)
        self.assertEqual(r["counts"]["likely"], 1)

    def test_below_the_appearance_floor_is_not_likely(self):
        # Two appearances is a guest spot, not a pattern.
        self._appearances(self.sub15, MIN_APPEARANCES - 1)
        self._fixture(self.sub15, days=4)
        r = upcoming(club_id=self.club.id, player=self.player, now=self.now)
        self.assertEqual(r["counts"]["likely"], 0)
        self.assertEqual(r["counts"]["context"], 1)

    def test_own_wins_over_likely_for_the_same_bracket(self):
        # Appearances in his OWN competition must not duplicate it into `likely`.
        self._appearances(self.sub14, MIN_APPEARANCES + 2)
        self._fixture(self.sub14, days=3)
        r = upcoming(club_id=self.club.id, player=self.player, now=self.now)
        self.assertEqual(r["counts"]["own"], 1)
        self.assertEqual(r["counts"]["likely"], 0)
        self.assertEqual(r["likely_brackets"], [])

    def test_playing_down_also_counts_as_likely(self):
        # It runs both ways at this club: 8 Primer Equipo players regularly turn
        # out for Sub 20. A "promotion only" rule would miss them.
        team18 = Category.objects.create(club=self.club, name="SUB-18")
        TeamSeason.objects.create(
            team=team18, season=self.season, bracket=self.sub18)
        senior = Player.objects.create(
            category=team18, first_name="Kid", last_name="Dos", is_active=True)
        for i in range(MIN_APPEARANCES):
            ev = self._fixture(self.sub15, days=-(20 + i))
            EventParticipant.objects.create(
                event=ev, player=senior,
                attendance=EventParticipant.Attendance.ATTENDED,
            )
        self._fixture(self.sub15, days=5)
        r = upcoming(club_id=self.club.id, player=senior, now=self.now)
        self.assertEqual(r["likely_brackets"], ["Sub 15"])

    # --- layer 3 and windowing ----------------------------------------
    def test_context_can_be_switched_off(self):
        self._fixture(self.sub18, days=3)
        r = upcoming(club_id=self.club.id, team=self.team, now=self.now,
                     include_context=False)
        self.assertEqual(r["counts"]["context"], 0)

    def test_the_horizon_is_respected(self):
        self._fixture(self.sub14, days=3)
        self._fixture(self.sub14, days=90)
        r = upcoming(club_id=self.club.id, team=self.team, days=45, now=self.now)
        self.assertEqual(r["counts"]["own"], 1)

    def test_past_fixtures_never_appear_in_upcoming(self):
        self._fixture(self.sub14, days=-3)
        r = upcoming(club_id=self.club.id, team=self.team, now=self.now)
        self.assertEqual(sum(r["counts"].values()), 0)

    def test_a_fixture_without_a_bracket_falls_to_context(self):
        # Women's fixtures have no bracket (COMET publishes no such
        # competitions), and must not be silently claimed by any team.
        Event.objects.create(
            club=self.club, department=self.dept, category=self.team,
            event_type=Event.TYPE_MATCH, scope=Event.SCOPE_CATEGORY,
            title="sin bracket", starts_at=self.now + timedelta(days=2),
        )
        r = upcoming(club_id=self.club.id, team=self.team, now=self.now)
        self.assertEqual(r["counts"]["own"], 0)
        self.assertEqual(r["counts"]["context"], 1)

    # --- past = participation, unfiltered -----------------------------
    def test_past_shows_appearances_in_any_competition(self):
        self._appearances(self.sub15, 2)      # above his own bracket
        self._appearances(self.sub14, 1)
        rows = past_for_player(self.player)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["bracket"] for r in rows}, {"Sub 14", "Sub 15"})

    def test_past_is_newest_first(self):
        self._appearances(self.sub14, 3)
        rows = past_for_player(self.player)
        dates = [r["starts_at"] for r in rows]
        self.assertEqual(dates, sorted(dates, reverse=True))
