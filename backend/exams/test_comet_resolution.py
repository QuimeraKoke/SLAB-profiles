"""Competition → bracket → team: storing the fact and computing the join.

The redesign this covers exists because the old shape stored the join result —
"which team plays this competition" — on the link. That is `bracket ⋈
TeamSeason(season)`: its left side never changes, its right side changes every
January. Caching it meant correcting either input left the stored answer stale
with nothing raising a hand, and on Universidad de Chile 2026 that came to all
215 synced youth matches sitting one rung too low.

The load-bearing test here is `test_correcting_the_season_re_points_with_no_repair`:
it is the property the old design could not have.
"""
from __future__ import annotations

from django.test import TestCase

from core.models import Bracket, Category, Club, TeamSeason
from exams.models import CometCompetitionLink, CometIntegration
from exams.services.comet_sync import _bracket_from_names, resolve_link_category


class BracketFromNamesTests(TestCase):
    def setUp(self):
        self.rungs = {
            code: Bracket.objects.create(code=code, name=name, age=age, order=order)
            for code, name, age, order in [
                ("sub_11", "Sub 11", 11, 1),
                ("sub_12", "Sub 12", 12, 2),
                ("sub_16", "Sub 16", 16, 6),
                ("sub_18", "Sub 18", 18, 7),
                ("primera", "Primera", None, 9),
            ]
        }

    def test_the_age_token_names_the_bracket(self):
        self.assertEqual(
            _bracket_from_names("Sub 12 Apertura 2026", ""), self.rungs["sub_12"])

    def test_the_age_can_live_in_the_parent_competition(self):
        # Cup and CONMEBOL ties: `name` is only the phase, the age is upstream.
        self.assertEqual(
            _bracket_from_names("Grupo 1", "Sub 12 Clausura 2026"),
            self.rungs["sub_12"],
        )

    def test_an_age_the_federation_does_not_run_climbs_to_the_next_rung(self):
        # There is no Sub 17 in the ANFP ladder, so a Sub 17 competition is
        # played in Sub 18. The gap is the single easiest thing to get wrong here.
        self.assertEqual(
            _bracket_from_names("Sub 17 Copa", ""), self.rungs["sub_18"])

    def test_no_age_token_means_senior(self):
        # Primera, Copa Chile, CONMEBOL — and "GRUPO D", which carries no age
        # at all. The senior rung is found by having no age, not by its name.
        for label in ("Primera División 2026", "GRUPO D", "Primera Fase"):
            self.assertEqual(
                _bracket_from_names(label, ""), self.rungs["primera"], label)

    def test_the_season_in_the_name_is_not_read_as_an_age(self):
        # "Clausura 2026" must not parse as Sub 20 — the word boundary around
        # the digits is what stops it, and it has bitten before.
        self.assertEqual(
            _bracket_from_names("Clausura 2026", ""), self.rungs["primera"])


class ResolveLinkCategoryTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.integ = CometIntegration.objects.create(
            club=self.club, api_key="k", tenant="ANFP",
            comet_team_id=40017, organization_id=39972,
        )
        self.sub12 = Bracket.objects.create(code="sub_12", name="Sub 12", age=12, order=2)
        self.sub13 = Bracket.objects.create(code="sub_13", name="Sub 13", age=13, order=3)
        self.sub18 = Bracket.objects.create(code="sub_18", name="Sub 18", age=18, order=7)
        self.primera = Bracket.objects.create(
            code="primera", name="Primera", age=None, order=9)

        # The 2014 cohort: Sub 12 in 2026, Sub 13 in 2027. Same team throughout.
        self.team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        TeamSeason.objects.create(team=self.team, season=2026, bracket=self.sub12)
        TeamSeason.objects.create(team=self.team, season=2027, bracket=self.sub13)
        self.senior_team = Category.objects.create(
            club=self.club, name="Primer Equipo", is_senior=True)

    def _link(self, bracket, **kw):
        return CometCompetitionLink.objects.create(
            integration=self.integ, competition_id=1,
            competition_name="X", bracket=bracket, **kw,
        )

    # ------------------------------------------------------------------
    def test_the_team_is_computed_from_the_declared_season(self):
        link = self._link(self.sub12)
        self.assertEqual(
            resolve_link_category(link, self.club, season=2026), self.team)

    def test_the_same_bracket_is_a_different_team_next_year(self):
        # Sub 12 in 2027 is the 2015 cohort, which this club has not declared.
        link = self._link(self.sub12)
        self.assertIsNone(resolve_link_category(link, self.club, season=2027))
        # And the 2014 cohort has moved up to Sub 13 without anything about any
        # competition changing.
        self.assertEqual(
            resolve_link_category(self._link_sub13(), self.club, season=2027),
            self.team,
        )

    def _link_sub13(self):
        return CometCompetitionLink.objects.create(
            integration=self.integ, competition_id=2,
            competition_name="Sub 13 Apertura 2027", bracket=self.sub13,
        )

    def _link_sub18_plain(self):
        return CometCompetitionLink.objects.create(
            integration=self.integ, competition_id=3,
            competition_name="Sub 18 Apertura 2026", bracket=self.sub18,
        )

    def test_correcting_the_season_re_points_with_no_repair(self):
        """The property the old design could not have.

        Under the cached shape, fixing `TeamSeason` left every stored answer
        untouched — which is exactly why `repoint_comet_events` had to be
        written. Here the correction lands immediately, because there is no
        stored answer to go stale.
        """
        link = self._link(self.sub12)
        other = Category.objects.create(
            club=self.club, name="SUB-12", cohort_year=2013)
        self.assertEqual(
            resolve_link_category(link, self.club, season=2026), self.team)

        # The club says the 2013 cohort is the one in Sub 12 2026.
        TeamSeason.objects.filter(team=self.team, season=2026).delete()
        TeamSeason.objects.create(team=other, season=2026, bracket=self.sub12)

        self.assertEqual(
            resolve_link_category(link, self.club, season=2026), other)

    def test_a_human_override_wins_over_the_join(self):
        # Sub 18 2026 holds more than one of the club's teams, so the join
        # genuinely cannot decide and should not pretend to.
        pinned = Category.objects.create(
            club=self.club, name="SUB-16", cohort_year=2009)
        derived = Category.objects.create(
            club=self.club, name="SUB-18", cohort_year=2008)
        TeamSeason.objects.create(team=derived, season=2026, bracket=self.sub18)
        link = self._link(self.sub18, category_override=pinned)
        # Without the pin the join would answer `derived` (oldest cohort wins).
        self.assertEqual(
            resolve_link_category(self._link_sub18_plain(), self.club, season=2026),
            derived,
        )
        self.assertEqual(
            resolve_link_category(link, self.club, season=2026), pinned)

    def test_an_override_survives_a_season_the_join_cannot_answer(self):
        link = self._link(self.sub12, category_override=self.senior_team)
        # 2099 has no TeamSeason at all; the pin still answers.
        self.assertEqual(
            resolve_link_category(link, self.club, season=2099), self.senior_team)

    def test_a_senior_bracket_resolves_through_the_flag(self):
        link = self._link(self.primera)
        self.assertEqual(
            resolve_link_category(link, self.club, season=2026), self.senior_team)

    def test_an_unresolved_bracket_answers_nothing_rather_than_guessing(self):
        link = self._link(None)
        self.assertIsNone(resolve_link_category(link, self.club, season=2026))

    def test_a_cohort_rename_cannot_change_the_answer(self):
        # The trap the old resolver had: it read digits out of the team NAME, so
        # renaming to "Serie 2014" made it read 20 and file the matches under
        # Sub 20. Nothing here consults the name.
        link = self._link(self.sub12)
        self.team.name = "Serie 2014"
        self.team.save(update_fields=["name"])
        self.assertEqual(
            resolve_link_category(link, self.club, season=2026), self.team)


class BracketSeniorTests(TestCase):
    def test_is_senior_is_derived_not_stored(self):
        # Deliberately a property: `age is None` already IS the signal, and a
        # stored flag could contradict it. Replaces a `code == "primera"` test,
        # which was a hardcoded name.
        youth = Bracket.objects.create(code="sub_12", name="Sub 12", age=12, order=2)
        senior = Bracket.objects.create(
            code="primera", name="Primera", age=None, order=9)
        self.assertFalse(youth.is_senior)
        self.assertTrue(senior.is_senior)
        self.assertEqual(Bracket.senior(), senior)

    def test_the_top_rung_wins_when_several_have_no_age(self):
        # Copa and Primera are both senior; `order` decides which is "the" one.
        Bracket.objects.create(code="copa", name="Copa Chile", age=None, order=8)
        primera = Bracket.objects.create(
            code="primera", name="Primera", age=None, order=9)
        self.assertEqual(Bracket.senior(), primera)
