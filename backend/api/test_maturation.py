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
    decimal_age, height_velocity, maturity_offset, maturity_timing,
    plausible_measurement, suggest_team, team_profiles,
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


class MaturityTimingTests(SimpleTestCase):
    """Early / on-time / late, classified against same-age peers only.

    Mirwald's APHV is biased toward the child's current age. Measured on this
    club: the median APHV drifts +1.19 years between ages 10 and 17 while the
    spread within one age is ~0.55 — the bias is more than double the signal. So
    an APHV of 14.0 is EARLY for a 17-year-old (median 14.46) and LATE for a
    14-year-old (median 13.38). Any fixed threshold would mostly measure age.
    """

    # A realistic same-age reference: 14-year-olds, median ≈ 13.4.
    PEERS = [12.9, 13.1, 13.2, 13.3, 13.4, 13.4, 13.5, 13.6, 13.8, 14.0]

    def test_a_low_aphv_is_an_early_maturer(self):
        out = maturity_timing(12.2, self.PEERS)
        self.assertIsNotNone(out)
        self.assertEqual(out[0], "early")
        self.assertLess(out[1], -1.0)

    def test_a_high_aphv_is_a_late_maturer(self):
        self.assertEqual(maturity_timing(14.8, self.PEERS)[0], "late")

    def test_the_middle_is_on_time(self):
        self.assertEqual(maturity_timing(13.4, self.PEERS)[0], "on_time")

    def test_the_same_value_flips_meaning_with_the_reference(self):
        # The whole reason this takes a peer list instead of a constant. 14.0 is
        # LATE among 14-year-olds and EARLY among 17-year-olds.
        younger = [12.9, 13.1, 13.2, 13.3, 13.4, 13.4, 13.5, 13.6, 13.8, 14.0]
        older = [13.9, 14.1, 14.3, 14.4, 14.5, 14.5, 14.6, 14.7, 14.9, 15.1]
        self.assertEqual(maturity_timing(14.0, younger)[0], "late")
        self.assertEqual(maturity_timing(14.0, older)[0], "early")

    def test_too_few_peers_abstains(self):
        self.assertIsNone(maturity_timing(13.0, self.PEERS[:3]))
        self.assertIsNone(maturity_timing(13.0, []))

    def test_a_reference_with_no_spread_abstains(self):
        # Identical peers give sd=0; a z-score would divide by zero and any
        # answer would be invented.
        self.assertIsNone(maturity_timing(13.0, [13.4] * 10))

    def test_nones_in_the_reference_are_ignored(self):
        self.assertIsNotNone(maturity_timing(13.4, self.PEERS + [None] * 3))

    def test_every_classification_has_a_label(self):
        from api.maturation import TIMING_LABELS

        for value in (12.0, 13.4, 15.0):
            key, _ = maturity_timing(value, self.PEERS)
            self.assertIn(key, TIMING_LABELS)


class BandTests(SimpleTestCase):
    def test_the_bands_cover_the_line_without_gaps(self):
        from api.maturation import band_for

        for offset in (-9.0, -1.0001, -1.0, -0.5, 0.0, 0.5, 1.0, 9.0):
            key, label = band_for(offset)
            self.assertTrue(key and label, offset)

    def test_the_boundaries_land_where_documented(self):
        from api.maturation import band_for

        self.assertEqual(band_for(-2.0)[0], "pre_lejano")
        self.assertEqual(band_for(-0.5)[0], "pre_cercano")
        self.assertEqual(band_for(0.0)[0], "post_cercano")
        self.assertEqual(band_for(0.99)[0], "post_cercano")
        self.assertEqual(band_for(1.0)[0], "post_lejano")

    def test_bands_are_ordered_and_contiguous(self):
        from api.maturation import BANDS

        for (_, _, _, hi), (_, _, lo2, _) in zip(BANDS, BANDS[1:]):
            self.assertEqual(hi, lo2, "las bandas deben ser contiguas")


class SuggestTeamTests(SimpleTestCase):
    """Which squad a player's maturity resembles.

    Framed as resemblance, never as a recommendation: bio-banding in the
    literature is often the OPPOSITE of "promote the early maturer" — you group
    by maturity so the early developer meets equally mature opponents and has to
    build skill instead of leaning on size. What to do about it is a decision
    about a child, not about a median.
    """

    PROFILES = {
        "SUB-12": {"team": "SUB-12", "median_offset": -1.34, "players": 25, "female": False},
        "SUB-13": {"team": "SUB-13", "median_offset": 0.08, "players": 32, "female": False},
        "SUB-15": {"team": "SUB-15", "median_offset": 2.03, "players": 32, "female": False},
        "SUB-19 F": {"team": "SUB-19 F", "median_offset": 3.67, "players": 16, "female": True},
    }

    def _row(self, team, offset, female=False):
        return {"team": team, "offset_years": offset, "female": female}

    def test_a_far_ahead_player_is_matched_upward(self):
        # Santaella: SUB-13 with +2.05, which is SUB-15's median.
        s = suggest_team(self._row("SUB-13", 2.05), self.PROFILES)
        self.assertIsNotNone(s)
        self.assertEqual(s["team"], "SUB-15")
        self.assertEqual(s["direction"], "up")

    def test_a_lagging_player_is_matched_downward(self):
        s = suggest_team(self._row("SUB-13", -1.58), self.PROFILES)
        self.assertEqual(s["team"], "SUB-12")
        self.assertEqual(s["direction"], "down")

    def test_a_player_at_his_own_median_gets_nothing(self):
        self.assertIsNone(suggest_team(self._row("SUB-13", 0.08), self.PROFILES))

    def test_a_marginal_difference_gets_nothing(self):
        # Below the gain floor the two groups are interchangeable for him, and a
        # suggestion would be noise dressed as insight.
        s = suggest_team(self._row("SUB-13", 0.5), self.PROFILES)
        self.assertIsNone(s)

    def test_it_never_suggests_across_sexes(self):
        # The real bug this guard exists for: an unscoped nearest-median search
        # matched a boy in SUB-16 to the women's SUB-19 squad. The equations
        # differ and girls reach PHV ~2 years earlier, so the medians are not
        # comparable references.
        s = suggest_team(self._row("SUB-15", 3.6, female=False), self.PROFILES)
        self.assertNotEqual(s["team"] if s else None, "SUB-19 F")

    def test_a_girl_is_matched_only_to_womens_squads(self):
        s = suggest_team(self._row("SUB-15", 3.6, female=True), self.PROFILES)
        # Her own squad isn't in the profiles as female, so either she matches
        # the women's squad or nothing — never a men's one.
        if s is not None:
            self.assertEqual(s["team"], "SUB-19 F")

    def test_a_team_without_a_profile_gets_nothing(self):
        # Too few players to have a median means no reference to compare against.
        self.assertIsNone(suggest_team(self._row("SUB-17", 2.0), self.PROFILES))

    def test_the_payload_carries_both_medians(self):
        s = suggest_team(self._row("SUB-13", 2.05), self.PROFILES)
        self.assertEqual(s["own_median_offset"], 0.08)
        self.assertEqual(s["median_offset"], 2.03)
        self.assertGreater(s["gain_years"], 0)


class TeamProfileTests(SimpleTestCase):
    def test_small_squads_get_no_profile(self):
        rows = [
            {"team": "A", "offset_years": 1.0, "female": False} for _ in range(3)
        ]
        self.assertEqual(team_profiles(rows), {})

    def test_the_majority_sex_defines_the_squad(self):
        rows = (
            [{"team": "A", "offset_years": 1.0, "female": True} for _ in range(7)]
            + [{"team": "A", "offset_years": 1.0, "female": False}]
        )
        self.assertTrue(team_profiles(rows)["A"]["female"])

    def test_the_median_is_the_median(self):
        rows = [
            {"team": "A", "offset_years": float(i), "female": False}
            for i in range(9)
        ]
        self.assertEqual(team_profiles(rows)["A"]["median_offset"], 4.0)


class GrowthAgeScopeTests(SimpleTestCase):
    """Who the growth analysis is about: an age, never a team name.

    The first version excluded squads by NAME (`{"Primer Equipo", "Selección
    Nacional"}`), which was wrong twice over. Names get renamed — the cohort
    rename is a planned migration — so the exclusion would have silently stopped
    excluding. And it asked the wrong question: an 18-year-old promoted to the
    first team is still growing. Two real players (Jhon Cortés and Andrés
    Bolaño, both 18, still growing 1.5 and 1.1 cm/year) were being dropped
    because of the squad they had been promoted into.
    """

    def test_the_ceiling_covers_mirwalds_window(self):
        # The prefilter must not cut below what the equation itself accepts,
        # or players would vanish before `maturity_offset` could judge them.
        from api.maturation import MAX_GROWTH_AGE, VALID_AGE

        self.assertGreaterEqual(MAX_GROWTH_AGE, VALID_AGE[1])

    def test_no_team_name_is_hardcoded_anywhere(self):
        # The regression guard: a squad name in this module is a bug waiting for
        # the rename.
        import inspect

        from api import maturation

        src = inspect.getsource(maturation)
        for name in ("Primer Equipo", "Selección Nacional", "SUB-20", "SUB-18"):
            self.assertNotIn(
                f'"{name}"', src,
                f"'{name}' hardcodeado: la fase 2 lo renombra y esto se rompe en silencio",
            )

    def test_an_eighteen_year_old_is_still_a_growth_question(self):
        # Cortés's real numbers.
        from api.maturation import maturity_offset

        m = maturity_offset(
            age_years=18.0, talla=176.0, talla_sentado=92.0, peso=72.0,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.stage, "post_phv")

    def test_an_adult_is_not(self):
        from api.maturation import maturity_offset

        self.assertIsNone(maturity_offset(
            age_years=28.0, talla=180.0, talla_sentado=94.0, peso=78.0,
        ))
