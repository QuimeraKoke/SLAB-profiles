"""Player-scoped objectives + alerts.

`Goal` is a first-class, mutable record (NOT an ExamResult): "for player X,
the value of (template T, field K) should satisfy operator OP target T by
due_date D". The evaluator (see `evaluator.py`) walks active goals and
flips status to met / missed, optionally creating an `Alert`.

`Alert` is intentionally generic: today only `source_type='goal'` is fired,
but threshold-based alerts (PRD §6.1) plug into the same table later.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from core.models import Player
from exams.models import ExamTemplate


class GoalOperator(models.TextChoices):
    LTE = "<=", "≤"
    LT = "<", "<"
    EQ = "==", "="
    GTE = ">=", "≥"
    GT = ">", ">"


class GoalStatus(models.TextChoices):
    ACTIVE = "active", "Activo"
    MET = "met", "Cumplido"
    MISSED = "missed", "No cumplido"
    CANCELLED = "cancelled", "Cancelado"


class Goal(models.Model):
    """An objective to be evaluated against a player's exam reading."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="goals")
    template = models.ForeignKey(
        ExamTemplate, on_delete=models.PROTECT, related_name="goals"
    )
    field_key = models.CharField(
        max_length=80,
        help_text="The key from template.config_schema['fields'][].key to evaluate.",
    )
    operator = models.CharField(max_length=2, choices=GoalOperator.choices)
    target_value = models.FloatField()
    due_date = models.DateField()
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=12,
        choices=GoalStatus.choices,
        default=GoalStatus.ACTIVE,
    )
    last_value = models.FloatField(
        null=True, blank=True,
        help_text="The player's value at the last evaluation. Null if no reading existed.",
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    warn_days_before = models.PositiveIntegerField(
        null=True, blank=True, default=7,
        help_text=(
            "Fire a pre-deadline warning alert when due_date is within this "
            "many days AND the goal isn't currently met. Leave blank / 0 "
            "to disable warnings for this goal. Default: 7."
        ),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_goals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-due_date", "-created_at")
        indexes = [
            models.Index(fields=["status", "due_date"]),
            models.Index(fields=["player", "status"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.player} · {self.field_key} {self.operator} "
            f"{self.target_value} by {self.due_date} ({self.get_status_display()})"
        )


class AlertSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Advertencia"
    CRITICAL = "critical", "Crítico"


class AlertStatus(models.TextChoices):
    ACTIVE = "active", "Activa"
    DISMISSED = "dismissed", "Descartada"
    RESOLVED = "resolved", "Resuelta"


class AlertSource(models.TextChoices):
    GOAL = "goal", "Objetivo (vencimiento)"
    GOAL_WARNING = "goal_warning", "Objetivo (aviso pre-vencimiento)"
    THRESHOLD = "threshold", "Umbral"  # reserved for the alarms engine
    MEDICATION = "medication", "Medicación (WADA)"


class Alert(models.Model):
    """A per-player notification raised by the evaluator engine.

    `source_type` + `source_id` is a polymorphic pointer back to whatever
    raised the alert (a Goal today; a Threshold rule tomorrow).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="alerts")
    source_type = models.CharField(max_length=20, choices=AlertSource.choices)
    source_id = models.UUIDField(
        help_text="UUID of the source row (Goal.id, Threshold.id, …)."
    )
    severity = models.CharField(
        max_length=10, choices=AlertSeverity.choices, default=AlertSeverity.WARNING
    )
    status = models.CharField(
        max_length=10, choices=AlertStatus.choices, default=AlertStatus.ACTIVE
    )
    message = models.TextField()
    fired_at = models.DateTimeField(auto_now_add=True)
    last_fired_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "Most-recent firing of the source rule. Equal to `fired_at` for "
            "single-fire alerts (goals); refreshed each time a threshold rule "
            "re-triggers while the alert is still active."
        ),
    )
    trigger_count = models.PositiveIntegerField(
        default=1,
        help_text=(
            "How many times the source rule has triggered since this alert was "
            "raised. Resets to 1 when a new alert is created (after dismissal)."
        ),
    )
    dismissed_at = models.DateTimeField(null=True, blank=True)
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dismissed_alerts",
    )

    class Meta:
        ordering = ("-fired_at",)
        indexes = [
            models.Index(fields=["player", "status"]),
            models.Index(fields=["source_type", "source_id"]),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.player} · {self.message[:60]}"


class AlertRuleKind(models.TextChoices):
    BOUND = "bound", "Límite (umbral fijo)"
    VARIATION = "variation", "Variación (% vs. ventana)"
    BAND = "band", "Banda de referencia (clínica)"


class AlertRule(models.Model):
    """A configured rule that raises a threshold-driven Alert when a new
    ExamResult satisfies it.

    Three kinds:
      * `bound` — `config = {"upper": <num>?, "lower": <num>?}`. Either side
        optional; the engine fires when `value > upper` OR `value < lower`.
      * `variation` — `config = {"window": {"kind": "last_n", "n": int} | {"kind": "timedelta", "days": int},
                                 "threshold_pct": <num>?, "threshold_units": <num>?,
                                 "direction": "any"|"increase"|"decrease"}`.
        Engine fetches the matching window of prior readings, computes mean,
        fires when **either** |(value - mean) / mean * 100| ≥ threshold_pct
        OR |value - mean| ≥ threshold_units (respecting the direction
        filter). At least one threshold must be set; both can be set
        together (logical OR).
      * `band` — `config = {}` (empty) or `{"trigger_labels": [str, ...]}`.
        The engine resolves the field's `reference_ranges` to find the
        alert band(s) via `exams.bands.alert_bands()` (reddest-band
        heuristic with explicit overrides). When `trigger_labels` is set,
        only bands whose label appears in the list trigger — overrides
        the heuristic entirely. The rule auto-resolves a previously-fired
        Alert when a newer reading lands outside the alert band(s).

    `category` (nullable) lets you scope a rule to one category — e.g. CK
    threshold of 1500 for adults vs 1000 for U-21. Null means "applies to
    every category that uses this template".

    Field references match the existing pattern (`Goal.field_key`,
    `WidgetDataSource.field_keys`): a string validated against the
    template's `config_schema['fields']` in `clean()`. NOT an FK to
    `TemplateField` because those rows get regenerated on every admin save.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        "exams.ExamTemplate", on_delete=models.CASCADE, related_name="alert_rules",
    )
    field_key = models.CharField(
        max_length=80,
        help_text="Key from the template's config_schema fields. Must be numeric or calculated.",
    )
    category = models.ForeignKey(
        "core.Category", on_delete=models.CASCADE, null=True, blank=True,
        related_name="alert_rules",
        help_text="Restrict to one category. Empty = applies to every category that uses this template.",
    )
    kind = models.CharField(max_length=12, choices=AlertRuleKind.choices)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'bound: {"upper": float?, "lower": float?}. '
            'variation: {"window": {"kind":"last_n","n":int} or {"kind":"timedelta","days":int}, '
            '"threshold_pct": float?, "threshold_units": float?, '
            '"direction": "any"|"increase"|"decrease"} — at least one threshold required. '
            'band: {} (auto-detect alert band via color heuristic) or '
            '{"trigger_labels": ["Elevado", ...]} to fire on specific bands.'
        ),
    )
    severity = models.CharField(
        max_length=10, choices=AlertSeverity.choices, default=AlertSeverity.WARNING,
    )
    message_template = models.CharField(
        max_length=300, blank=True,
        help_text=(
            "Plantilla del mensaje. Placeholders: {value}, {field_label}, "
            "{upper}, {lower}, {baseline}, {pct_change}, {direction}, "
            "{window_desc}. Si está vacío, se autogenera."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_alert_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("template__name", "field_key", "kind")
        indexes = [
            models.Index(fields=["template", "is_active"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        # field_key must exist in the template's config_schema.
        if self.template_id and self.field_key:
            schema = self.template.config_schema or {}
            fields = schema.get("fields") or []
            target = next(
                (f for f in fields
                 if isinstance(f, dict) and f.get("key") == self.field_key),
                None,
            )
            if target is None:
                valid = sorted(
                    f.get("key") for f in fields
                    if isinstance(f, dict) and f.get("key")
                )
                raise ValidationError({
                    "field_key": (
                        f"Unknown field on template '{self.template.name}'. "
                        f"Available: {', '.join(valid) or '(none)'}"
                    )
                })
            if target.get("type") not in {"number", "calculated"}:
                raise ValidationError({
                    "field_key": (
                        f"Alert rules only apply to numeric/calculated fields; "
                        f"'{self.field_key}' is type '{target.get('type')}'."
                    )
                })

        # Category and template must share a club; the category should opt in.
        if self.category_id and self.template_id:
            if self.category.club_id != self.template.department.club_id:
                raise ValidationError({
                    "category": "Category and template must belong to the same club."
                })
            if not self.template.applicable_categories.filter(pk=self.category_id).exists():
                raise ValidationError({
                    "category": (
                        f"Template '{self.template.name}' is not applicable to "
                        f"category '{self.category.name}'."
                    )
                })

        # Per-kind config validation.
        cfg = self.config or {}
        if self.kind == AlertRuleKind.BOUND:
            upper = cfg.get("upper")
            lower = cfg.get("lower")
            if upper is None and lower is None:
                raise ValidationError({"config": "bound rule requires at least one of 'upper' or 'lower'."})
            for k in ("upper", "lower"):
                v = cfg.get(k)
                if v is not None:
                    try:
                        float(v)
                    except (TypeError, ValueError):
                        raise ValidationError({"config": f"'{k}' must be numeric."})
            if upper is not None and lower is not None and float(upper) <= float(lower):
                raise ValidationError({"config": "'upper' must be greater than 'lower'."})

        elif self.kind == AlertRuleKind.VARIATION:
            window = cfg.get("window") or {}
            wkind = window.get("kind")
            if wkind == "last_n":
                n = window.get("n")
                if not isinstance(n, int) or n < 1:
                    raise ValidationError({"config": "variation.window.n must be an integer ≥ 1."})
            elif wkind == "timedelta":
                days = window.get("days")
                if not isinstance(days, int) or days < 1:
                    raise ValidationError({"config": "variation.window.days must be an integer ≥ 1."})
            else:
                raise ValidationError({
                    "config": "variation.window.kind must be 'last_n' or 'timedelta'."
                })

            pct = cfg.get("threshold_pct")
            units = cfg.get("threshold_units")
            if pct is None and units is None:
                raise ValidationError({
                    "config": "variation requires at least one of 'threshold_pct' or 'threshold_units'."
                })
            for label, raw in (("threshold_pct", pct), ("threshold_units", units)):
                if raw is None:
                    continue
                try:
                    n = float(raw)
                except (TypeError, ValueError):
                    raise ValidationError({"config": f"variation.{label} must be numeric."})
                if n <= 0:
                    raise ValidationError({"config": f"variation.{label} must be > 0."})

            direction = cfg.get("direction", "any")
            if direction not in {"any", "increase", "decrease"}:
                raise ValidationError({
                    "config": "variation.direction must be 'any', 'increase', or 'decrease'."
                })

        elif self.kind == AlertRuleKind.BAND:
            # The only configurable knob is an optional list of band labels
            # that override the reddest-band heuristic. Empty config = use
            # heuristic, which is the common case.
            labels = cfg.get("trigger_labels")
            if labels is not None:
                if not isinstance(labels, list) or not all(
                    isinstance(x, str) and x for x in labels
                ):
                    raise ValidationError({
                        "config": (
                            "band.trigger_labels must be a list of non-empty "
                            "band labels (e.g. [\"Elevado\"])."
                        )
                    })
            # Also surface the upfront error if the bound field has no
            # reference_ranges configured — otherwise the rule would silently
            # never fire and confuse the admin.
            if self.template_id and self.field_key:
                schema = self.template.config_schema or {}
                for f in schema.get("fields", []) or []:
                    if isinstance(f, dict) and f.get("key") == self.field_key:
                        if not (f.get("reference_ranges") or []):
                            raise ValidationError({
                                "field_key": (
                                    f"Field '{self.field_key}' has no "
                                    "reference_ranges configured — band "
                                    "rules require them. Add ranges on the "
                                    "template, or use a bound rule instead."
                                )
                            })
                        break

    def __str__(self) -> str:
        scope = self.category.name if self.category_id else "(all categories)"
        return f"{self.template.name}.{self.field_key} · {self.get_kind_display()} · {scope}"
