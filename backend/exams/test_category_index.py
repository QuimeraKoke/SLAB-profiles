"""`_category_index` — which team a competition's matches get filed under.

This exists because of a trap that would have been silent. The original
implementation read the age out of the category NAME with `re.search(r"(\d{1,2})")`.
Rename a team to its cohort — "Serie 2014", which the cohort model is heading
towards — and that regex matches **20**, filing the 2014 kids' matches under
Sub 20. No error, no warning, just wrong.
"""
from __future__ import annotations

from django.test import TestCase

from core.models import Bracket, Category, Club, TeamSeason
from exams.services.comet_sync import _category_index


class CategoryIndexTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.sub12 = Bracket.objects.create(
            code="sub_12", name="Sub 12", age=12, order=1)
        self.sub18 = Bracket.objects.create(
            code="sub_18", name="Sub 18", age=18, order=6)

    def test_declared_season_beats_the_label(self):
        # The team is LABELLED SUB-11 but competes in Sub 12 — the 2025 label on
        # the 2014 cohort. The Sub 12 competition belongs to it.
        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub12)
        self.assertEqual(_category_index(self.club, season=2026)[12], team)

    def test_a_cohort_name_does_not_poison_the_mapping(self):
        # The regression this file exists for: "Serie 2014" → the old regex read
        # 20. With TeamSeason declared, the name is never consulted.
        team = Category.objects.create(
            club=self.club, name="Serie 2014", cohort_year=2014)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub12)
        idx = _category_index(self.club, season=2026)
        self.assertEqual(idx[12], team)
        self.assertNotIn(20, idx)

    def test_shared_bracket_picks_the_oldest_cohort(self):
        # Sub 18 2026 has three of this club's teams in it. Only one label can
        # be shown, so the oldest cohort wins — a display choice; who actually
        # plays is answered by Event.bracket.
        older = Category.objects.create(
            club=self.club, name="SUB-18", cohort_year=2008)
        younger = Category.objects.create(
            club=self.club, name="SUB-16", cohort_year=2009)
        undeclared = Category.objects.create(club=self.club, name="SUB-17")
        for t in (younger, undeclared, older):
            TeamSeason.objects.create(team=t, season=2026, bracket=self.sub18)
        self.assertEqual(_category_index(self.club, season=2026)[18], older)

    def test_a_team_without_a_cohort_loses_to_one_with(self):
        undeclared = Category.objects.create(club=self.club, name="SUB-17")
        declared = Category.objects.create(
            club=self.club, name="SUB-18", cohort_year=2008)
        for t in (undeclared, declared):
            TeamSeason.objects.create(team=t, season=2026, bracket=self.sub18)
        self.assertEqual(_category_index(self.club, season=2026)[18], declared)

    def test_a_bracket_nobody_competes_in_is_absent(self):
        # Sub 11 2026 belongs to the 2015 cohort, who aren't in SLAB. Absent is
        # the honest answer: the sync then reports the competition as unmapped
        # instead of filing it under the wrong team.
        team = Category.objects.create(
            club=self.club, name="SUB-11", cohort_year=2014)
        TeamSeason.objects.create(team=team, season=2026, bracket=self.sub12)
        self.assertNotIn(11, _category_index(self.club, season=2026))

    def test_the_same_age_maps_to_different_teams_across_seasons(self):
        a = Category.objects.create(club=self.club, name="A", cohort_year=2014)
        b = Category.objects.create(club=self.club, name="B", cohort_year=2013)
        TeamSeason.objects.create(team=a, season=2026, bracket=self.sub12)
        TeamSeason.objects.create(team=b, season=2025, bracket=self.sub12)
        self.assertEqual(_category_index(self.club, season=2026)[12], a)
        self.assertEqual(_category_index(self.club, season=2025)[12], b)

    def test_falls_back_to_the_label_when_nothing_is_declared(self):
        # A club that hasn't been backfilled must keep working exactly as before.
        team = Category.objects.create(club=self.club, name="SUB-15")
        idx = _category_index(self.club, season=2026)
        self.assertEqual(idx[15], team)

    def test_the_fallback_still_skips_womens_squads(self):
        Category.objects.create(club=self.club, name="SUB-16 F - Femenino")
        self.assertNotIn(16, _category_index(self.club, season=2026))
