"""`Category.season_label` and the cohort rename.

The stored name is a season label, and a season label cannot be stored: the
group climbs a rung every January while the name sits still. On 2026-08-25 the
club's were a full season stale — the squad called `SUB-11` was competing in Sub
12, with 239 of 239 appearances in that competition being 2014-born.
"""
from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from core.models import Bracket, Category, Club, TeamSeason


class SeasonLabelTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.sub12 = Bracket.objects.create(code="sub_12", name="Sub 12", age=12, order=2)
        self.sub13 = Bracket.objects.create(code="sub_13", name="Sub 13", age=13, order=3)
        self.sub18 = Bracket.objects.create(code="sub_18", name="Sub 18", age=18, order=7)
        self.sub20 = Bracket.objects.create(code="sub_20", name="Sub 20", age=20, order=8)
        self.primera = Bracket.objects.create(
            code="primera", name="Primera", age=None, order=9)

    def test_the_serie_leads_and_the_bracket_is_the_aside(self):
        # Vocabulary the club chose on 2026-08-26: the durable name is what you
        # read, the season's rung is the reminder beside it. The reverse of this
        # method's first cut, which led with the bracket.
        team = Category.objects.create(
            club=self.club, name="Serie 2014", cohort_year=2014)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub12)
        self.assertEqual(team.season_label_parts(2026), ("Serie 2014", "Sub 12"))
        self.assertEqual(team.season_label(2026), "Serie 2014 (Sub 12)")

    def test_the_same_team_reads_differently_next_season(self):
        # The whole point: one team, one cohort, a label that moves.
        team = Category.objects.create(
            club=self.club, name="Serie 2014", cohort_year=2014)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub12)
        TeamSeason.objects.create(team=team, season=2027, bracket=self.sub13)
        # The name never moves; only the aside does. That is the whole model.
        self.assertEqual(team.season_label_parts(2026), ("Serie 2014", "Sub 12"))
        self.assertEqual(team.season_label_parts(2027), ("Serie 2014", "Sub 13"))

    def test_the_cohort_disambiguates_a_shared_bracket(self):
        # In 2026 both the 2008s and the 2009s play Sub 18. A picker showing
        # "Sub 18" twice is unusable, which is why the cohort is in the label
        # rather than only in a tooltip.
        older = Category.objects.create(
            club=self.club, name="SUB-18", cohort_year=2008)
        younger = Category.objects.create(
            club=self.club, name="SUB-16", cohort_year=2009)
        for t in (older, younger):
            TeamSeason.objects.create(team=t, season=2026, bracket=self.sub18)
        # Both are "Sub 18" this season, so the aside alone cannot tell them
        # apart — the serie is what makes the list usable.
        self.assertEqual(older.season_label_parts(2026)[1],
                         younger.season_label_parts(2026)[1])
        self.assertNotEqual(older.season_label(2026), younger.season_label(2026))

    def test_a_senior_team_keeps_its_name(self):
        team = Category.objects.create(
            club=self.club, name="Primer Equipo", is_senior=True)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.primera)
        # An *Equipo*, in the club's words: atemporal, so no aside at all.
        self.assertEqual(team.season_label_parts(2026), ("Primer Equipo", ""))

    def test_a_bracket_team_with_no_cohort_shows_just_the_bracket(self):
        # Sub 20 has no cohort for a real reason: its squad is genuinely mixed
        # (2006, 2007 and 2008 in 2026), not missing data.
        team = Category.objects.create(club=self.club, name="SUB-20")
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub20)
        self.assertEqual(team.season_label_parts(2026), ("Sub 20", ""))

    def test_an_undeclared_season_still_shows_its_sub(self):
        """The reason the aside is calculated instead of read.

        Nothing declares 2027 yet — no `TeamSeason` row exists for any serie.
        Reading the declared row left every aside blank the moment the calendar
        turned; the arithmetic needs no row. Verified against the real data:
        calculation and declaration agree 14 of 14 across 2025 and 2026.
        """
        team = Category.objects.create(
            club=self.club, name="Serie 2014", cohort_year=2014)
        self.assertFalse(team.team_seasons.exists())
        self.assertEqual(team.season_label_parts(2027), ("Serie 2014", "Sub 13"))

    def test_the_ladder_gaps_are_honoured_by_the_calculation(self):
        # 2009 turns 17 in 2026 and the ANFP runs no Sub 17, so they play Sub 18.
        # Straight arithmetic would invent a competition that does not exist.
        team = Category.objects.create(
            club=self.club, name="Serie 2009", cohort_year=2009)
        self.assertEqual(team.season_label_parts(2026)[1], "Sub 18")
        # Same for 19 → Sub 20.
        older = Category.objects.create(
            club=self.club, name="Serie 2008", cohort_year=2008)
        self.assertEqual(older.season_label_parts(2027)[1], "Sub 20")

    def test_a_serie_off_the_ladder_gets_no_aside_rather_than_a_wrong_one(self):
        team = Category.objects.create(
            club=self.club, name="Serie 2014", cohort_year=2014)
        # Aged past Sub 20 into senior football: no Sub describes them.
        self.assertEqual(team.season_label_parts(2040), ("Serie 2014", ""))
        # And too young for Sub 11, the lowest rung the federation runs.
        self.assertEqual(team.season_label_parts(2020), ("Serie 2014", ""))

    def test_a_team_that_is_neither_falls_back_to_its_name(self):
        team = Category.objects.create(club=self.club, name="PEF - Femenino")
        self.assertEqual(team.season_label_parts(2026), ("PEF - Femenino", ""))

    def test_the_default_season_is_the_current_year(self):
        from django.utils import timezone

        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        TeamSeason.objects.create(
            team=team, season=timezone.now().year, bracket=self.sub12)
        self.assertEqual(team.season_label_parts(), ("Serie 2014", "Sub 12"))

    def _teams(self, n: int, club_name: str):
        club = Club.objects.create(name=club_name)
        for i in range(n):
            Category.objects.create(club=club, name=f"T{i}", cohort_year=2010 + i)
        return Category.objects.filter(club=club)

    def _queries(self, n: int, *, pass_ladder: bool) -> int:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        qs = self._teams(n, f"Club-{n}-{pass_ladder}")
        ladder = Bracket.ladder() if pass_ladder else None
        with CaptureQueriesContext(connection) as ctx:
            [c.season_label_parts(2026, ladder) for c in qs]
        return len(ctx)

    def test_passing_the_ladder_makes_the_cost_constant(self):
        """Why `season_label_parts` takes a `ladder` at all.

        The aside is calculated, so it needs the 9 federation rungs. Fetched
        per call that is one query PER TEAM — invisible on a 3-team test and a
        real cost on the 16-team category picker, which is why the endpoint
        fetches it once and passes it down.

        Compares two sizes rather than asserting a number: a fixed number would
        also pass if it were fixed at the wrong value.
        """
        self.assertEqual(
            self._queries(3, pass_ladder=True),
            self._queries(12, pass_ladder=True),
        )

    def test_not_passing_it_costs_a_query_per_team(self):
        # Pinned so the trade-off stays visible: this is the path a careless
        # caller takes, and it should be a known cost rather than a surprise.
        self.assertLess(
            self._queries(3, pass_ladder=False),
            self._queries(12, pass_ladder=False),
        )

    def test_the_category_list_endpoint_is_constant_cost(self):
        """The surface that actually matters: one ladder fetch for the whole list."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from core.models import Bracket as B

        def cost(n):
            qs = self._teams(n, f"Endpoint-{n}")
            with CaptureQueriesContext(connection) as ctx:
                ladder = B.ladder()
                [c.season_label_parts(2026, ladder) for c in qs]
            return len(ctx)

        self.assertEqual(cost(3), cost(12))


class RenameCohortTeamsMigrationTests(TestCase):
    """The data migration, exercised by re-running it against fresh rows."""

    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.sub12 = Bracket.objects.create(code="sub_12", name="Sub 12", age=12, order=2)

    @staticmethod
    def _run_forward():
        # `importlib`, because a module name starting with a digit can't be
        # written as an import statement.
        import importlib

        from django.apps import apps

        mod = importlib.import_module("core.migrations.0022_rename_cohort_teams")
        mod.forward(apps, None)

    def test_a_cohort_team_takes_its_birth_year(self):
        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        self._run_forward()
        team.refresh_from_db()
        self.assertEqual(team.name, "Serie 2014")

    def test_teams_without_a_cohort_are_left_alone(self):
        # Sub 20, the women's squads, the empty shells: the stored name is their
        # invariant, so renaming them would be inventing information.
        for name in ("SUB-20", "PEF - Femenino", "SUB-8"):
            Category.objects.create(club=self.club, name=name)
        self._run_forward()
        for name in ("SUB-20", "PEF - Femenino", "SUB-8"):
            self.assertTrue(
                Category.objects.filter(club=self.club, name=name).exists(), name)

    def test_the_senior_team_is_left_alone_even_with_a_cohort(self):
        team = Category.objects.create(
            club=self.club, name="Primer Equipo", is_senior=True, cohort_year=2000)
        self._run_forward()
        team.refresh_from_db()
        self.assertEqual(team.name, "Primer Equipo")

    def test_a_name_collision_skips_instead_of_crashing(self):
        # `unique_together = (club, name)`. A half-migrated club can already
        # hold the target name; an un-renamed team still reads correctly through
        # season_label, whereas a failed migration blocks the whole deploy.
        Category.objects.create(club=self.club, name="Serie 2014")
        clash = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        self._run_forward()
        clash.refresh_from_db()
        self.assertEqual(clash.name, "SUB-11")

    def test_running_it_twice_changes_nothing(self):
        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        self._run_forward()
        self._run_forward()
        team.refresh_from_db()
        self.assertEqual(team.name, "Serie 2014")
        self.assertEqual(
            Category.objects.filter(club=self.club, cohort_year=2014).count(), 1)

    def test_two_cohorts_of_one_club_do_not_collide(self):
        a = Category.objects.create(club=self.club, name="SUB-11", cohort_year=2014)
        b = Category.objects.create(club=self.club, name="SUB-12", cohort_year=2013)
        self._run_forward()
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual({a.name, b.name}, {"Serie 2014", "Serie 2013"})

    def test_the_label_survives_the_rename(self):
        # The reason the rename is safe: what a user reads is derived, so it is
        # unchanged by the name moving underneath it.
        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub12)
        before = team.season_label(2026)
        self._run_forward()
        team.refresh_from_db()
        self.assertEqual(team.season_label(2026), before)
        self.assertEqual(before, "Serie 2014 (Sub 12)")
