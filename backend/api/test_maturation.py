"""Maturity offset and height velocity — pure math, no database.

These outputs decide who trains with whom, so the tests are mostly about the
REFUSALS: every case where the function must answer "I don't know" instead of a
number that looks precise.
"""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from api.maturation import (
    CONFIDENT_OFFSET, MAX_PLAUSIBLE_VELOCITY, MIN_VELOCITY_DAYS, VALID_AGE,
    decimal_age, height_velocity, maturity_offset, plausible_measurement,
)


class DecimalAgeTests(SimpleTestCase):
    def test_a_whole_year(self):
        self.assertAlmostEqual(
            decimal_age(date(2014, 1, 1), date(2025, 1, 1)), 11.0, places=1,
        )

    def test_a_half_year(self):
        self.assertAlmostEqual(
            decimal_age(date(2014, 1, 1), date(2025, 7, 2)), 11.5, places=1,
        )


class PlausibilityTests(SimpleTestCase):
    """The ratio check is what catches this club's real corruption."""

    def test_a_real_measurement_passes(self):
        # Mateo Martinez, 2025-07-14, from the clean row.
        self.assertTrue(plausible_measurement(
            talla=148.6, talla_sentado=78.5, peso=44.7,
        ))

    def test_a_senior_passes(self):
        self.assertTrue(plausible_measurement(
            talla=188.5, talla_sentado=97.0, peso=84.0,
        ))

    def test_the_real_shifted_row_is_rejected(self):
        # The corrupted row for the same boy on 2025-04-07: weight landed in
        # talla, height in talla_sentado, age in peso.
        self.assertFalse(plausible_measurement(
            talla=45.15, talla_sentado=146.9, peso=11.0,
        ))

    def test_a_swapped_pair_is_rejected_by_the_ratio(self):
        # Both values are individually plausible statures; only their RATIO
        # reveals the swap. A per-field range check would pass this.
        self.assertTrue(plausible_measurement(
            talla=148.6, talla_sentado=78.5, peso=44.7,
        ))
        self.assertFalse(plausible_measurement(
            talla=78.5, talla_sentado=148.6, peso=44.7,
        ))

    def test_missing_values_are_not_plausible(self):
        for kw in (
            dict(talla=None, talla_sentado=78.5, peso=44.7),
            dict(talla=148.6, talla_sentado=None, peso=44.7),
            dict(talla=148.6, talla_sentado=78.5, peso=None),
        ):
            self.assertFalse(plausible_measurement(**kw), kw)


class MaturityOffsetTests(SimpleTestCase):
    # A plausible 13-year-old boy mid-spurt.
    MID = dict(age_years=13.0, talla=160.0, talla_sentado=82.0, peso=48.0)

    def test_it_returns_years_from_phv(self):
        m = maturity_offset(**self.MID)
        self.assertIsNotNone(m)
        self.assertIsInstance(m.offset_years, float)
        # A 13-year-old should be within a few years of PHV either way — the
        # guard is against a wildly out-of-range estimate, not a precise value.
        self.assertGreater(m.offset_years, -5.0)
        self.assertLess(m.offset_years, 5.0)

    def test_aphv_is_age_minus_offset(self):
        m = maturity_offset(**self.MID)
        self.assertAlmostEqual(m.aphv_years, m.age_years - m.offset_years, places=2)

    def test_a_younger_boy_of_the_same_build_is_further_from_phv(self):
        younger = maturity_offset(**{**self.MID, "age_years": 10.0})
        older = maturity_offset(**{**self.MID, "age_years": 15.0})
        self.assertLess(younger.offset_years, older.offset_years)

    def test_stage_labels_follow_the_offset_sign(self):
        for age, expected in ((9.0, "pre_phv"), (17.0, "post_phv")):
            m = maturity_offset(**{**self.MID, "age_years": age})
            self.assertEqual(m.stage, expected, f"a los {age}")
            self.assertTrue(m.label)

    def test_confidence_narrows_far_from_phv(self):
        # Mirwald's error grows with distance from PHV, so far-out estimates are
        # flagged rather than presented as equals.
        near = maturity_offset(**{**self.MID, "age_years": 13.5})
        far = maturity_offset(**{**self.MID, "age_years": 8.5})
        if abs(far.offset_years) > CONFIDENT_OFFSET:
            self.assertFalse(far.confident)
        self.assertEqual(near.confident, abs(near.offset_years) <= CONFIDENT_OFFSET)

    def test_outside_the_fitted_age_range_it_abstains(self):
        # The equation happily returns a number for a 25-year-old. That number
        # is meaningless, which is exactly why it must not be returned.
        self.assertIsNone(maturity_offset(**{**self.MID, "age_years": 25.0}))
        self.assertIsNone(maturity_offset(**{**self.MID, "age_years": 5.0}))
        self.assertIsNotNone(maturity_offset(**{**self.MID, "age_years": VALID_AGE[0]}))

    def test_corrupted_measurements_abstain(self):
        self.assertIsNone(maturity_offset(
            age_years=11.0, talla=45.15, talla_sentado=146.9, peso=11.0,
        ))

    def test_a_sitting_height_above_stature_abstains(self):
        self.assertIsNone(maturity_offset(
            age_years=13.0, talla=150.0, talla_sentado=150.0, peso=45.0,
        ))

    def test_girls_use_a_different_equation(self):
        boy = maturity_offset(**self.MID)
        girl = maturity_offset(**self.MID, female=True)
        self.assertNotAlmostEqual(boy.offset_years, girl.offset_years, places=2)

    def test_girls_reach_phv_earlier_than_boys(self):
        # The one directional claim worth pinning: for identical anthropometry a
        # girl is further past PHV than a boy.
        boy = maturity_offset(**self.MID)
        girl = maturity_offset(**self.MID, female=True)
        self.assertGreater(girl.offset_years, boy.offset_years)


class HeightVelocityTests(SimpleTestCase):
    def test_a_year_of_growth(self):
        v = height_velocity([
            (date(2025, 1, 1), 150.0),
            (date(2026, 1, 1), 156.0),
        ])
        self.assertAlmostEqual(v.cm_per_year, 6.0, places=1)
        self.assertFalse(v.provisional)
        self.assertEqual(v.delta_cm, 6.0)

    def test_a_short_interval_is_provisional(self):
        v = height_velocity([
            (date(2025, 1, 1), 150.0),
            (date(2025, 8, 1), 153.0),
        ])
        self.assertIsNotNone(v)
        self.assertTrue(v.provisional)

    def test_too_short_an_interval_abstains(self):
        # Annualising a few weeks multiplies measurement error until the number
        # is pure noise.
        self.assertIsNone(height_velocity([
            (date(2025, 1, 1), 150.0),
            (date(2025, 2, 1), 151.0),
        ]))

    def test_it_uses_the_widest_interval_not_the_last_pair(self):
        # ISAK repeatability is millimetres, so consecutive pairs can show
        # nonsense. The full span is the stable signal.
        v = height_velocity([
            (date(2025, 1, 1), 150.0),
            (date(2025, 11, 1), 155.8),
            (date(2026, 1, 1), 156.0),
        ])
        self.assertEqual(v.from_talla, 150.0)
        self.assertEqual(v.to_talla, 156.0)

    def test_a_single_measurement_abstains(self):
        self.assertIsNone(height_velocity([(date(2025, 1, 1), 150.0)]))
        self.assertIsNone(height_velocity([]))

    def test_shrinking_abstains_instead_of_reporting_it(self):
        # A child does not lose stature. Reporting -2 cm/year would send someone
        # looking for a physiological explanation of a tape-measure error.
        self.assertIsNone(height_velocity([
            (date(2025, 1, 1), 156.0),
            (date(2026, 1, 1), 154.0),
        ]))

    def test_an_impossible_rate_abstains(self):
        self.assertIsNone(height_velocity([
            (date(2025, 1, 1), 130.0),
            (date(2026, 1, 1), 130.0 + MAX_PLAUSIBLE_VELOCITY + 5),
        ]))

    def test_corrupted_heights_are_filtered_before_the_maths(self):
        # The real shifted row (45.15) sits between two valid ones. Including it
        # would produce +100 cm/year; filtering leaves a sane 6.
        v = height_velocity([
            (date(2025, 4, 7), 45.15),
            (date(2025, 7, 14), 150.0),
            (date(2026, 7, 14), 156.0),
        ])
        self.assertIsNotNone(v)
        self.assertAlmostEqual(v.cm_per_year, 6.0, places=0)

    def test_the_interval_floor_is_at_least_a_season(self):
        self.assertGreaterEqual(MIN_VELOCITY_DAYS, 150)
