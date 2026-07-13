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
from datetime import date, timedelta
from typing import Iterable

from django.db import models
from django.utils import timezone

from exams.bands import alert_bands as _alert_bands, band_for_value as _band_for_value
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


def _upsert_alert(*, player, source_type: str, source_id, severity: str, message: str,
                  source_recorded_at=None) -> Alert:
    """Generic upsert: refresh an active alert by (source_type, source_id, player), or create one.

    Used by both the goal evaluator and the threshold evaluator (§ AlertRule).
    Newly-created alerts also dispatch an email notification via Celery —
    re-fires don't (avoids spamming the doctor on every reading).

    `player` is part of the dedup key because threshold rules (BOUND /
    VARIATION / BAND) apply to MANY players. Without the player filter
    the second player to trip the same rule would overwrite the first
    one's alert instead of creating their own. Goal-source alerts are
    naturally per-player (Goal has a player FK), so including player
    in the filter is a no-op for them.
    """
    now = timezone.now()
    existing = Alert.objects.filter(
        source_type=source_type,
        source_id=source_id,
        player=player,
        status=AlertStatus.ACTIVE,
    ).first()
    if existing:
        existing.last_fired_at = now
        existing.trigger_count = (existing.trigger_count or 1) + 1
        existing.message = message
        existing.severity = severity
        fields = ["last_fired_at", "trigger_count", "message", "severity"]
        if source_recorded_at is not None:
            existing.source_recorded_at = source_recorded_at
            fields.append("source_recorded_at")
        existing.save(update_fields=fields)
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
        source_recorded_at=source_recorded_at,
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


def _molestia_labels(template) -> dict:
    """code → readable zone label, from the molestia field's option_labels."""
    for f in (template.config_schema or {}).get("fields", []):
        if f.get("key") == "molestia":
            return f.get("option_labels") or {}
    return {}


def evaluate_molestia_alert(*, player, template, estado: str, codes: list[str],
                            mismatch: bool, recorded_at) -> bool:
    """Upsert (or resolve) a player's molestia alert from their latest check-in.

    One active alert per (player, wellness template). Fires when the latest
    check-in reports a molestia; auto-resolves when a later check-in clears it.
    Severity escalates with the declared estado; an estado-mismatch
    (Disponible + molestia) is flagged for staff review. Returns True when an
    alert was fired/refreshed.
    """
    from .models import Alert, AlertSource, AlertStatus, AlertSeverity

    source_id = template.id  # dedup key is (source_type, source_id, player)

    if not codes:
        # Discomfort cleared → resolve any standing molestia alert.
        Alert.objects.filter(
            source_type=AlertSource.MOLESTIA, source_id=source_id,
            player=player, status=AlertStatus.ACTIVE,
        ).update(status=AlertStatus.RESOLVED)
        return False

    labels = _molestia_labels(template)
    zonas = ", ".join(labels.get(c, c) for c in codes)
    when = timezone.localtime(recorded_at).date().isoformat()
    if estado == "lesion":
        severity, suffix = AlertSeverity.CRITICAL, " · declara LESIÓN"
    elif estado == "parcial":
        severity, suffix = AlertSeverity.WARNING, " · entrena PARCIAL"
    elif mismatch:
        severity, suffix = AlertSeverity.WARNING, " · se declara DISPONIBLE — revisar"
    else:
        severity, suffix = AlertSeverity.INFO, ""
    message = f"Molestia: {zonas}{suffix} (check-in {when})"

    _upsert_alert(
        player=player, source_type=AlertSource.MOLESTIA, source_id=source_id,
        severity=severity, message=message, source_recorded_at=recorded_at,
    )
    return True


# A molestia is a DAILY self-report — once a player stops filling the
# check-in (e.g. a long-term injury), his last report ages out of relevance.
MOLESTIA_STALE_DAYS = 7


def resolve_stale_checkin_alerts(template, max_age_days: int = MOLESTIA_STALE_DAYS) -> int:
    """Resolve active check-in-derived alerts (molestia AND band/threshold)
    whose player has NOT checked in for `max_age_days`.

    The check-in is a DAILY self-report — when a player goes silent
    (typically because he's now injured and the Episode carries his state),
    his last report ages out of relevance. Without this, a frozen "check-in
    from April" alert survives forever, because both molestia and band
    alerts only auto-resolve when a NEWER reading arrives. Returns how many
    alerts were resolved.
    """
    from django.db.models import Max, Q

    from exams.models import ExamResult

    from .models import Alert, AlertRule, AlertSource, AlertStatus

    cutoff = timezone.now() - timedelta(days=max_age_days)
    rule_ids = list(AlertRule.objects.filter(template=template).values_list("id", flat=True))
    active = Alert.objects.filter(
        Q(source_type=AlertSource.MOLESTIA, source_id=template.id)
        | Q(source_type=AlertSource.THRESHOLD, source_id__in=rule_ids),
        status=AlertStatus.ACTIVE,
    )
    if not active.exists():
        return 0
    last_by_player = dict(
        ExamResult.objects.filter(
            template=template, player_id__in=active.values_list("player_id", flat=True),
        ).values_list("player_id").annotate(last=Max("recorded_at")).values_list("player_id", "last")
    )
    stale = 0
    for alert in active:
        last = last_by_player.get(alert.player_id)
        if last is None or last < cutoff:
            alert.status = AlertStatus.RESOLVED
            alert.save(update_fields=["status"])
            stale += 1
    return stale


# Backwards-compatible alias (pre-band-coverage name).
resolve_stale_molestia_alerts = resolve_stale_checkin_alerts


# General staleness policy for measurement-anchored alerts: when the reading
# behind an alert is older than this, the alert stops being actionable
# information and expires. (The daily check-in uses the tighter 7-day sweep
# above; goals follow their own due-date lifecycle and are exempt.)
ALERT_STALE_DAYS = 30

# GPS / training-load alerts anchor on a session; the doctor's ask is to
# suppress them when there's been no recent exposure — 72h without a session.
GPS_LOAD_STALE_HOURS = 72


def expire_stale_alerts(max_age_days: int = ALERT_STALE_DAYS) -> dict:
    """Resolve ACTIVE alerts whose anchoring data is older than `max_age_days`.

    - THRESHOLD (band/bound/variation rules): anchored on the player's
      LATEST result for the rule's template — "his last anthropometry says
      X" stops being an alert when that anthropometry is a season old.
    - MEDICATION / TRAINING_LOAD: anchored on the source result itself
      (`source_id` is the ExamResult id) — a WADA flag on a prescription
      from last year isn't a live signal.

    Runs daily via Celery beat. Returns counts per source type.
    """
    from django.db.models import Max

    from exams.models import ExamResult

    from .models import Alert, AlertRule, AlertSource, AlertStatus

    cutoff = timezone.now() - timedelta(days=max_age_days)
    out = {"threshold": 0, "medication": 0, "training_load": 0}

    # THRESHOLD — group lookups: rule -> template, then latest per (player, template).
    threshold = list(Alert.objects.filter(
        status=AlertStatus.ACTIVE, source_type=AlertSource.THRESHOLD,
    ))
    rules = {
        r.id: r for r in AlertRule.objects.filter(
            id__in={a.source_id for a in threshold},
        )
    }
    pairs = {
        (a.player_id, rules[a.source_id].template_id)
        for a in threshold if a.source_id in rules
    }
    latest = {}
    for pid, tid in pairs:
        latest[(pid, tid)] = (
            ExamResult.objects.filter(player_id=pid, template_id=tid)
            .aggregate(Max("recorded_at"))["recorded_at__max"]
        )
    for a in threshold:
        rule = rules.get(a.source_id)
        last = latest.get((a.player_id, rule.template_id)) if rule else None
        if last is None or last < cutoff:
            a.status = AlertStatus.RESOLVED
            a.save(update_fields=["status"])
            out["threshold"] += 1

    # MEDICATION + TRAINING_LOAD — anchored on the source reading
    # (source_recorded_at, falling back to the source ExamResult). Training-load
    # uses the tighter GPS 72h window; medication keeps the 30-day policy.
    gps_cutoff = timezone.now() - timedelta(hours=GPS_LOAD_STALE_HOURS)
    for source_type, key, type_cutoff in (
        (AlertSource.MEDICATION, "medication", cutoff),
        (AlertSource.TRAINING_LOAD, "training_load", gps_cutoff),
    ):
        for a in Alert.objects.filter(status=AlertStatus.ACTIVE, source_type=source_type):
            rec = a.source_recorded_at or (
                ExamResult.objects.filter(id=a.source_id)
                .values_list("recorded_at", flat=True).first()
            )
            if rec is None or rec < type_cutoff:
                a.status = AlertStatus.RESOLVED
                a.save(update_fields=["status"])
                out[key] += 1
    return out


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


def _result_in_scope(result: ExamResult, rule: AlertRule) -> bool:
    """True if the rule's optional scope admits this result. Empty scope = all.

    - session_types: the GPS `tipo_sesion` (or the linked event's type).
    - roles: the player's `Position.role`.
    - microcycle_days: the result's `md_label` (set at GPS ingest, §1.e).
    """
    scope = rule.scope or {}
    if not scope:
        return True
    data = result.result_data or {}

    session_types = scope.get("session_types")
    if session_types:
        sess = data.get("tipo_sesion")
        if not sess and result.event_id:
            sess = getattr(result.event, "event_type", None)
        if sess not in session_types:
            return False

    roles = scope.get("roles")
    if roles:
        pos = getattr(result.player, "position", None)
        if (getattr(pos, "role", None) if pos else None) not in roles:
            return False

    mds = scope.get("microcycle_days")
    if mds and data.get("md_label") not in mds:
        return False

    return True


def _effective_bound(cfg: dict, player) -> dict:
    """Resolve the bound band for a player: the `by_role` entry for the
    player's Position.role if present, else the top-level upper/lower (§1.2)."""
    by_role = cfg.get("by_role") or {}
    if by_role:
        pos = getattr(player, "position", None)
        role = getattr(pos, "role", None) if pos else None
        if role and role in by_role:
            band = by_role[role]
            return {"upper": band.get("upper"), "lower": band.get("lower")}
    return {"upper": cfg.get("upper"), "lower": cfg.get("lower")}


def _prior_values(result: ExamResult, rule: AlertRule) -> tuple[list[float], str]:
    """Prior numeric readings for (player, template, field), OLDEST→NEWEST,
    within the rule's window (excludes the current result). For the zscore
    kind (EWMA needs chronological order)."""
    from datetime import timedelta

    cfg = rule.config or {}
    window = cfg.get("window") or {}
    qs = (
        ExamResult.objects.filter(
            player_id=result.player_id, template_id=result.template_id,
            recorded_at__lt=result.recorded_at,
        ).order_by("-recorded_at")
    )
    if window.get("kind") == "last_n":
        n = int(window.get("n", 1))
        rows = list(qs[:n])
        desc = f"últimas {n}"
    elif window.get("kind") == "timedelta":
        days = int(window.get("days", 30))
        rows = list(qs.filter(recorded_at__gte=result.recorded_at - timedelta(days=days)))
        desc = f"últimos {days} días"
    else:
        return [], "(window inválida)"

    vals: list[float] = []
    for r in reversed(rows):  # oldest → newest
        raw = (r.result_data or {}).get(rule.field_key)
        try:
            if raw is not None and raw != "":
                vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    return vals, desc


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
        if not _result_in_scope(result, rule):
            continue
        value = _value_for_rule(result, rule)
        if value is None:
            continue
        label = _field_label(rule)
        cfg = rule.config or {}
        severity = rule.severity

        if rule.kind == AlertRuleKind.BOUND:
            eff = _effective_bound(cfg, result.player)
            triggered, _side = _bound_violated(value, eff)
            if not triggered:
                continue
            msg = _format_rule_message(
                rule, value=value, field_label=label,
                upper=eff.get("upper"), lower=eff.get("lower"),
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

        elif rule.kind == AlertRuleKind.ZSCORE:
            from dashboards import stats

            prior, window_desc = _prior_values(result, rule)
            dev = stats.deviation(
                value, prior,
                method=cfg.get("method", "moving_avg"), span=cfg.get("span"),
            )
            z = dev.get("z") if dev else None
            if z is None:
                continue  # no usable basal (need ≥2 prior + spread)
            direction = cfg.get("direction", "any")
            tz = float(cfg.get("threshold_z"))
            if direction == "increase":
                triggered = z >= tz
            elif direction == "decrease":
                triggered = z <= -tz
            else:
                triggered = abs(z) >= tz
            if not triggered:
                continue
            centre = dev.get("centre")
            msg = _format_rule_message(
                rule, value=value, field_label=label,
                baseline=centre, pct_change=dev.get("pct"),
                delta=(value - centre) if centre is not None else None,
                direction=direction, window_desc=window_desc,
            )
            msg = f"{msg} · z={z:+.1f}"

        elif rule.kind == AlertRuleKind.PCT_MATCH:
            from dashboards.player_state import match_load_refs

            refs = match_load_refs(result.player_id, result.recorded_at, [rule.field_key])
            ref = (refs.get(rule.field_key) or {}).get("chronic") if refs else None
            if not ref:
                continue  # no match-demand reference to compare against
            ru, rl = cfg.get("ratio_upper"), cfg.get("ratio_lower")
            triggered = (
                (ru is not None and value >= float(ru) * ref)
                or (rl is not None and value <= float(rl) * ref)
            )
            if not triggered:
                continue
            pct = value / ref * 100.0
            msg = _format_rule_message(
                rule, value=value, field_label=label,
                baseline=ref, pct_change=pct - 100.0, window_desc="vs partido",
            )
            msg = f"{msg} · {pct:.0f}% de partido"

        elif rule.kind == AlertRuleKind.BAND:
            current_band, alert_band_set = _band_evaluation(rule, value)
            in_alert = (
                current_band is not None
                and any(b is current_band for b in alert_band_set)
            )
            if not in_alert:
                # Auto-resolve: when a newer reading lands outside the alert
                # bands, mark any previously-fired active Alert for this
                # rule+player as RESOLVED. Keeps the team_alerts widget
                # honest — stale alerts don't haunt the watchlist.
                _resolve_band_alert(rule_id=rule.id, player_id=result.player_id)
                continue
            msg = _format_band_message(
                rule, value=value, field_label=label, band=current_band,
            )
            # A band may carry its own severity (e.g. recuperación 1–10:
            # "Muy bajo" ≤2 escalates to critical while "Bajo" 3–4 stays a
            # warning) — the rule's severity is just the default.
            band_sev = current_band.get("severity")
            if band_sev in ("info", "warning", "critical"):
                severity = band_sev

        else:
            continue

        # Every warning carries the DATE OF THE READING that fired it —
        # "= 3 cae en banda «Bajo»" is meaningless without knowing when.
        when = timezone.localtime(result.recorded_at).date().isoformat()
        msg = f"{msg} ({when})"

        alert = _upsert_alert(
            player=result.player,
            source_type=AlertSource.THRESHOLD,
            source_id=rule.id,
            severity=severity,
            message=msg,
            source_recorded_at=result.recorded_at,
        )
        fired.append(alert)
    return fired


# ---------------------------------------------------------------------------
# BAND-rule helpers
# ---------------------------------------------------------------------------


def _band_evaluation(
    rule: AlertRule, value: float,
) -> tuple[dict | None, list[dict]]:
    """Return (current_band, alert_band_set) for a BAND-kind rule.

    - `current_band`: the band the value falls into, or None if no band
      covers it (open-ended bands cover the extremes).
    - `alert_band_set`: bands that are configured to fire. When the rule's
      config carries `trigger_labels`, that wins. Otherwise we fall back
      to `exams.bands.alert_bands()` (the reddest-band heuristic).
    """
    field_def = _field_definition(rule)
    ranges = list((field_def or {}).get("reference_ranges") or [])
    if not ranges:
        return None, []

    current_band = _band_for_value(value, ranges)

    cfg = rule.config or {}
    explicit_labels = cfg.get("trigger_labels")
    if isinstance(explicit_labels, list) and explicit_labels:
        wanted = set(explicit_labels)
        alerts = [b for b in ranges if isinstance(b, dict) and b.get("label") in wanted]
    else:
        alerts = _alert_bands(ranges)

    return current_band, alerts


def _field_definition(rule: AlertRule) -> dict | None:
    """Return the raw field-definition dict from the template's schema."""
    schema = rule.template.config_schema or {}
    for f in schema.get("fields", []) or []:
        if isinstance(f, dict) and f.get("key") == rule.field_key:
            return f
    return None


def _format_band_message(
    rule: AlertRule, *, value: float, field_label: str, band: dict,
) -> str:
    """Render the message for a BAND firing. Honors rule.message_template
    with placeholders {value}, {field_label}, {band_label}, {band_min},
    {band_max}; otherwise produces a clean default."""
    placeholders = {
        "value": f"{value:g}",
        "field_label": field_label,
        "band_label": band.get("label") or "",
        "band_min": "" if band.get("min") is None else f"{float(band['min']):g}",
        "band_max": "" if band.get("max") is None else f"{float(band['max']):g}",
    }
    template = rule.message_template or ""
    if template:
        try:
            return template.format(**placeholders)
        except (KeyError, IndexError, ValueError):
            pass  # fall through to default
    label = band.get("label") or "(sin etiqueta)"
    return f"{field_label} = {value:g} cae en banda «{label}»"


def _resolve_band_alert(*, rule_id, player_id) -> None:
    """Mark any active THRESHOLD alert for this (rule, player) as RESOLVED.

    Only used for BAND rules — bound/variation alerts don't auto-resolve
    today (legacy behavior preserved). This is a narrow surgical update
    so the team_alerts widget reflects current state.
    """
    now = timezone.now()
    Alert.objects.filter(
        source_type=AlertSource.THRESHOLD,
        source_id=rule_id,
        player_id=player_id,
        status=AlertStatus.ACTIVE,
    ).update(status=AlertStatus.RESOLVED, dismissed_at=now)


# ---------------------------------------------------------------------------
# Bulk finalize — used by the legacy migration & any one-shot recompute.
# ---------------------------------------------------------------------------


def finalize_threshold_alerts_for_template(template) -> dict:
    """Evaluate threshold rules on the LATEST result per (player, template).

    Designed to be called after a bulk load (legacy migration, fixtures)
    where the post_save signal was suppressed via
    ``goals.signals.suppress_alert_evaluation``. Two effects:

      1. Each player's latest reading is run through every active rule on
         the template. Triggered rules upsert an alert (creating or
         refreshing the message in place).
      2. Any active THRESHOLD alert on this template whose latest reading
         no longer triggers the rule is RESOLVED — so old "Elevado" alerts
         from January don't linger when November's reading is back in
         range.

    Returns a stats dict for logging.
    """
    rules = list(
        AlertRule.objects
        .filter(template=template, is_active=True)
        .select_related("template", "category")
    )
    if not rules:
        return {"template": template.slug, "rules": 0, "fired": 0, "resolved": 0}

    # Latest result per player for this template.
    latest_per_player: dict = {}
    for r in (
        ExamResult.objects
        .filter(template=template)
        .select_related("player")
        .order_by("player_id", "-recorded_at")
    ):
        latest_per_player.setdefault(r.player_id, r)

    # Evaluate the latest reading; collect (rule_id, player_id) pairs that
    # still fire so we know which active alerts to KEEP.
    still_triggered: set[tuple] = set()
    fired_count = 0
    for r in latest_per_player.values():
        for alert in evaluate_threshold_rules_for_result(r):
            still_triggered.add((alert.source_id, alert.player_id))
            fired_count += 1

    # Resolve any active threshold alert on this template's rules whose
    # latest (player, rule) reading is no longer triggering.
    rule_ids = [r.id for r in rules]
    active_now = Alert.objects.filter(
        source_type=AlertSource.THRESHOLD,
        source_id__in=rule_ids,
        status=AlertStatus.ACTIVE,
    ).values_list("id", "source_id", "player_id")

    stale_ids = [
        aid for (aid, src, pid) in active_now
        if (src, pid) not in still_triggered
    ]
    resolved = 0
    if stale_ids:
        resolved = Alert.objects.filter(id__in=stale_ids).update(
            status=AlertStatus.RESOLVED,
            dismissed_at=timezone.now(),
        )

    return {
        "template": template.slug,
        "rules": len(rules),
        "players_evaluated": len(latest_per_player),
        "fired": fired_count,
        "resolved": resolved,
    }


def finalize_threshold_alerts_all() -> list[dict]:
    """Run finalize for every template that has at least one active rule.

    Convenience wrapper for the migration phase + a future
    ``refresh_threshold_alerts`` management command.
    """
    from exams.models import ExamTemplate
    templates = (
        ExamTemplate.objects
        .filter(alert_rules__is_active=True)
        .distinct()
    )
    return [finalize_threshold_alerts_for_template(t) for t in templates]


