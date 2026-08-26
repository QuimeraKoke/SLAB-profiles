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

    def test_an_undeclared_season_falls_back_to_the_cohort(self):
        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        self.assertEqual(team.season_label_parts(2099), ("Serie 2014", ""))

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

    def _label_queries(self, n_teams: int) -> int:
        """Queries needed to label `n_teams`, each with a declared season."""
        club = Club.objects.create(name=f"Club{n_teams}")
        for i in range(n_teams):
            t = Category.objects.create(
                club=club, name=f"T{i}", cohort_year=2000 + i)
            TeamSeason.objects.create(team=t, season=2026, bracket=self.sub12)

        qs = Category.objects.filter(club=club).prefetch_related(
            "team_seasons__bracket")
        with self.assertNumQueries(3) as ctx:
            [c.season_label(2026) for c in qs]
        return len(ctx)

    def test_labelling_does_not_cost_a_query_per_team(self):
        """The count must be CONSTANT, which is the property that matters.

        `.filter()` on a prefetched relation issues a fresh query, so without
        `season_bracket` reading the prefetch cache the category picker costs one
        query per team and the `prefetch_related` is dead weight. Asserting a
        fixed number would also pass if it were fixed at the wrong value, so this
        compares two sizes: three queries either way — categories, team_seasons,
        brackets — regardless of how many teams.
        """
        self.assertEqual(self._label_queries(3), self._label_queries(12))


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
