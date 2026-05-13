"""Unit tests for the goal evaluator.

Silent miss = bad clinical signal — these tests cover the operators, the
"no reading" / "non-numeric value" edge cases, and the daily transitions.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ExamTemplate

from .evaluator import (
    apply_due_goals,
    evaluate_goal,
    evaluate_threshold_rules_for_result,
    sync_evaluate_for_result,
)
from .models import (
    Alert,
    AlertRule,
    AlertRuleKind,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    Goal,
    GoalOperator,
    GoalStatus,
)


def _make_template(department, *, name="CK", field_key="valor"):
    return ExamTemplate.objects.create(
        name=name,
        department=department,
        config_schema={
            "fields": [
                {"key": field_key, "label": "Valor", "type": "number", "unit": "U/L"}
            ]
        },
        input_config={
            "input_modes": ["single"],
            "default_input_mode": "single",
            "modifiers": {},
        },
    )


def _make_result(player, template, value, *, days_ago=0, field_key="valor"):
    return ExamResult.objects.create(
        player=player,
        template=template,
        recorded_at=timezone.now() - timedelta(days=days_ago),
        result_data={field_key: value},
    )


class GoalEvaluatorTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Médico", slug="medico")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B", nationality="CL",
        )
        self.template = _make_template(self.dept)
        self.template.applicable_categories.add(self.cat)

    # ---------- pure-function evaluate_goal ----------

    def test_lte_met(self):
        _make_result(self.player, self.template, 480)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        met, reading = evaluate_goal(goal)
        self.assertTrue(met)
        self.assertEqual(reading.value, 480.0)

    def test_lte_missed(self):
        _make_result(self.player, self.template, 920)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        met, reading = evaluate_goal(goal)
        self.assertFalse(met)
        self.assertEqual(reading.value, 920.0)

    def test_gte_and_gt(self):
        _make_result(self.player, self.template, 1.020)
        for op, expected in [(GoalOperator.GTE, True), (GoalOperator.GT, False)]:
            goal = Goal.objects.create(
                player=self.player, template=self.template, field_key="valor",
                operator=op, target_value=1.020, due_date=date.today(),
            )
            met, _ = evaluate_goal(goal)
            self.assertEqual(met, expected, f"Failed for operator {op}")

    def test_no_reading_returns_none(self):
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        met, reading = evaluate_goal(goal)
        self.assertIsNone(met)
        self.assertIsNone(reading)

    def test_null_field_in_latest_result_treats_as_no_reading(self):
        ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(),
            result_data={"valor": None},  # explicit null in JSONB
        )
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        met, reading = evaluate_goal(goal)
        self.assertIsNone(met)
        self.assertIsNone(reading)

    def test_non_numeric_value_treats_as_no_reading(self):
        ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(),
            result_data={"valor": "n/a"},
        )
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        met, reading = evaluate_goal(goal)
        self.assertIsNone(met)
        self.assertIsNone(reading)

    def test_uses_most_recent_reading(self):
        # Old reading meets, recent reading misses → goal is missed.
        _make_result(self.player, self.template, 480, days_ago=10)
        _make_result(self.player, self.template, 800, days_ago=1)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        met, reading = evaluate_goal(goal)
        self.assertFalse(met)
        self.assertEqual(reading.value, 800.0)

    # ---------- apply_due_goals (the daily Celery tick) ----------

    def test_apply_due_goals_transitions_met(self):
        _make_result(self.player, self.template, 400)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        summary = apply_due_goals()
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.MET)
        self.assertEqual(goal.last_value, 400.0)
        self.assertEqual(summary["met"], 1)
        self.assertEqual(summary["alerts_fired"], 0)
        self.assertFalse(Alert.objects.filter(source_id=goal.id).exists())

    def test_apply_due_goals_fires_alert_on_miss(self):
        _make_result(self.player, self.template, 1000)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500, due_date=date.today(),
        )
        summary = apply_due_goals()
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.MISSED)
        self.assertEqual(summary["missed"], 1)
        self.assertEqual(summary["alerts_fired"], 1)
        alert = Alert.objects.get(source_id=goal.id)
        self.assertEqual(alert.status, AlertStatus.ACTIVE)
        self.assertIn("1000", alert.message)

    def test_apply_due_goals_fires_alert_on_no_reading(self):
        # Past-due goal with zero readings — "missed by absence".
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() - timedelta(days=1),
        )
        apply_due_goals()
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.MISSED)
        self.assertIsNone(goal.last_value)
        alert = Alert.objects.get(source_id=goal.id)
        self.assertIn("Sin datos", alert.message)

    def test_apply_due_goals_skips_future_dates(self):
        _make_result(self.player, self.template, 1000)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=7),
        )
        summary = apply_due_goals()
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.ACTIVE)
        self.assertEqual(summary["evaluated"], 0)

    def test_apply_due_goals_is_idempotent_on_already_processed_goals(self):
        # Already-met goal should not re-fire alerts.
        _make_result(self.player, self.template, 1000)
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() - timedelta(days=2),
            status=GoalStatus.MISSED,
        )
        summary = apply_due_goals()
        # Filter is `status=ACTIVE`, so the missed goal is skipped.
        self.assertEqual(summary["evaluated"], 0)
        self.assertEqual(Alert.objects.filter(source_id=goal.id).count(), 0)

    # ---------- sync_evaluate_for_result (post_save signal path) ----------

    def test_sync_flips_active_to_met_on_qualifying_reading(self):
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=14),  # future
        )
        # Save a qualifying result — signal fires sync_evaluate_for_result.
        result = _make_result(self.player, self.template, 420)
        # The signal already ran via post_save, but call directly to be
        # explicit (also tests that calling twice is safe).
        sync_evaluate_for_result(result)
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.MET)
        self.assertEqual(goal.last_value, 420.0)

    def test_sync_does_not_flip_active_to_missed(self):
        # A bad reading pre-deadline should NOT close the goal — the doctor
        # still has time to follow up. Only the daily tick can transition
        # to MISSED.
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=14),
        )
        _make_result(self.player, self.template, 950)
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.ACTIVE)

    def test_warning_fires_within_window(self):
        from .evaluator import evaluate_goal_warnings
        # Goal due in 5 days, warn_days_before=7 → warning window.
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=5),
            warn_days_before=7,
        )
        # No reading → not met → warning fires.
        summary = evaluate_goal_warnings()
        self.assertEqual(summary["warned"], 1)
        alert = Alert.objects.get(source_id=goal.id)
        self.assertEqual(alert.source_type, AlertSource.GOAL_WARNING)
        self.assertIn("quedan 5", alert.message)

    def test_warning_skipped_outside_window(self):
        from .evaluator import evaluate_goal_warnings
        # Due in 30 days, warn_days_before=7 → outside window.
        Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=30),
            warn_days_before=7,
        )
        summary = evaluate_goal_warnings()
        self.assertEqual(summary["warned"], 0)
        self.assertFalse(
            Alert.objects.filter(source_type=AlertSource.GOAL_WARNING).exists()
        )

    def test_warning_skipped_when_already_met(self):
        from .evaluator import evaluate_goal_warnings
        _make_result(self.player, self.template, 400)  # under target → met
        Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=3),
            warn_days_before=7,
        )
        summary = evaluate_goal_warnings()
        self.assertEqual(summary["warned"], 0)

    def test_warning_skipped_when_disabled(self):
        from .evaluator import evaluate_goal_warnings
        Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=3),
            warn_days_before=None,  # disabled
        )
        summary = evaluate_goal_warnings()
        self.assertEqual(summary["warned"], 0)

    def test_warning_dismissed_when_goal_closes(self):
        from .evaluator import evaluate_goal_warnings
        # Set up a warning alert manually.
        goal = Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today() + timedelta(days=3),
            warn_days_before=7,
        )
        evaluate_goal_warnings()
        warning = Alert.objects.get(source_id=goal.id, source_type=AlertSource.GOAL_WARNING)
        self.assertEqual(warning.status, AlertStatus.ACTIVE)
        # Now the doctor saves a passing reading — sync evaluator flips to MET
        # and the warning should resolve.
        _make_result(self.player, self.template, 400)
        warning.refresh_from_db()
        self.assertEqual(warning.status, AlertStatus.RESOLVED)

    def test_sync_alert_idempotent(self):
        # Trigger apply_due_goals twice on the same missed goal — only one
        # active alert should exist.
        _make_result(self.player, self.template, 1000)
        Goal.objects.create(
            player=self.player, template=self.template, field_key="valor",
            operator=GoalOperator.LTE, target_value=500,
            due_date=date.today(),
        )
        apply_due_goals()
        # Reset the goal back to ACTIVE so we can re-run apply_due_goals
        # and check that the existing active alert is reused.
        Goal.objects.update(status=GoalStatus.ACTIVE)
        apply_due_goals()
        self.assertEqual(
            Alert.objects.filter(status=AlertStatus.ACTIVE).count(), 1,
        )


# =============================================================================
# Threshold rule tests
# =============================================================================


class ThresholdEvaluatorTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
        )
        self.template = _make_template(self.dept, name="CK", field_key="valor")
        self.template.applicable_categories.add(self.cat)

    def _bound_rule(self, **cfg) -> AlertRule:
        return AlertRule.objects.create(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BOUND,
            config=cfg, severity=AlertSeverity.WARNING,
        )

    def _variation_rule(self, **cfg) -> AlertRule:
        return AlertRule.objects.create(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.VARIATION,
            config=cfg, severity=AlertSeverity.WARNING,
        )

    # ---------- Bound ----------

    def test_bound_upper_triggers(self):
        rule = self._bound_rule(upper=500)
        result = _make_result(self.player, self.template, 920)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id, status=AlertStatus.ACTIVE).exists())

    def test_bound_lower_triggers(self):
        rule = self._bound_rule(lower=100)
        result = _make_result(self.player, self.template, 50)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id, status=AlertStatus.ACTIVE).exists())

    def test_bound_value_inside_range_skips(self):
        rule = self._bound_rule(lower=100, upper=500)
        result = _make_result(self.player, self.template, 250)
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_bound_message_uses_template(self):
        rule = self._bound_rule(upper=500)
        rule.message_template = "{field_label}={value} (>{upper})"
        rule.save()
        result = _make_result(self.player, self.template, 920)
        evaluate_threshold_rules_for_result(result)
        alert = Alert.objects.get(source_id=rule.id)
        self.assertEqual(alert.message, "Valor=920 (>500)")

    # ---------- Variation: last_n ----------

    def test_variation_last_n_increase(self):
        # Three prior readings → mean = 100. Current = 110 → +10%.
        for v, days_ago in [(100, 21), (100, 14), (100, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_pct=5, direction="increase",
        )
        result = _make_result(self.player, self.template, 110, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_decrease_only_skips_increase(self):
        for v, days_ago in [(100, 21), (100, 14), (100, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_pct=5, direction="decrease",
        )
        # +10% but the rule wants decreases only → no alert.
        result = _make_result(self.player, self.template, 110, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_below_threshold_skips(self):
        for v, days_ago in [(100, 21), (100, 14), (100, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_pct=15, direction="any",
        )
        # +10% < 15% threshold → no alert.
        result = _make_result(self.player, self.template, 110, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    # ---------- Variation: timedelta ----------

    def test_variation_timedelta_window_only_includes_recent(self):
        # Only a 60-day-old reading exists; window=30 days → no usable history → skip.
        _make_result(self.player, self.template, 100, days_ago=60)
        rule = self._variation_rule(
            window={"kind": "timedelta", "days": 30},
            threshold_pct=5, direction="any",
        )
        result = _make_result(self.player, self.template, 200, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        # No alert: empty baseline → skip rather than divide by zero.
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_timedelta_with_history(self):
        # Two 10-day-old readings of 100 → mean=100; current=200 = +100%.
        _make_result(self.player, self.template, 100, days_ago=10)
        _make_result(self.player, self.template, 100, days_ago=5)
        rule = self._variation_rule(
            window={"kind": "timedelta", "days": 30},
            threshold_pct=20, direction="any",
        )
        result = _make_result(self.player, self.template, 200, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())

    # ---------- Variation: threshold_units ----------

    def test_variation_threshold_units_triggers(self):
        # Baseline 100 → current 103 → +3 absolute; threshold_units=2 → fires.
        # threshold_pct of 5 would NOT fire (3% < 5%) — proves units works alone.
        for v, days_ago in [(100, 21), (100, 14), (100, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_units=2, direction="any",
        )
        result = _make_result(self.player, self.template, 103, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_threshold_units_below_skips(self):
        for v, days_ago in [(100, 21), (100, 14), (100, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_units=10, direction="any",
        )
        result = _make_result(self.player, self.template, 103, days_ago=0)  # +3 < 10
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_units_decrease_only(self):
        for v, days_ago in [(100, 21), (100, 14), (100, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_units=2, direction="decrease",
        )
        # +5 absolute is an increase → no fire under decrease-only.
        result = _make_result(self.player, self.template, 105, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_combined_thresholds_units_wins(self):
        # Both thresholds set; only units triggers (small % but big absolute).
        # baseline=1000 → current=1010 = +1% (< 5%) but +10 (≥ 5 units).
        for v, days_ago in [(1000, 21), (1000, 14), (1000, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_pct=5, threshold_units=5, direction="any",
        )
        result = _make_result(self.player, self.template, 1010, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_combined_thresholds_pct_wins(self):
        # Both thresholds set; only pct triggers (small absolute but big %).
        # baseline=10 → current=12 = +20% (≥ 5%) but +2 (< 5 units).
        for v, days_ago in [(10, 21), (10, 14), (10, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_pct=5, threshold_units=5, direction="any",
        )
        result = _make_result(self.player, self.template, 12, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_units_works_with_zero_baseline(self):
        # Baseline=0 disables percentage path but units still works.
        for v, days_ago in [(0, 21), (0, 14), (0, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_units=5, direction="any",
        )
        result = _make_result(self.player, self.template, 10, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())

    def test_variation_pct_only_skips_when_baseline_zero(self):
        # Baseline=0 + pct-only → cannot evaluate → no alert.
        for v, days_ago in [(0, 21), (0, 14), (0, 7)]:
            _make_result(self.player, self.template, v, days_ago=days_ago)
        rule = self._variation_rule(
            window={"kind": "last_n", "n": 3},
            threshold_pct=5, direction="any",
        )
        result = _make_result(self.player, self.template, 10, days_ago=0)
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    # ---------- Idempotence + trigger_count ----------

    def test_repeat_trigger_increments_counter(self):
        rule = self._bound_rule(upper=500)
        # Three saves that all trigger.
        for v in (520, 600, 700):
            _make_result(self.player, self.template, v)
        evaluate_threshold_rules_for_result(
            ExamResult.objects.filter(player=self.player, template=self.template)
            .order_by("-recorded_at").first()
        )
        # The post_save signal also fires the evaluator; count active alerts
        # for this rule — should be exactly one.
        active = Alert.objects.filter(
            source_id=rule.id, status=AlertStatus.ACTIVE,
        )
        self.assertEqual(active.count(), 1)
        self.assertGreaterEqual(active.first().trigger_count, 3)

    def test_dismissed_then_new_violation_creates_fresh_alert(self):
        rule = self._bound_rule(upper=500)
        _make_result(self.player, self.template, 920)
        Alert.objects.filter(source_id=rule.id).update(status=AlertStatus.DISMISSED)
        # New result triggers again → new active alert.
        _make_result(self.player, self.template, 1000)
        active = Alert.objects.filter(source_id=rule.id, status=AlertStatus.ACTIVE)
        self.assertEqual(active.count(), 1)
        # And a dismissed one is preserved.
        self.assertTrue(Alert.objects.filter(source_id=rule.id, status=AlertStatus.DISMISSED).exists())

    # ---------- Scoping ----------

    def test_category_scoped_rule_skips_other_categories(self):
        other_cat = Category.objects.create(club=self.club, name="B")
        other_cat.departments.add(self.dept)
        self.template.applicable_categories.add(other_cat)
        rule = AlertRule.objects.create(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BOUND, config={"upper": 500},
            severity=AlertSeverity.WARNING,
            category=other_cat,  # only fires for category B
        )
        # Player is in category A → rule shouldn't fire.
        _make_result(self.player, self.template, 920)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_inactive_rule_does_not_fire(self):
        rule = self._bound_rule(upper=500)
        rule.is_active = False
        rule.save()
        _make_result(self.player, self.template, 920)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())


class AlertRuleValidationTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="X", slug="x")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.template = _make_template(self.dept, name="T", field_key="valor")
        self.template.applicable_categories.add(self.cat)

    def test_unknown_field_key_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="nonsense",
            kind=AlertRuleKind.BOUND, config={"upper": 1},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_bound_without_sides_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BOUND, config={},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_bound_upper_lower_inverted_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BOUND, config={"upper": 100, "lower": 200},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_variation_invalid_window_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.VARIATION,
            config={"window": {"kind": "monthly"}, "threshold_pct": 5},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_variation_no_thresholds_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.VARIATION,
            config={"window": {"kind": "last_n", "n": 3}, "direction": "any"},
        )
        with self.assertRaisesRegex(ValidationError, "at least one"):
            rule.full_clean()

    def test_variation_negative_threshold_units_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.VARIATION,
            config={
                "window": {"kind": "last_n", "n": 3},
                "threshold_units": -1,
            },
        )
        with self.assertRaisesRegex(ValidationError, "> 0"):
            rule.full_clean()

    def test_text_field_rejected(self):
        from django.core.exceptions import ValidationError
        text_template = ExamTemplate.objects.create(
            name="N", slug="n", department=self.dept,
            config_schema={"fields": [{"key": "nota", "type": "text"}]},
        )
        rule = AlertRule(
            template=text_template, field_key="nota",
            kind=AlertRuleKind.BOUND, config={"upper": 1},
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_band_rule_without_reference_ranges_rejected(self):
        from django.core.exceptions import ValidationError
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BAND, config={},
        )
        with self.assertRaisesRegex(ValidationError, "reference_ranges"):
            rule.full_clean()

    def test_band_rule_with_ranges_passes(self):
        self.template.config_schema = {
            "fields": [
                {
                    "key": "valor", "label": "Valor", "type": "number", "unit": "U/L",
                    "reference_ranges": [
                        {"label": "OK",        "max": 100, "color": "#16a34a"},
                        {"label": "Elevado",   "min": 100, "color": "#dc2626"},
                    ],
                }
            ]
        }
        self.template.save(update_fields=["config_schema"])
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BAND, config={},
        )
        rule.full_clean()  # should not raise

    def test_band_invalid_trigger_labels_rejected(self):
        from django.core.exceptions import ValidationError
        self.template.config_schema = {
            "fields": [
                {
                    "key": "valor", "label": "Valor", "type": "number", "unit": "U/L",
                    "reference_ranges": [
                        {"label": "OK",      "max": 100, "color": "#16a34a"},
                        {"label": "Elevado", "min": 100, "color": "#dc2626"},
                    ],
                }
            ]
        }
        self.template.save(update_fields=["config_schema"])
        rule = AlertRule(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BAND, config={"trigger_labels": [123]},
        )
        with self.assertRaisesRegex(ValidationError, "trigger_labels"):
            rule.full_clean()


def _make_banded_template(department, field_key="valor"):
    """Build a template whose `field_key` has Bajo/OK/Elevado bands.

    Heuristic-friendly: "Elevado" carries a strong red (#dc2626), "Bajo" a
    strong green (#16a34a), so `alert_bands()` picks Elevado by default.
    """
    return ExamTemplate.objects.create(
        name="Banded", slug="banded", department=department,
        config_schema={
            "fields": [{
                "key": field_key, "label": "Valor", "type": "number",
                "unit": "U/L",
                "reference_ranges": [
                    {"label": "Bajo",    "max": 50,            "color": "#16a34a"},
                    {"label": "OK",      "min": 50, "max": 100, "color": "#86efac"},
                    {"label": "Elevado", "min": 100,           "color": "#dc2626"},
                ],
            }],
        },
    )


class BandRuleEvaluatorTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
        )
        self.template = _make_banded_template(self.dept)
        self.template.applicable_categories.add(self.cat)

    def _band_rule(self, **cfg) -> AlertRule:
        return AlertRule.objects.create(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BAND,
            config=cfg, severity=AlertSeverity.CRITICAL,
        )

    def test_value_in_red_band_fires(self):
        rule = self._band_rule()
        result = _make_result(self.player, self.template, 150)  # → Elevado
        evaluate_threshold_rules_for_result(result)
        self.assertTrue(Alert.objects.filter(
            source_id=rule.id, status=AlertStatus.ACTIVE,
        ).exists())

    def test_value_in_safe_band_does_not_fire(self):
        rule = self._band_rule()
        result = _make_result(self.player, self.template, 75)  # → OK
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_alert_severity_inherited_from_rule(self):
        # Slice 2 will default new rules to CRITICAL; this test confirms
        # the evaluator passes the rule's severity through verbatim.
        rule = self._band_rule()
        result = _make_result(self.player, self.template, 150)
        evaluate_threshold_rules_for_result(result)
        alert = Alert.objects.get(source_id=rule.id)
        self.assertEqual(alert.severity, AlertSeverity.CRITICAL)

    def test_subsequent_safe_reading_auto_resolves(self):
        # First reading in red band → alert fires.
        # Second reading back in OK → alert auto-resolves.
        rule = self._band_rule()
        red = _make_result(self.player, self.template, 150, days_ago=2)
        evaluate_threshold_rules_for_result(red)
        self.assertEqual(
            Alert.objects.filter(source_id=rule.id, status=AlertStatus.ACTIVE).count(),
            1,
        )
        ok = _make_result(self.player, self.template, 75, days_ago=0)
        evaluate_threshold_rules_for_result(ok)
        # Active count must now be 0; the original alert flipped to RESOLVED.
        self.assertEqual(
            Alert.objects.filter(source_id=rule.id, status=AlertStatus.ACTIVE).count(),
            0,
        )
        self.assertEqual(
            Alert.objects.filter(
                source_id=rule.id, status=AlertStatus.RESOLVED,
            ).count(),
            1,
        )

    def test_trigger_labels_override_heuristic(self):
        # Force OK to be the trigger (silly, but tests the override path).
        rule = self._band_rule(trigger_labels=["OK"])
        ok = _make_result(self.player, self.template, 75)  # → OK band
        evaluate_threshold_rules_for_result(ok)
        self.assertTrue(Alert.objects.filter(source_id=rule.id).exists())
        # And Elevado should NOT fire because it's not in trigger_labels.
        Alert.objects.filter(source_id=rule.id).delete()
        red = _make_result(self.player, self.template, 150, days_ago=0)
        evaluate_threshold_rules_for_result(red)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_non_numeric_value_skips_silently(self):
        rule = self._band_rule()
        # `_value_for_rule` returns None for text values → no alert.
        result = ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(),
            result_data={"valor": "n/a"},
        )
        evaluate_threshold_rules_for_result(result)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_inactive_band_rule_does_not_fire(self):
        rule = self._band_rule()
        rule.is_active = False
        rule.save()
        _make_result(self.player, self.template, 150)
        self.assertFalse(Alert.objects.filter(source_id=rule.id).exists())

    def test_message_template_with_band_placeholder(self):
        rule = self._band_rule()
        rule.message_template = "{field_label} = {value} → {band_label}"
        rule.save(update_fields=["message_template"])
        result = _make_result(self.player, self.template, 150)
        evaluate_threshold_rules_for_result(result)
        alert = Alert.objects.get(source_id=rule.id)
        self.assertEqual(alert.message, "Valor = 150 → Elevado")


class SeedBandAlertsCommandTests(TestCase):
    """End-to-end coverage for `python manage.py seed_band_alerts`.

    These tests intentionally don't mock the evaluator — the command's
    value proposition IS the end-to-end "rules created → alerts firing"
    flow, so we exercise it as one piece.
    """

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="N", slug="n")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player_red = Player.objects.create(
            category=self.cat, first_name="Red", last_name="P", is_active=True,
        )
        self.player_safe = Player.objects.create(
            category=self.cat, first_name="Safe", last_name="P", is_active=True,
        )
        self.template = _make_banded_template(self.dept)
        self.template.applicable_categories.add(self.cat)

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("seed_band_alerts", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_creates_rule_for_field_with_red_band(self):
        self._run()
        rules = AlertRule.objects.filter(
            template=self.template, field_key="valor", kind=AlertRuleKind.BAND,
        )
        self.assertEqual(rules.count(), 1)
        rule = rules.first()
        self.assertEqual(rule.severity, AlertSeverity.CRITICAL)
        self.assertTrue(rule.is_active)
        self.assertEqual(rule.config, {})

    def test_idempotent_rerun_does_not_duplicate(self):
        self._run()
        before = AlertRule.objects.filter(kind=AlertRuleKind.BAND).count()
        self._run()
        after = AlertRule.objects.filter(kind=AlertRuleKind.BAND).count()
        self.assertEqual(before, after)

    def test_preserves_admin_severity_on_rerun(self):
        self._run()
        rule = AlertRule.objects.get(kind=AlertRuleKind.BAND, template=self.template)
        rule.severity = AlertSeverity.WARNING
        rule.message_template = "custom message"
        rule.save(update_fields=["severity", "message_template"])
        self._run()
        rule.refresh_from_db()
        self.assertEqual(rule.severity, AlertSeverity.WARNING)
        self.assertEqual(rule.message_template, "custom message")

    def test_backfill_fires_alert_for_player_in_red_band(self):
        _make_result(self.player_red, self.template, 150)
        _make_result(self.player_safe, self.template, 75)
        self._run()
        red_alerts = Alert.objects.filter(
            player=self.player_red, status=AlertStatus.ACTIVE,
            source_type=AlertSource.THRESHOLD,
        )
        safe_alerts = Alert.objects.filter(
            player=self.player_safe, status=AlertStatus.ACTIVE,
            source_type=AlertSource.THRESHOLD,
        )
        self.assertEqual(red_alerts.count(), 1)
        self.assertEqual(safe_alerts.count(), 0)

    def test_skips_field_without_alert_color(self):
        # Replace the template's field with bands that have only cool colors.
        self.template.config_schema = {
            "fields": [{
                "key": "valor", "label": "Valor", "type": "number", "unit": "U/L",
                "reference_ranges": [
                    {"label": "Bajo", "max": 50,  "color": "#16a34a"},
                    {"label": "Alto", "min": 50,  "color": "#22c55e"},  # still greenish
                ],
            }],
        }
        self.template.save(update_fields=["config_schema"])
        self._run()
        self.assertFalse(AlertRule.objects.filter(
            template=self.template, kind=AlertRuleKind.BAND,
        ).exists())

    def test_deactivates_rule_when_alert_band_removed(self):
        # Seed once → rule active.
        self._run()
        rule = AlertRule.objects.get(template=self.template, kind=AlertRuleKind.BAND)
        self.assertTrue(rule.is_active)

        # Remove the red band → re-seed should deactivate.
        self.template.config_schema = {
            "fields": [{
                "key": "valor", "label": "Valor", "type": "number", "unit": "U/L",
                "reference_ranges": [
                    {"label": "Bajo", "max": 50,  "color": "#16a34a"},
                    {"label": "Alto", "min": 50,  "color": "#22c55e"},
                ],
            }],
        }
        self.template.save(update_fields=["config_schema"])
        self._run()
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    def test_dry_run_writes_nothing(self):
        self._run("--dry-run")
        self.assertFalse(AlertRule.objects.exists())
        self.assertFalse(Alert.objects.exists())

    def test_no_backfill_creates_rules_but_no_alerts(self):
        _make_result(self.player_red, self.template, 150)
        # Wipe alerts the post_save signal created so we can verify the
        # command itself doesn't add any more when --no-backfill is set.
        Alert.objects.all().delete()
        self._run("--no-backfill")
        self.assertTrue(AlertRule.objects.filter(kind=AlertRuleKind.BAND).exists())
        self.assertFalse(Alert.objects.filter(source_type=AlertSource.THRESHOLD).exists())
