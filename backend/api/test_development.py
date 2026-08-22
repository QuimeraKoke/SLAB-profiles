"""Development analysis — the rung arithmetic and the two anchors that fail.

These pin the decisions from PRD_EQUIPO_TEMPORADA.md §6.1 and §7, each of which
was arrived at by getting the measurement wrong first on real club data.
"""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from api.development import LABELS, Ladder, classify


class _B:
    def __init__(self, code, name, age, order):
        self.code, self.name, self.age, self.order = code, name, age, order


# The ANFP ladder: no Sub 17, no Sub 19.
LADDER = Ladder([
    _B("sub_11", "Sub 11", 11, 0),
    _B("sub_12", "Sub 12", 12, 1),
    _B("sub_13", "Sub 13", 13, 2),
    _B("sub_14", "Sub 14", 14, 3),
    _B("sub_15", "Sub 15", 15, 4),
    _B("sub_16", "Sub 16", 16, 5),
    _B("sub_18", "Sub 18", 18, 6),
    _B("sub_20", "Sub 20", 20, 7),
    _B("primera", "Primera", None, 8),
])


class NaturalBracketTests(SimpleTestCase):
    def test_a_cohort_lands_on_its_own_rung(self):
        self.assertEqual(LADDER.natural(2014, 2026).code, "sub_12")
        self.assertEqual(LADDER.natural(2011, 2026).code, "sub_15")

    def test_seventeen_year_olds_land_on_sub_18(self):
        # 96.1% of this club's 2009 cohort played Sub 18 in 2026, because there
        # is no Sub 17 competition to play in.
        self.assertEqual(LADDER.natural(2009, 2026).code, "sub_18")

    def test_nineteen_year_olds_land_on_sub_20(self):
        self.assertEqual(LADDER.natural(2007, 2026).code, "sub_20")

    def test_adults_land_on_senior(self):
        self.assertEqual(LADDER.natural(1995, 2026).code, "primera")

    def test_no_birth_year_cannot_be_judged(self):
        self.assertIsNone(LADDER.natural(None, 2026))


class RungArithmeticTests(SimpleTestCase):
    """Distance is measured in rungs, never in years."""

    def test_sub_16_to_sub_18_is_one_rung_not_two(self):
        # The single easiest mistake with this data. Ages differ by 2; the
        # ladder distance is 1, because Sub 17 doesn't exist.
        a = LADDER.natural(2010, 2026)      # Sub 16
        b = LADDER.natural(2009, 2026)      # Sub 18
        self.assertEqual(b.order - a.order, 1)
        self.assertEqual(b.age - a.age, 2)

    def test_a_2011_born_in_sub_18_is_two_rungs_up(self):
        nat = LADDER.natural(2011, 2026)                    # Sub 15
        played = next(b for b in LADDER.brackets if b.code == "sub_18")
        self.assertEqual(played.order - nat.order, 2)
        self.assertEqual(classify(2), "muy_por_encima")

    def test_the_yardstick_moves_with_the_season_not_the_player(self):
        # A 2007-born plays Sub 20 in both seasons and changes nothing, yet his
        # natural rung moves from Sub 18 to Sub 20 because the ladder skips 19.
        # Reading that as "stopped standing out" produced 16 false positives.
        sub20 = next(b for b in LADDER.brackets if b.code == "sub_20")
        self.assertEqual(sub20.order - LADDER.natural(2007, 2025).order, 1)
        self.assertEqual(sub20.order - LADDER.natural(2007, 2026).order, 0)


class ClassifyTests(SimpleTestCase):
    def test_thresholds(self):
        self.assertEqual(classify(3), "muy_por_encima")
        self.assertEqual(classify(2), "muy_por_encima")
        self.assertEqual(classify(1), "por_encima")
        self.assertEqual(classify(0), "su_cohorte")
        self.assertEqual(classify(-1), "por_debajo")

    def test_unjudgeable_is_its_own_state_not_zero(self):
        # "No sabemos" must never be rendered as "en su cohorte".
        self.assertEqual(classify(None), "sin_datos")
        self.assertNotEqual(classify(None), classify(0))

    def test_every_status_has_a_label(self):
        for rungs in (3, 2, 1, 0, -1, None):
            self.assertIn(classify(rungs), LABELS)

    def test_playing_down_is_a_state_of_its_own(self):
        # Belmar, born 2009-12-20, turned out for Sub 16 in 2026: playing DOWN
        # under the cutoff-date rule, which is neither a promotion nor an error.
        nat = LADDER.natural(2009, 2026)                    # Sub 18
        played = next(b for b in LADDER.brackets if b.code == "sub_16")
        self.assertEqual(classify(played.order - nat.order), "por_debajo")


class LadderOrderingTests(SimpleTestCase):
    def test_load_sorts_by_order_regardless_of_input_order(self):
        shuffled = Ladder([
            _B("primera", "Primera", None, 8),
            _B("sub_11", "Sub 11", 11, 0),
            _B("sub_15", "Sub 15", 15, 4),
        ])
        self.assertEqual([b.order for b in shuffled.brackets], [0, 4, 8])

    def test_natural_needs_ascending_order_to_be_correct(self):
        # `natural` returns the FIRST admitting bracket, so a ladder handed in
        # backwards would answer Primera for everyone. Guard the invariant.
        self.assertEqual(
            Ladder([
                _B("sub_20", "Sub 20", 20, 7),
                _B("sub_12", "Sub 12", 12, 1),
            ]).natural(2014, 2026).code,
            "sub_12",
        )

    def test_by_order_round_trips(self):
        for b in LADDER.brackets:
            self.assertEqual(LADDER.by_order(b.order).code, b.code)

    def test_empty_ladder_does_not_crash(self):
        self.assertIsNone(Ladder([]).natural(2014, 2026))
