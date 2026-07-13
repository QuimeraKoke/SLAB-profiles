"""Formula-engine tests with focus on the namespace + snapshot extensions.

Existing behavior (numeric arithmetic, coalesce, ternary) is exercised by
existing seed flows; this file targets the new surface area:
  * `[player.X]` and `[<slug>.Y]` dot syntax
  * String equality on `player.sex`
  * inputs_snapshot capture
  * Player profile write-back signal (Step 2)
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player

from .calculations import (
    FormulaError,
    Namespace,
    compute_result_data,
    evaluate_formula,
    extract_namespace_refs,
)
from .models import ExamResult, ExamTemplate, TemplateField


def _ns(name, values):
    return Namespace(name, values, tracker={})


class FormulaEngineDotSyntaxTests(TestCase):
    def test_bracket_dot_normalizes_to_attribute_access(self):
        # Numeric attribute access still works.
        ns = _ns("player", {"current_weight_kg": 80.0, "current_height_cm": 178.0})
        result = evaluate_formula(
            "[player.current_weight_kg] / (([player.current_height_cm] / 100) ** 2)",
            {"player": ns},
        )
        self.assertAlmostEqual(result, 25.249, places=2)

    def test_string_equality_on_player_sex(self):
        ns_m = _ns("player", {"sex": "M"})
        ns_f = _ns("player", {"sex": "F"})
        formula = '1.0 if [player.sex] == "M" else 0.5'
        self.assertEqual(evaluate_formula(formula, {"player": ns_m}), 1.0)
        self.assertEqual(evaluate_formula(formula, {"player": ns_f}), 0.5)

    def test_namespace_used_as_bare_name_raises(self):
        ns = _ns("player", {"sex": "M"})
        with self.assertRaisesRegex(FormulaError, "namespace"):
            evaluate_formula("[player] + 1", {"player": ns})

    def test_unknown_namespace_raises(self):
        with self.assertRaisesRegex(FormulaError, "Unknown namespace"):
            evaluate_formula("[player.sex]", {})

    def test_missing_attribute_raises(self):
        ns = _ns("player", {"sex": "M"})
        with self.assertRaisesRegex(FormulaError, "no value"):
            evaluate_formula("[player.current_weight_kg]", {"player": ns})

    def test_deep_attribute_chain_rejected(self):
        # `a.b.c` parses as Attribute(Attribute(Name(a), b), c) — not allowed.
        with self.assertRaises(FormulaError):
            evaluate_formula("[player.foo.bar]", {})

    def test_extract_namespace_refs(self):
        formula = "[player.sex] + [pentacompartimental.peso] / [peso]"
        self.assertEqual(
            extract_namespace_refs(formula),
            {"player", "pentacompartimental"},
        )

    def test_namespace_lookup_records_snapshot(self):
        tracker = {}
        ns = Namespace("player", {"sex": "M", "current_weight_kg": 80.0}, tracker)
        ns.lookup("sex")
        ns.lookup("current_weight_kg")
        ns.lookup("missing")  # no-op, doesn't pollute snapshot
        self.assertEqual(tracker, {"player.sex": "M", "player.current_weight_kg": 80.0})


class ComputeResultDataTests(TestCase):
    """End-to-end test of `compute_result_data` including snapshot capture."""

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
            sex="M",
            current_weight_kg=Decimal("80.00"),
            current_height_cm=Decimal("178.0"),
        )

    def test_imc_from_player_attributes(self):
        template = ExamTemplate.objects.create(
            name="BMI calc", slug="bmi", department=self.dept,
            config_schema={"fields": [
                {"key": "imc", "type": "calculated",
                 "formula": "[player.current_weight_kg] / (([player.current_height_cm] / 100) ** 2)"},
            ]},
        )
        template.applicable_categories.add(self.cat)
        out, snapshot = compute_result_data(template, {}, player=self.player)
        self.assertAlmostEqual(out["imc"], 25.249, places=2)
        # Snapshot captures the values used.
        self.assertEqual(snapshot["player.current_weight_kg"], 80.0)
        self.assertEqual(snapshot["player.current_height_cm"], 178.0)

    def test_sex_branched_formula(self):
        template = ExamTemplate.objects.create(
            name="Sex coef", slug="sexcoef", department=self.dept,
            config_schema={"fields": [
                {"key": "coef", "type": "calculated",
                 "formula": '1.0 if [player.sex] == "M" else 0.5'},
            ]},
        )
        out, snapshot = compute_result_data(template, {}, player=self.player)
        self.assertEqual(out["coef"], 1.0)
        self.assertEqual(snapshot["player.sex"], "M")

    def test_cross_template_reference_uses_latest(self):
        # Source template the formula will reference.
        ck_template = ExamTemplate.objects.create(
            name="CK", slug="ck", department=self.dept,
            config_schema={"fields": [{"key": "valor", "type": "number"}]},
        )
        ExamResult.objects.create(
            player=self.player, template=ck_template,
            recorded_at=timezone.now() - timedelta(days=2),
            result_data={"valor": 1000},
        )
        ExamResult.objects.create(
            player=self.player, template=ck_template,
            recorded_at=timezone.now(),
            result_data={"valor": 420},  # newest — should win
        )
        # Consumer template referencing CK by slug.
        target = ExamTemplate.objects.create(
            name="CK ratio", slug="ckratio", department=self.dept,
            config_schema={"fields": [
                {"key": "ratio", "type": "calculated",
                 "formula": "[ck.valor] / [player.current_weight_kg]"},
            ]},
        )
        out, snapshot = compute_result_data(target, {}, player=self.player)
        self.assertAlmostEqual(out["ratio"], 5.25, places=2)  # 420 / 80
        self.assertEqual(snapshot["ck.valor"], 420)
        self.assertEqual(snapshot["player.current_weight_kg"], 80.0)

    def test_missing_cross_template_data_yields_null(self):
        target = ExamTemplate.objects.create(
            name="CK ratio", slug="ckratio2", department=self.dept,
            config_schema={"fields": [
                {"key": "ratio", "type": "calculated",
                 "formula": "[ck.valor] / [player.current_weight_kg]"},
            ]},
        )
        # No ck template / no readings → formula fails → field stored as None.
        out, snapshot = compute_result_data(target, {}, player=self.player)
        self.assertIsNone(out["ratio"])
        # Snapshot captures only what was successfully read (player still resolved).
        self.assertNotIn("ck.valor", snapshot)


class TemplateFieldKeyValidationTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="X", slug="x")
        self.template = ExamTemplate.objects.create(
            name="T", slug="t", department=self.dept,
        )

    def test_dot_in_key_rejected(self):
        from django.core.exceptions import ValidationError
        f = TemplateField(template=self.template, key="bad.key", label="Bad", type="number")
        with self.assertRaises(ValidationError):
            f.full_clean()

    def test_player_key_rejected(self):
        from django.core.exceptions import ValidationError
        f = TemplateField(template=self.template, key="player", label="Bad", type="number")
        with self.assertRaises(ValidationError):
            f.full_clean()

    def test_normal_key_accepted(self):
        f = TemplateField(template=self.template, key="peso", label="Peso", type="number")
        f.full_clean()  # should not raise


class TemplateSlugValidationTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="X", slug="x")

    def test_reserved_slug_rejected(self):
        from django.core.exceptions import ValidationError
        t = ExamTemplate(name="Bad", slug="player", department=self.dept)
        with self.assertRaises(ValidationError):
            t.full_clean()

    def test_auto_derive_slug_from_name(self):
        from django.core.exceptions import ValidationError
        t = ExamTemplate(name="Pentacompartimental", department=self.dept)
        try:
            t.full_clean()
        except ValidationError:
            pass  # may fail on other fields; we only care that slug got set
        self.assertEqual(t.slug, "pentacompartimental")

    def test_slug_uniqueness_per_club(self):
        from django.core.exceptions import ValidationError
        ExamTemplate.objects.create(name="A", slug="myslug", department=self.dept)
        t2 = ExamTemplate(name="B", slug="myslug", department=self.dept)
        with self.assertRaisesRegex(ValidationError, "already used"):
            t2.full_clean()


class PlayerWriteBackTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Nut", slug="nut")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
        )
        # Template whose `peso` field writes back to the player.
        self.template = ExamTemplate.objects.create(
            name="Anthro", slug="anthro", department=self.dept,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "writes_to_player_field": "current_weight_kg"},
                {"key": "talla", "type": "number", "writes_to_player_field": "current_height_cm"},
            ]},
        )
        self.template.applicable_categories.add(self.cat)

    def test_writeback_updates_player_on_new_result(self):
        ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 78.5, "talla": 178.0},
        )
        self.player.refresh_from_db()
        self.assertEqual(self.player.current_weight_kg, Decimal("78.50"))
        self.assertEqual(self.player.current_height_cm, Decimal("178.0"))

    def test_back_dated_result_does_not_overwrite_newer(self):
        # Newer reading first.
        ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 80.0},
        )
        self.player.refresh_from_db()
        self.assertEqual(self.player.current_weight_kg, Decimal("80.00"))
        # Then a back-dated older reading — should NOT clobber.
        ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now() - timedelta(days=30),
            result_data={"peso": 70.0},
        )
        self.player.refresh_from_db()
        self.assertEqual(self.player.current_weight_kg, Decimal("80.00"))


# =============================================================================
# Episodic templates (Episode lifecycle + Player.status derivation)
# =============================================================================


from .models import Episode  # noqa: E402
from .episode_lifecycle import (  # noqa: E402
    recompute_player_status,
    refresh_episode_from_results,
    resolve_episode,
)


class EpisodeLifecycleTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
        )
        self.template = ExamTemplate.objects.create(
            name="Lesiones", slug="lesiones", department=self.dept,
            config_schema={"fields": [
                {"key": "type", "type": "categorical",
                 "options": ["Muscular", "Ligamentosa"]},
                {"key": "body_part", "type": "categorical",
                 "options": ["Muslo der.", "Pantorrilla izq."]},
                {"key": "stage", "type": "categorical",
                 "options": ["injured", "recovery", "reintegration", "closed"]},
            ]},
            is_episodic=True,
            episode_config={
                "stage_field": "stage",
                "open_stages": ["injured", "recovery", "reintegration"],
                "closed_stage": "closed",
                "title_template": "{type} — {body_part}",
            },
        )
        self.template.applicable_categories.add(self.cat)

    def _add_result(self, episode, stage, **extra):
        return ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(), episode=episode,
            result_data={
                "type": "Muscular", "body_part": "Muslo der.",
                "stage": stage, **extra,
            },
        )

    def test_new_diagnosis_creates_open_episode_and_sets_player_status(self):
        ep = resolve_episode(
            template=self.template, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self._add_result(ep, "injured")
        ep.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(ep.status, "open")
        self.assertEqual(ep.stage, "injured")
        self.assertEqual(ep.title, "Muscular — Muslo der.")
        self.assertEqual(self.player.status, "injured")

    def test_progressing_stages_updates_player_status(self):
        ep = resolve_episode(
            template=self.template, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self._add_result(ep, "injured")
        self._add_result(ep, "recovery")
        self.player.refresh_from_db()
        self.assertEqual(self.player.status, "recovery")
        self._add_result(ep, "reintegration")
        self.player.refresh_from_db()
        self.assertEqual(self.player.status, "reintegration")

    def test_closing_resets_player_to_available(self):
        ep = resolve_episode(
            template=self.template, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self._add_result(ep, "injured")
        self._add_result(ep, "closed")
        ep.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(ep.status, "closed")
        self.assertIsNotNone(ep.ended_at)
        self.assertEqual(self.player.status, "available")

    def test_multiple_concurrent_episodes_worst_stage_wins(self):
        # Episode A — recovery
        ep_a = resolve_episode(
            template=self.template, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self._add_result(ep_a, "injured")
        self._add_result(ep_a, "recovery")
        # Episode B — fresh diagnosis (injured) → worse than recovery
        ep_b = resolve_episode(
            template=self.template, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self._add_result(ep_b, "injured", body_part="Pantorrilla izq.")
        self.player.refresh_from_db()
        self.assertEqual(self.player.status, "injured")
        # Closing the worse one drops back to recovery (the other still open).
        self._add_result(ep_b, "closed", body_part="Pantorrilla izq.")
        self.player.refresh_from_db()
        self.assertEqual(self.player.status, "recovery")

    def test_resolve_episode_rejects_closed_episode(self):
        ep = resolve_episode(
            template=self.template, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self._add_result(ep, "closed")
        ep.refresh_from_db()
        self.assertEqual(ep.status, "closed")
        from ninja.errors import HttpError
        with self.assertRaises(HttpError):
            resolve_episode(
                template=self.template, player=self.player,
                episode_id=ep.id, recorded_at=timezone.now(), user=None,
            )

    def test_resolve_episode_validates_player_template_match(self):
        # Episode owned by another player.
        other = Player.objects.create(category=self.cat, first_name="X", last_name="Y")
        ep = resolve_episode(
            template=self.template, player=other,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        from ninja.errors import HttpError
        with self.assertRaises(HttpError):
            resolve_episode(
                template=self.template, player=self.player,
                episode_id=ep.id, recorded_at=timezone.now(), user=None,
            )

    def test_non_episodic_template_returns_none(self):
        plain = ExamTemplate.objects.create(
            name="Plain", slug="plain", department=self.dept,
            config_schema={"fields": [{"key": "x", "type": "number"}]},
        )
        result = resolve_episode(
            template=plain, player=self.player,
            episode_id=None, recorded_at=timezone.now(), user=None,
        )
        self.assertIsNone(result)


class EpisodeConfigValidationTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="X", slug="x")

    def test_episodic_without_config_rejected(self):
        from django.core.exceptions import ValidationError
        t = ExamTemplate(
            name="Bad", slug="bad", department=self.dept,
            is_episodic=True,
            config_schema={"fields": [{"key": "stage", "type": "categorical", "options": ["a"]}]},
        )
        with self.assertRaises(ValidationError):
            t.full_clean()

    def test_episode_config_closed_in_open_stages_rejected(self):
        from django.core.exceptions import ValidationError
        t = ExamTemplate(
            name="Bad", slug="bad", department=self.dept,
            is_episodic=True,
            episode_config={
                "stage_field": "stage",
                "open_stages": ["injured", "closed"],
                "closed_stage": "closed",
            },
            config_schema={"fields": [{"key": "stage", "type": "categorical", "options": ["a"]}]},
        )
        with self.assertRaisesRegex(ValidationError, "must NOT be in"):
            t.full_clean()

    def test_episode_config_unknown_stage_field_rejected(self):
        from django.core.exceptions import ValidationError
        t = ExamTemplate(
            name="Bad", slug="bad", department=self.dept,
            is_episodic=True,
            episode_config={
                "stage_field": "missing",
                "open_stages": ["a"],
                "closed_stage": "closed",
            },
            config_schema={"fields": [{"key": "real", "type": "categorical", "options": ["a"]}]},
        )
        with self.assertRaisesRegex(ValidationError, "not found in template fields"):
            t.full_clean()


from django.test import SimpleTestCase  # noqa: E402
from . import gps_session as G  # noqa: E402


class GpsSessionParsingTests(SimpleTestCase):
    """Pure parsing helpers for the one-time per-session GPS backfill."""

    def test_parse_days_java_tostring(self):
        # Locale-independent parse of "Mon Mar 09 23:01:33 UTC 2026".
        self.assertEqual(G.parse_days("Mon Mar 09 23:01:33 UTC 2026"), date(2026, 3, 9))
        self.assertEqual(G.parse_days("Sat Jan 31 20:00:00 UTC 2026"), date(2026, 1, 31))

    def test_parse_days_garbage_is_none(self):
        self.assertIsNone(G.parse_days("not a date"))
        self.assertIsNone(G.parse_days(None))

    def test_extract_session_date_full(self):
        self.assertEqual(G.extract_session_date("Sesión 04-01-26"), date(2026, 1, 4))
        self.assertEqual(G.extract_session_date("Reintegro 30-03-26"), date(2026, 3, 30))

    def test_extract_session_date_defaults_year(self):
        # No year in the label -> default season year.
        self.assertEqual(G.extract_session_date("Reintegro 11-02", default_year=2026),
                         date(2026, 2, 11))

    def test_extract_session_date_two_digit_year(self):
        self.assertEqual(G.extract_session_date("Sesión 05-01-25"), date(2025, 1, 5))

    def test_extract_session_date_undated(self):
        self.assertIsNone(G.extract_session_date("Amistoso vs San Luis"))
        self.assertIsNone(G.extract_session_date("Sub20 vs UDEC"))

    def test_resolve_date_prefers_days_column(self):
        row = G.GpsRow(player_label="AguArc", session="Sesión 04-01-26",
                       days_raw="Mon Mar 09 23:01:33 UTC 2026")
        self.assertEqual(G.resolve_date(row), date(2026, 3, 9))  # Days wins
        row2 = G.GpsRow(player_label="AguArc", session="Sesión 04-01-26", days_raw=None)
        self.assertEqual(G.resolve_date(row2), date(2026, 1, 4))  # falls back to label

    def test_classify_session(self):
        self.assertEqual(G.classify_session("F8 vs La Serena", is_match_file=True), "partido")
        self.assertEqual(G.classify_session("Reintegro 01-04-26", is_match_file=False), "reintegro")
        self.assertEqual(G.classify_session("Amistoso vs San Luis", is_match_file=False), "amistoso")
        self.assertEqual(G.classify_session("Tareas F5 vs Colo Colo", is_match_file=False), "tareas")
        self.assertEqual(G.classify_session("Sesión 04-01-26", is_match_file=False), "entrenamiento")
        self.assertEqual(G.classify_session("Sub20 vs UDEC", is_match_file=False), "otro")

    def test_parse_match_parts(self):
        self.assertEqual(G.parse_match_parts("F8 vs La Serena"), ("F8", "La Serena"))
        self.assertEqual(G.parse_match_parts("C.Liga F2 vs ULC"), ("C.Liga F2", "ULC"))
        self.assertEqual(G.parse_match_parts("Sesión 04-01-26"), (None, None))

    def test_build_result_data_maps_headers_and_coerces(self):
        row = G.GpsRow(
            player_label="AguArc", session="F6 vs U.Concepción", days_raw=None,
            metrics={
                "Tiempo (min)": 78.0, "Distance (m)": 8952.0, "Max Speed (km/h)": 28.3,
                "Speed Zones (m) [95.0, 100.0]": 0.0, "HMLD (m)": None,  # None dropped
            },
        )
        data = G.build_result_data(row)
        self.assertEqual(data["tot_dur"], 78.0)
        self.assertEqual(data["tot_dist"], 8952.0)
        self.assertEqual(data["max_vel"], 28.3)
        self.assertEqual(data["zone_95_100"], 0.0)  # zero is a real value, kept
        self.assertNotIn("hmld", data)              # None is dropped
        self.assertIsInstance(data["tot_dur"], float)


from .management.commands.split_gps_partido import (  # noqa: E402
    convert_per_half,
    remap_display_config,
    remap_field_keys,
    PER_HALF_TO_PARTIDO,
    LEGACY_TRAIN_TO_SESSION,
)


class SplitGpsPartidoHelpersTests(SimpleTestCase):
    """Pure conversion helpers for the gps_sesion → gps_partido split."""

    def test_convert_per_half_maps_totals_only(self):
        data = convert_per_half({
            "tot_dist_total": 9500.0, "tot_dist_p1": 5000.0, "tot_dist_p2": 4500.0,
            "tot_dur_total": 92.0, "sprint_total": 210.0, "dist_85_95_total": 30.0,
            "player_load_total": 700.0, "hiaa_total": 40.0, "dist_70_85_total": 120.0,
            "hsr_rel_total": 8.4,
        })
        self.assertEqual(data["tot_dist"], 9500.0)
        self.assertEqual(data["tot_dur"], 92.0)
        self.assertEqual(data["sprint_dist"], 210.0)      # distance >25 km/h
        self.assertEqual(data["zone_85_95"], 30.0)        # same %Vmax band
        self.assertEqual(data["player_load"], 700.0)      # optional provider metric
        self.assertEqual(data["hiaa"], 40.0)
        self.assertNotIn("tot_dist_p1", data)             # halves stay archived
        self.assertNotIn("hsr_rel", data)                 # no counterpart
        self.assertNotIn("zone_75_85", data)              # 70-85 band ≠ 75-85

    def test_convert_per_half_skips_non_numeric_and_none(self):
        data = convert_per_half({"tot_dist_total": None, "max_vel_total": "n/a",
                                 "hsr_total": True, "hmld_total": 1200})
        self.assertEqual(data, {"hmld": 1200})

    def test_remap_field_keys_drops_unmappable(self):
        keys = ["tot_dist_total", "hsr_total", "hsr_rel_total", "mpm_total"]
        self.assertEqual(remap_field_keys(keys, PER_HALF_TO_PARTIDO),
                         ["tot_dist", "hsr", "mpm"])
        self.assertEqual(
            remap_field_keys(["tot_dist", "sprint", "rpe", "hsr_rel"], LEGACY_TRAIN_TO_SESSION),
            ["tot_dist", "sprint_dist", "rpe"],
        )

    def test_remap_display_config_rewrites_axis_keys(self):
        cfg = {
            "y_axis_title": "CK (U/L)",
            "right_axis_keys": ["tot_dist_total"],
            "right_y_axis_title": "Distancia total (m)",
        }
        out = remap_display_config(cfg, PER_HALF_TO_PARTIDO)
        self.assertEqual(out["right_axis_keys"], ["tot_dist"])
        self.assertEqual(out["y_axis_title"], "CK (U/L)")

    def test_remap_display_config_drops_unmappable_total_keys_from_lists(self):
        cfg = {"right_axis_keys": ["tot_dist_total", "hsr_rel_total"]}
        out = remap_display_config(cfg, PER_HALF_TO_PARTIDO)
        self.assertEqual(out["right_axis_keys"], ["tot_dist"])


from .microcycle import microcycle_label  # noqa: E402


class MicrocycleLabelTests(SimpleTestCase):
    MATCH = date(2026, 7, 12)  # a Sunday match

    def test_no_calendar_is_unlabelled(self):
        self.assertIsNone(microcycle_label(date(2026, 7, 8), []))

    def test_day_before_is_md_minus_1(self):
        self.assertEqual(microcycle_label(date(2026, 7, 11), [self.MATCH]), "MD-1")

    def test_four_days_before_is_md_minus_4(self):
        self.assertEqual(microcycle_label(date(2026, 7, 8), [self.MATCH]), "MD-4")

    def test_match_day_is_md(self):
        self.assertEqual(microcycle_label(self.MATCH, [self.MATCH]), "MD")

    def test_day_after_is_md_plus_1(self):
        self.assertEqual(microcycle_label(date(2026, 7, 13), [self.MATCH]), "MD+1")

    def test_beyond_a_week_is_unlabelled(self):
        self.assertIsNone(microcycle_label(date(2026, 7, 1), [self.MATCH]))

    def test_picks_nearest_of_several_matches(self):
        cal = [date(2026, 7, 5), date(2026, 7, 12), date(2026, 7, 19)]
        # Wed 8th: 3 days after the 5th (MD+3) vs 4 days before the 12th → MD+3.
        self.assertEqual(microcycle_label(date(2026, 7, 8), cal), "MD+3")

    def test_tie_prefers_upcoming_match(self):
        # Equidistant (2 days) between a past and an upcoming match → MD-2.
        cal = [date(2026, 7, 10), date(2026, 7, 14)]
        self.assertEqual(microcycle_label(date(2026, 7, 12), cal), "MD-2")
