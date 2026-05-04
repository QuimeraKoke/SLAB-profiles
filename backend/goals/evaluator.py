"""Goal evaluation engine.

Pure-function `evaluate_goal(goal)` returns the player's current value on
the goal's (template, field_key) and whether it satisfies the operator.

`apply_due_goals()` runs daily via Celery beat: every active goal whose
due_date <= today is transitioned to MET / MISSED and an Alert is fired
on misses.

`sync_evaluate_for_result(result)` runs from a post_save signal so a
freshly-saved reading can flip a goal to MET *before* its due_date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from django.db import models
from django.utils import timezone

from exams.models import ExamResult
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


_OPERATORS = {
    GoalOperator.LTE: lambda a, t: a <= t,
    GoalOperator.LT:  lambda a, t: a < t,
    GoalOperator.EQ:  lambda a, t: a == t,
    GoalOperator.GTE: lambda a, t: a >= t,
    GoalOperator.GT:  lambda a, t: a > t,
}


@dataclass(frozen=True)
class GoalReading:
    """Snapshot of the player's latest reading on the goal's field."""

    value: float
    recorded_at: object  # datetime — kept generic to avoid TZ import noise here

    @property
    def is_present(self) -> bool:
        return self.value is not None


def _latest_reading(goal: Goal) -> GoalReading | None:
    """Find the most recent ExamResult on (player, template) and pull field_key.

    Returns None when:
      - the player has no result for this template, or
      - the latest result has the field_key as null/missing/non-numeric.
    """
    latest = (
        ExamResult.objects
        .filter(player=goal.player, template=goal.template)
        .order_by("-recorded_at")
        .first()
    )
    if latest is None:
        return None
    raw = (latest.result_data or {}).get(goal.field_key)
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return GoalReading(value=value, recorded_at=latest.recorded_at)


def evaluate_goal(goal: Goal) -> tuple[bool | None, GoalReading | None]:
    """Pure-function evaluation.

    Returns `(met, reading)`:
      - `met=True/False` when a numeric reading exists.
      - `met=None` when no reading is available — caller decides what to do
        (treat as missed on due date, ignore early on sync, etc.).
    """
    reading = _latest_reading(goal)
    if reading is None:
        return None, None
    op = _OPERATORS[GoalOperator(goal.operator)]
    return op(reading.value, goal.target_value), reading


def _fire_alert(goal: Goal, *, severity: str, message: str) -> Alert:
    """Idempotent: if an active alert already exists for this goal, refresh
    it (last_fired_at + trigger_count) instead of creating a duplicate.
    """
    return _upsert_alert(
        player=goal.player,
        source_type=AlertSource.GOAL,
        source_id=goal.id,
        severity=severity,
        message=message,
    )


def _upsert_alert(*, player, source_type: str, source_id, severity: str, message: str) -> Alert:
    """Generic upsert: refresh an active alert by (source_type, source_id), or create one.

    Used by both the goal evaluator and the threshold evaluator (§ AlertRule).
    Newly-created alerts also dispatch an email notification via Celery —
    re-fires don't (avoids spamming the doctor on every reading).
    """
    now = timezone.now()
    existing = Alert.objects.filter(
        source_type=source_type,
        source_id=source_id,
        status=AlertStatus.ACTIVE,
    ).first()
    if existing:
        existing.last_fired_at = now
        existing.trigger_count = (existing.trigger_count or 1) + 1
        existing.message = message
        existing.severity = severity
        existing.save(update_fields=[
            "last_fired_at", "trigger_count", "message", "severity",
        ])
        return existing
    alert = Alert.objects.create(
        player=player,
        source_type=source_type,
        source_id=source_id,
        severity=severity,
        status=AlertStatus.ACTIVE,
        message=message,
        last_fired_at=now,
        trigger_count=1,
    )
    # Fire-and-forget email dispatch. Wrapped in a try because the broker
    # may be unavailable in test/standalone contexts and we don't want to
    # block alert creation on it.
    try:
        from .tasks import send_alert_email
        send_alert_email.delay(str(alert.id))
    except Exception:  # pragma: no cover — broker offline / eager mode
        pass
    return alert


def _format_miss_message(goal: Goal, reading: GoalReading | None) -> str:
    operator_display = dict(GoalOperator.choices).get(goal.operator, goal.operator)
    target_str = f"{goal.target_value:g}"
    base = (
        f'Objetivo no cumplido: {goal.field_key} {operator_display} {target_str} '
        f"(vence {goal.due_date.isoformat()})"
    )
    if reading is None:
        return base + ". Sin datos en el período."
    return base + f". Valor actual: {reading.value:g}."


def apply_due_goals(today: date | None = None) -> dict:
    """Daily tick — transition active goals whose due_date has arrived.

    Returns a small summary so the Celery task log is informative:
        {"evaluated": int, "met": int, "missed": int, "alerts_fired": int}
    """
    today = today or timezone.localdate()
    qs = Goal.objects.filter(status=GoalStatus.ACTIVE, due_date__lte=today)

    summary = {"evaluated": 0, "met": 0, "missed": 0, "alerts_fired": 0}
    now = timezone.now()
    for goal in qs.iterator():
        summary["evaluated"] += 1
        met, reading = evaluate_goal(goal)
        goal.evaluated_at = now
        goal.last_value = reading.value if reading else None
        if met is True:
            goal.status = GoalStatus.MET
            summary["met"] += 1
        else:
            # met=False or met=None (no reading) — both count as missed on
            # the due date. The miss message distinguishes them.
            goal.status = GoalStatus.MISSED
            summary["missed"] += 1
            _fire_alert(
                goal,
                severity=AlertSeverity.WARNING,
                message=_format_miss_message(goal, reading),
            )
            summary["alerts_fired"] += 1
        goal.save(update_fields=["status", "last_value", "evaluated_at", "updated_at"])
        # Whichever way the goal closed, dismiss any pre-deadline warning
        # alert that's still outstanding — the warning's clinical purpose
        # is moot once the goal has been formally evaluated.
        _dismiss_active_warning(goal)
    return summary


def evaluate_goal_warnings(today: date | None = None) -> dict:
    """Daily tick — fire pre-deadline warning alerts for goals approaching
    their due_date but not yet met.

    A warning fires when ALL of:
      - goal.status == active
      - goal.warn_days_before is set (> 0)
      - 0 <= (due_date - today) <= warn_days_before
      - the goal's current value does NOT satisfy the operator (or no reading)

    Idempotent via _upsert_alert: re-running the same day refreshes the
    last_fired_at + trigger_count of the existing warning instead of
    creating duplicates. Source type GOAL_WARNING is distinct from GOAL,
    so a pre-deadline warn and an eventual due-date miss can coexist.
    """
    from datetime import timedelta as _td

    today = today or timezone.localdate()
    qs = Goal.objects.filter(
        status=GoalStatus.ACTIVE,
        warn_days_before__isnull=False,
        warn_days_before__gt=0,
    )

    summary = {"checked": 0, "warned": 0}
    for goal in qs.iterator():
        summary["checked"] += 1
        delta_days = (goal.due_date - today).days
        if delta_days < 0 or delta_days > (goal.warn_days_before or 0):
            continue  # outside the warning window
        met, reading = evaluate_goal(goal)
        if met is True:
            continue  # already meeting the goal — no need to warn
        _fire_warning_alert(goal, reading, delta_days)
        summary["warned"] += 1
    return summary


def _format_warning_message(goal: Goal, reading: GoalReading | None, days_left: int) -> str:
    operator_display = dict(GoalOperator.choices).get(goal.operator, goal.operator)
    target_str = f"{goal.target_value:g}"
    days_phrase = (
        "vence hoy" if days_left == 0
        else f"quedan {days_left} día{'s' if days_left != 1 else ''}"
    )
    base = (
        f"Aviso: objetivo {goal.field_key} {operator_display} {target_str} "
        f"({days_phrase})"
    )
    if reading is None:
        return base + ". Sin datos en el período."
    return base + f". Valor actual: {reading.value:g}."


def _fire_warning_alert(goal: Goal, reading: GoalReading | None, days_left: int) -> Alert:
    return _upsert_alert(
        player=goal.player,
        source_type=AlertSource.GOAL_WARNING,
        source_id=goal.id,
        severity=AlertSeverity.WARNING,
        message=_format_warning_message(goal, reading, days_left),
    )


def _dismiss_active_warning(goal: Goal) -> None:
    """Mark any active GOAL_WARNING alert for this goal as dismissed.

    Called when the goal transitions away from ACTIVE (met / missed /
    cancelled). The warning was raised to nudge the doctor toward acting
    before the deadline; once the goal closes, the warning is stale.
    """
    Alert.objects.filter(
        source_type=AlertSource.GOAL_WARNING,
        source_id=goal.id,
        status=AlertStatus.ACTIVE,
    ).update(
        status=AlertStatus.RESOLVED,
        dismissed_at=timezone.now(),
    )


def sync_evaluate_for_result(result: ExamResult) -> Iterable[Goal]:
    """Re-evaluate any *active* goals for the (player, template) of `result`.

    Only flips active → MET when the new reading satisfies the operator.
    Active → MISSED is reserved for the daily tick (a single bad reading
    pre-deadline shouldn't slam the goal closed; the doctor still has time
    to follow up). Returns the goals that transitioned to MET.
    """
    qs = Goal.objects.filter(
        player_id=result.player_id,
        template_id=result.template_id,
        status=GoalStatus.ACTIVE,
    )
    transitioned = []
    now = timezone.now()
    for goal in qs:
        met, reading = evaluate_goal(goal)
        if met is True:
            goal.status = GoalStatus.MET
            goal.last_value = reading.value if reading else None
            goal.evaluated_at = now
            goal.save(update_fields=["status", "last_value", "evaluated_at", "updated_at"])
            _dismiss_active_warning(goal)
            transitioned.append(goal)
    return transitioned


# =============================================================================
# Threshold rules — fire on every ExamResult save
# =============================================================================


def _value_for_rule(result: ExamResult, rule: AlertRule) -> float | None:
    raw = (result.result_data or {}).get(rule.field_key)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _bound_violated(value: float, cfg: dict) -> tuple[bool, str]:
    """Return (triggered, side) where side ∈ {'upper', 'lower', ''}."""
    upper = cfg.get("upper")
    lower = cfg.get("lower")
    if upper is not None and value > float(upper):
        return True, "upper"
    if lower is not None and value < float(lower):
        return True, "lower"
    return False, ""


def _baseline_for_variation(result: ExamResult, rule: AlertRule) -> tuple[float | None, str]:
    """Compute the mean of prior readings for this (player, template, field).

    Returns (mean, window_desc). `mean` is None if no usable history exists.
    Excludes the current result itself.
    """
    cfg = rule.config or {}
    window = cfg.get("window") or {}
    prior = (
        ExamResult.objects
        .filter(
            player_id=result.player_id,
            template_id=result.template_id,
            recorded_at__lt=result.recorded_at,
        )
        .order_by("-recorded_at")
    )
    if window.get("kind") == "last_n":
        n = int(window.get("n", 1))
        prior = list(prior[:n])
        desc = f"últimas {n}"
    elif window.get("kind") == "timedelta":
        from datetime import timedelta
        days = int(window.get("days", 30))
        cutoff = result.recorded_at - timedelta(days=days)
        prior = list(prior.filter(recorded_at__gte=cutoff))
        desc = f"últimos {days} días"
    else:
        return None, "(window inválida)"

    values: list[float] = []
    for r in prior:
        raw = (r.result_data or {}).get(rule.field_key)
        try:
            if raw is not None and raw != "":
                values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        return None, desc
    return sum(values) / len(values), desc


def _variation_triggered(delta: float, baseline: float, cfg: dict, direction: str) -> bool:
    """Returns True when either threshold (% or units) is exceeded in the
    configured direction. Either threshold may be None (= disabled)."""
    threshold_pct = cfg.get("threshold_pct")
    threshold_units = cfg.get("threshold_units")

    def exceeds_pct() -> bool:
        if threshold_pct is None or baseline == 0:
            return False
        pct = delta / baseline * 100
        if direction == "increase":
            return pct >= float(threshold_pct)
        if direction == "decrease":
            return pct <= -float(threshold_pct)
        return abs(pct) >= float(threshold_pct)

    def exceeds_units() -> bool:
        if threshold_units is None:
            return False
        if direction == "increase":
            return delta >= float(threshold_units)
        if direction == "decrease":
            return delta <= -float(threshold_units)
        return abs(delta) >= float(threshold_units)

    return exceeds_pct() or exceeds_units()


def _format_rule_message(
    rule: AlertRule,
    *,
    value: float,
    field_label: str,
    upper=None,
    lower=None,
    baseline=None,
    pct_change=None,
    delta=None,
    direction=None,
    window_desc=None,
) -> str:
    """Render a message from the rule's template, with safe fallbacks."""
    placeholders = {
        "value": f"{value:g}",
        "field_label": field_label,
        "upper": "" if upper is None else f"{float(upper):g}",
        "lower": "" if lower is None else f"{float(lower):g}",
        "baseline": "" if baseline is None else f"{baseline:g}",
        "pct_change": "" if pct_change is None else f"{pct_change:.1f}",
        "delta": "" if delta is None else f"{delta:+g}",
        "direction": direction or "",
        "window_desc": window_desc or "",
    }
    template = rule.message_template or ""
    if template:
        try:
            return template.format(**placeholders)
        except (KeyError, IndexError, ValueError):
            pass  # fall through to autogenerated message
    # Auto-generated fallback so admins can leave message_template blank.
    if rule.kind == AlertRuleKind.BOUND:
        if upper is not None and value > float(upper):
            return f"{field_label} = {value:g} (umbral superior {float(upper):g})"
        if lower is not None and value < float(lower):
            return f"{field_label} = {value:g} (umbral inferior {float(lower):g})"
        return f"{field_label} = {value:g}"

    # Variation: prefer the part that's actually configured / meaningful.
    parts = [f"{field_label}: {value:g}"]
    if delta is not None:
        parts.append(f"Δ {delta:+g}")
    if pct_change is not None:
        parts.append(f"({pct_change:+.1f}%)")
    if baseline is not None:
        parts.append(f"vs media {baseline:g}")
    if window_desc:
        parts.append(f"({window_desc})")
    return " ".join(parts)


def _field_label(rule: AlertRule) -> str:
    schema = rule.template.config_schema or {}
    for f in schema.get("fields", []) or []:
        if isinstance(f, dict) and f.get("key") == rule.field_key:
            return f.get("label") or rule.field_key
    return rule.field_key


def evaluate_threshold_rules_for_result(result: ExamResult) -> list[Alert]:
    """Evaluate every active rule on (template, player.category) for `result`.

    Returns the list of alerts that were created or updated. Idempotent:
    re-runs on the same result update the existing active alert instead of
    creating duplicates (last_fired_at + trigger_count refresh handled by
    `_upsert_alert`).
    """
    rules = (
        AlertRule.objects
        .filter(template_id=result.template_id, is_active=True)
        .filter(models.Q(category_id=None) | models.Q(category_id=result.player.category_id))
        .select_related("template", "category")
    )
    fired: list[Alert] = []
    for rule in rules:
        value = _value_for_rule(result, rule)
        if value is None:
            continue
        label = _field_label(rule)
        cfg = rule.config or {}

        if rule.kind == AlertRuleKind.BOUND:
            triggered, _side = _bound_violated(value, cfg)
            if not triggered:
                continue
            msg = _format_rule_message(
                rule, value=value, field_label=label,
                upper=cfg.get("upper"), lower=cfg.get("lower"),
            )

        elif rule.kind == AlertRuleKind.VARIATION:
            baseline, window_desc = _baseline_for_variation(result, rule)
            if baseline is None:
                continue  # no history → skip both checks
            delta = value - baseline
            direction = cfg.get("direction", "any")
            triggered = _variation_triggered(delta, baseline, cfg, direction)
            if not triggered:
                continue
            # `pct_change` is None when baseline=0 — we still let the message
            # render (the placeholder degrades to empty string).
            pct_change = (delta / baseline * 100) if baseline != 0 else None
            msg = _format_rule_message(
                rule, value=value, field_label=label,
                baseline=baseline, pct_change=pct_change, delta=delta,
                direction=direction, window_desc=window_desc,
            )
        else:
            continue

        alert = _upsert_alert(
            player=result.player,
            source_type=AlertSource.THRESHOLD,
            source_id=rule.id,
            severity=rule.severity,
            message=msg,
        )
        fired.append(alert)
    return fired


