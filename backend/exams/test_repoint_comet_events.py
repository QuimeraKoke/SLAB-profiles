"""`repoint_comet_events` — re-filing COMET matches under the team that played them.

The bug this heals, measured on Universidad de Chile 2026: of 215 synced youth
matches, ZERO were filed under the right team. Every one sat exactly one rung
too low, because the resolver matched the competition's "Sub NN" token against
the category NAME — and the names are a frozen 2025 snapshot. The squad still
called `SUB-11` is the 2014 cohort, and in 2026 that cohort competes in Sub 12.

So `SUB-12`'s calendar showed the matches `SUB-11`'s kids actually played.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Bracket, Category, Club, Department, TeamSeason
from events.models import Event
from exams.models import CometCompetitionLink, CometIntegration


class RepointCometEventsTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="Médico", slug="medico")
        self.integ = CometIntegration.objects.create(
            club=self.club, api_key="k", tenant="ANFP",
            comet_team_id=40017, organization_id=39972,
        )
        self.sub11 = Bracket.objects.create(code="sub_11", name="Sub 11", age=11, order=1)
        self.sub12 = Bracket.objects.create(code="sub_12", name="Sub 12", age=12, order=2)
        self.primera = Bracket.objects.create(
            code="primera", name="Primera", age=None, order=9)

        # The 2014 cohort, still LABELLED SUB-11, competing in Sub 12 in 2026.
        self.team2014 = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        TeamSeason.objects.create(team=self.team2014, season=2026, bracket=self.sub12)
        # The team the matches were wrongly filed under.
        self.team2013 = Category.objects.create(
            club=self.club, name="SUB-12", cohort_year=2013)
        # Atemporal: no cohort, no bracket arithmetic.
        self.senior = Category.objects.create(
            club=self.club, name="Primer Equipo", is_senior=True)

    # ------------------------------------------------------------------
    def _link(self, comp_id, name, *, category, auto=True, ignored=False):
        return CometCompetitionLink.objects.create(
            integration=self.integ, competition_id=comp_id, competition_name=name,
            category=category, auto_resolved=auto, ignored=ignored,
        )

    def _match(self, comp_id, comp_name, *, category, bracket, season=2026):
        return Event.objects.create(
            club=self.club, department=self.dept, category=category, bracket=bracket,
            event_type=Event.TYPE_MATCH, scope=Event.SCOPE_CATEGORY,
            title=f"vs Rival ({comp_name})",
            starts_at=timezone.make_aware(
                timezone.datetime(season, 6, 1, 15, 0)),
            metadata={
                "comet_match_id": 1000 + comp_id,
                "competition_id": comp_id,
                "competition": comp_name,
            },
        )

    # ------------------------------------------------------------------
    def test_youth_match_moves_one_rung_up_to_its_real_team(self):
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013)
        ev = self._match(1, "Sub 12 Apertura 2026",
                         category=self.team2013, bracket=self.sub12)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.category, self.team2014)

    def test_the_federations_bracket_is_left_alone(self):
        # `bracket` comes from the competition label, which was always right.
        # Only `category` — who SLAB thinks owns the fixture — was wrong.
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013)
        ev = self._match(1, "Sub 12 Apertura 2026",
                         category=self.team2013, bracket=self.sub12)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.bracket, self.sub12)

    def test_dry_run_is_the_default_and_writes_nothing(self):
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013)
        ev = self._match(1, "Sub 12 Apertura 2026",
                         category=self.team2013, bracket=self.sub12)

        call_command("repoint_comet_events", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.category, self.team2013)

    def test_senior_fixtures_are_untouched(self):
        # Primera carries no age token: it resolves through `is_senior`, which
        # never had the off-by-one. The senior squad is atemporal — the whole
        # cohort→bracket arithmetic simply does not apply to it.
        self._link(9, "Primera División 2026", category=self.senior)
        ev = self._match(9, "Primera División 2026",
                         category=self.senior, bracket=self.primera)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.category, self.senior)

    def test_a_humans_resolution_outranks_the_command(self):
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013, auto=False)
        ev = self._match(1, "Sub 12 Apertura 2026",
                         category=self.team2013, bracket=self.sub12)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.category, self.team2013)

    def test_a_parked_competition_stays_parked(self):
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013, ignored=True)
        ev = self._match(1, "Sub 12 Apertura 2026",
                         category=self.team2013, bracket=self.sub12)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.category, self.team2013)

    def test_a_bracket_with_no_squad_detaches_instead_of_padding_a_calendar(self):
        # Universidad de Chile's real "Sub 11" 2026: 17 played matches, not one
        # lineup, because that competition is the 2015 cohort's and SLAB has no
        # such squad. Leaving them on SUB-11 pads its calendar with matches its
        # kids never played. They are detached, not deleted — real ANFP matches
        # that attach if the club ever loads the 2015 roster.
        self._link(2, "Sub 11 Apertura 2026", category=self.team2014)
        ev = self._match(2, "Sub 11 Apertura 2026",
                         category=self.team2014, bracket=self.sub11)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertIsNone(ev.category)
        self.assertTrue(Event.objects.filter(pk=ev.pk).exists())

    def test_the_cached_link_is_refreshed_so_the_next_sync_does_not_undo_this(self):
        # The reason the sync's own fix could not heal history: a link is only
        # re-resolved while its category is NULL, so a wrongly-filed link keeps
        # its category forever and every new match inherits it.
        link = self._link(1, "Sub 12 Apertura 2026", category=self.team2013)
        self._match(1, "Sub 12 Apertura 2026",
                    category=self.team2013, bracket=self.sub12)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        link.refresh_from_db()
        self.assertEqual(link.category, self.team2014)

    def test_each_match_resolves_through_its_own_seasons_index(self):
        # The same team is a different bracket each year, so a 2025 match and a
        # 2026 match of one team cannot share an index.
        TeamSeason.objects.create(team=self.team2014, season=2025, bracket=self.sub11)
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013)
        self._link(3, "Sub 11 Apertura 2025", category=self.team2013)

        ev26 = self._match(1, "Sub 12 Apertura 2026",
                           category=self.team2013, bracket=self.sub12, season=2026)
        ev25 = self._match(3, "Sub 11 Apertura 2025",
                           category=self.team2013, bracket=self.sub11, season=2025)

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev26.refresh_from_db()
        ev25.refresh_from_db()
        # 2026: the 2014 cohort is Sub 12. 2025: the same cohort was Sub 11.
        self.assertEqual(ev26.category, self.team2014)
        self.assertEqual(ev25.category, self.team2014)

    def test_a_match_already_in_the_right_place_is_not_rewritten(self):
        self._link(1, "Sub 12 Apertura 2026", category=self.team2014)
        ev = self._match(1, "Sub 12 Apertura 2026",
                         category=self.team2014, bracket=self.sub12)
        before = ev.updated_at

        call_command("repoint_comet_events", "--commit", verbosity=0)

        ev.refresh_from_db()
        self.assertEqual(ev.category, self.team2014)
        self.assertEqual(ev.updated_at, before)

    def test_season_flag_limits_the_blast_radius(self):
        TeamSeason.objects.create(team=self.team2014, season=2025, bracket=self.sub11)
        self._link(1, "Sub 12 Apertura 2026", category=self.team2013)
        self._link(3, "Sub 11 Apertura 2025", category=self.team2013)
        ev26 = self._match(1, "Sub 12 Apertura 2026",
                           category=self.team2013, bracket=self.sub12, season=2026)
        ev25 = self._match(3, "Sub 11 Apertura 2025",
                           category=self.team2013, bracket=self.sub11, season=2025)

        call_command("repoint_comet_events", "--season", "2026", "--commit", verbosity=0)

        ev26.refresh_from_db()
        ev25.refresh_from_db()
        self.assertEqual(ev26.category, self.team2014)
        self.assertEqual(ev25.category, self.team2013)   # out of scope, untouched
