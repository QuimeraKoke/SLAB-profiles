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


class RateMetricChoiceTests(SimpleTestCase):
    """Which GPS metrics may be compared at all.

    Both directions are confounded and both were measured on real data:

      * **Cumulative** metrics measure MINUTES, not ability. Jhon Cortés sat at
        the 13th percentile for total distance and the 17th for HSR purely
        because he came on for 10 minutes.
      * **Per-minute** rates favour short appearances — a 15-minute substitute
        out-runs a 90-minute starter on every rate — which is why peers are
        restricted to comparable durations. Vicente Ramírez went from the 30th
        to the 55th percentile for top speed once that band was applied.
    """

    def test_only_duration_safe_metrics_are_offered(self):
        from api.development import RATE_METRICS

        keys = {k for k, _, _ in RATE_METRICS}
        self.assertEqual(keys, {"max_vel", "mpm", "hsr_min", "sprint_dist_min"})

    def test_cumulative_metrics_are_excluded(self):
        from api.development import RATE_METRICS

        keys = {k for k, _, _ in RATE_METRICS}
        for banned in ("tot_dist", "hsr", "sprint_dist", "tot_dur", "player_load"):
            self.assertNotIn(banned, keys, f"{banned} depende de los minutos")

    def test_every_metric_has_a_label_and_a_unit(self):
        from api.development import RATE_METRICS

        for key, label, unit in RATE_METRICS:
            self.assertTrue(label and unit, key)

    def test_the_peer_band_is_a_ratio_not_an_absolute(self):
        # ±35% of the player's OWN typical duration: a fixed window of minutes
        # would be far too wide for a 15-minute cameo and too narrow for 98.
        from api.development import DURATION_BAND

        self.assertGreater(DURATION_BAND, 0)
        self.assertLess(DURATION_BAND, 1)

    def test_the_peer_floor_is_high_enough_to_mean_something(self):
        # Correct banding left Jhon Cortés with ONE comparable peer, where a
        # "100th percentile" would have been indefensible.
        from api.development import MIN_PEERS

        self.assertGreaterEqual(MIN_PEERS, 5)


class MedianTests(SimpleTestCase):
    def test_odd_and_even_lengths(self):
        from api.development import _median

        self.assertEqual(_median([3.0, 1.0, 2.0]), 2.0)
        self.assertEqual(_median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_single_value(self):
        from api.development import _median

        self.assertEqual(_median([7.5]), 7.5)


class NumCoercionTests(SimpleTestCase):
    def test_reads_numbers_and_rejects_everything_else(self):
        from api.development import _num

        self.assertEqual(_num({"a": 3}, "a"), 3.0)
        self.assertEqual(_num({"a": 2.5}, "a"), 2.5)
        for bad in ({}, {"a": None}, {"a": ""}, {"a": "12"}, None):
            self.assertIsNone(_num(bad, "a"), bad)

    def test_booleans_are_not_numbers(self):
        # `True` is an int in Python; a checkbox field must never be averaged.
        from api.development import _num

        self.assertIsNone(_num({"a": True}, "a"))
