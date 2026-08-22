"""The cohort/bracket ladder — pure logic, no database.

Everything here exists because the ANFP ladder HAS GAPS: no Sub 17, no Sub 19.
The real progression is 11→12→13→14→15→16→18→20→Primera, so age arithmetic and
rung arithmetic are different things. Conflating them produced two wrong
analyses on 2026-08-20 (see PRD_EQUIPO_TEMPORADA.md §6.1), which is why the
ladder is pinned here rather than left to a comment.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from core.management.commands.backfill_cohorts import (
    BRACKETS, bracket_for_age, is_age_group, parse_age, parse_age_token,
)


class _B:
    """Stand-in for a Bracket row; the helpers only read age/code/order."""

    def __init__(self, code, name, age, order):
        self.code, self.name, self.age, self.order = code, name, age, order


LADDER = [_B(c, n, a, i) for i, (c, n, a) in enumerate(BRACKETS)]


class LadderShapeTests(SimpleTestCase):
    def test_there_is_no_sub_17_or_sub_19(self):
        ages = [a for _, _, a in BRACKETS if a is not None]
        self.assertNotIn(17, ages)
        self.assertNotIn(19, ages)

    def test_order_is_consecutive_across_the_age_gaps(self):
        # Sub 16 → Sub 18 must be ONE rung. This is the assertion that stops
        # someone "fixing" the ladder by indexing on age.
        by_age = {b.age: b for b in LADDER if b.age is not None}
        self.assertEqual(by_age[18].order - by_age[16].order, 1)
        self.assertEqual(by_age[20].order - by_age[18].order, 1)

    def test_order_is_dense_and_ascending(self):
        orders = [b.order for b in LADDER]
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(orders, list(range(len(LADDER))))

    def test_senior_is_the_last_rung_and_has_no_age(self):
        self.assertEqual(LADDER[-1].code, "primera")
        self.assertIsNone(LADDER[-1].age)


class BracketForAgeTests(SimpleTestCase):
    def test_exact_age_lands_on_its_own_bracket(self):
        self.assertEqual(bracket_for_age(12, LADDER).code, "sub_12")
        self.assertEqual(bracket_for_age(16, LADDER).code, "sub_16")

    def test_a_seventeen_year_old_plays_sub_18(self):
        # The gap in practice: the 2009 cohort had 96.1% of its 2026 appearances
        # in Sub 18 because Sub 17 does not exist.
        self.assertEqual(bracket_for_age(17, LADDER).code, "sub_18")

    def test_a_nineteen_year_old_plays_sub_20(self):
        self.assertEqual(bracket_for_age(19, LADDER).code, "sub_20")

    def test_above_the_ladder_is_senior(self):
        self.assertEqual(bracket_for_age(21, LADDER).code, "primera")
        self.assertEqual(bracket_for_age(34, LADDER).code, "primera")

    def test_below_the_ladder_lands_on_the_youngest(self):
        # A cohort younger than any bracket still has to resolve somewhere.
        self.assertEqual(bracket_for_age(8, LADDER).code, "sub_11")

    def test_the_2014_cohort_moves_one_rung_between_seasons(self):
        # The drift that started all of this: 2014-born are Sub 11 in 2025 and
        # Sub 12 in 2026, while SLAB kept calling them "SUB-11".
        self.assertEqual(bracket_for_age(2025 - 2014, LADDER).code, "sub_11")
        self.assertEqual(bracket_for_age(2026 - 2014, LADDER).code, "sub_12")

    def test_consecutive_seasons_never_skip_a_rung(self):
        # Any cohort, any season pair: at most one rung of movement. A test that
        # fails here means the ladder gained a hole.
        for birth in range(2006, 2016):
            for season in (2025, 2026, 2027):
                a = bracket_for_age(season - birth, LADDER)
                b = bracket_for_age(season + 1 - birth, LADDER)
                self.assertLessEqual(
                    b.order - a.order, 1,
                    f"cohorte {birth} salta más de un escalón en {season}",
                )


class ParseAgeTests(SimpleTestCase):
    def test_youth_labels_parse(self):
        self.assertEqual(parse_age("SUB-15"), 15)
        self.assertEqual(parse_age("SUB-9"), 9)

    def test_senior_and_blank_are_not_age_groups(self):
        for name in ("Primer Equipo", "", None):
            self.assertIsNone(parse_age(name))
            self.assertFalse(is_age_group(name or ""))

    def test_womens_squads_are_excluded(self):
        # COMET's feed for this tenant carries no femenino competitions, so
        # giving them a cohort would invent a mapping nothing can verify.
        for name in ("SUB-16 F - Femenino", "SUB-19 F - Femenino", "PEF - Femenino"):
            self.assertIsNone(parse_age(name), name)
            self.assertFalse(is_age_group(name), name)

    def test_is_age_group_agrees_with_parse_age(self):
        for name in ("SUB-11", "SUB-20", "Primer Equipo", "PEF - Femenino"):
            self.assertEqual(is_age_group(name), parse_age(name) is not None)


class ParseAgeTokenTests(SimpleTestCase):
    """Reading the age out of a federation competition name.

    Looser than `parse_age` on purpose — it has to cope with how COMET writes
    competitions — but the season must never be mistaken for an age group.
    """

    def test_reads_the_age_from_a_real_competition_name(self):
        self.assertEqual(parse_age_token("Sub 15 Nacional Clausura 2026"), 15)
        self.assertEqual(parse_age_token("Playoffs Sub 18 Nacional Apertura 2026"), 18)
        self.assertEqual(parse_age_token("Grupo Centro 1 - Sub 13"), 13)
        self.assertEqual(parse_age_token("Final Sub 11 Apertura"), 11)

    def test_the_season_is_not_read_as_an_age(self):
        # The trap: "Clausura 2026" must not parse as Sub 20 (or Sub 26).
        self.assertIsNone(parse_age_token("Primera División 2026"))
        self.assertIsNone(parse_age_token("Clausura 2026"))

    def test_senior_competitions_have_no_age(self):
        for name in ("Primera División 2026", "COPA CHILE COCA COLA ZERO AZUCAR 2026",
                     "GRUPO D", "Primera Fase", ""):
            self.assertIsNone(parse_age_token(name), name)

    def test_case_and_spacing_dont_matter(self):
        for text in ("SUB 16 Nacional", "sub16 apertura", "Sub  14 grupo"):
            self.assertIsNotNone(parse_age_token(text), text)


class EventBracketFallbackTests(SimpleTestCase):
    """A label can name an age the federation doesn't actually run.

    `SUB-17` is a real category in this club with 6 fixtures, and there is no
    Sub 17 competition — so an exact-age lookup left those events without a
    bracket. They belong to Sub 18, the same answer the rest of the system
    gives for a 17-year-old.
    """

    def test_sub_17_fixtures_belong_to_sub_18(self):
        self.assertEqual(bracket_for_age(parse_age("SUB-17"), LADDER).code, "sub_18")

    def test_a_label_below_the_ladder_has_no_competition(self):
        # Sub 9/10 are local tournaments; promoting them to Sub 11 would invent
        # a competition that doesn't exist, so the caller must skip them.
        min_age = min(b.age for b in LADDER if b.age is not None)
        for name in ("SUB-8", "SUB-9", "SUB-10"):
            self.assertLess(parse_age(name), min_age, name)

    def test_labels_on_the_ladder_map_to_themselves(self):
        for age in (11, 12, 13, 14, 15, 16, 18, 20):
            self.assertEqual(bracket_for_age(age, LADDER).age, age)
