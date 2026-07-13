"""Alert rules for the Fatiga Central (CFF) template — clinical policy 2026-07.

Five BAND rules per club that has the `fatiga_central` template:

  * `delta_basal_pct` — CRITICAL when |Δ%| > 5 (the field's two red bands:
    «Alerta (caída ≥5%)» and «Alerta (alza ≥5%)» — both directions).
  * `pr` (Percepción de recuperación, TQR 1-10) — CRITICAL on «Bajo» (1-3),
    WARNING on «Vigilar» (4-6).
  * `ea` (Estado de ánimo, 1-10) — same two rules.

The band boundaries live on the template's `reference_ranges` (single source
of truth — they also color the profile charts); these rules only bind
severity + message to the bands. Evaluated by the standard threshold engine
on every result save / import, with band auto-resolve when a newer reading
lands back in a safe band.

Idempotent: keyed on (template, field_key, kind, trigger_labels). Re-runs
re-assert is_active but preserve admin-tuned severity/messages.

    docker compose exec backend python manage.py seed_fatiga_alert_rules [--no-backfill]
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Player
from exams.models import ExamResult, ExamTemplate
from goals.evaluator import evaluate_threshold_rules_for_result
from goals.models import AlertRule, AlertRuleKind, AlertSeverity

RULES = [
    {
        "field_key": "delta_basal_pct",
        "severity": AlertSeverity.CRITICAL,
        "config": {},  # auto: both ±5% bands carry alert=true
        "message_template": (
            "Fatiga central: CFF media difiere {value}% del basal ({band_label})"
        ),
    },
    {
        "field_key": "pr",
        "severity": AlertSeverity.CRITICAL,
        "config": {"trigger_labels": ["Bajo"]},
        "message_template": "PR (percepción de recuperación) = {value} — zona crítica (1–3)",
    },
    {
        "field_key": "pr",
        "severity": AlertSeverity.WARNING,
        "config": {"trigger_labels": ["Vigilar"]},
        "message_template": "PR (percepción de recuperación) = {value} — zona de vigilancia (4–6)",
    },
    {
        "field_key": "ea",
        "severity": AlertSeverity.CRITICAL,
        "config": {"trigger_labels": ["Bajo"]},
        "message_template": "EA (estado de ánimo) = {value} — zona crítica (1–3)",
    },
    {
        "field_key": "ea",
        "severity": AlertSeverity.WARNING,
        "config": {"trigger_labels": ["Vigilar"]},
        "message_template": "EA (estado de ánimo) = {value} — zona de vigilancia (4–6)",
    },
]


class Command(BaseCommand):
    help = "Seed the Fatiga Central (CFF) alert rules (Δ% vs basal ±5, PR/EA bands) and backfill."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None, help="Restrict to one club.")
        parser.add_argument("--no-backfill", action="store_true",
                            help="Create/refresh rules only; don't evaluate latest results.")

    @transaction.atomic
    def handle(self, *args, **opts):
        templates = ExamTemplate.objects.filter(slug="fatiga_central", is_active_version=True)
        if opts["club"]:
            templates = templates.filter(department__club__name=opts["club"])
        if not templates.exists():
            self.stdout.write(self.style.WARNING("No fatiga_central template found — nothing to do."))
            return

        for template in templates:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n{template.department.club.name} — {template.name}"))
            rules = []
            for spec in RULES:
                labels = (spec["config"] or {}).get("trigger_labels")
                rule = next(
                    (r for r in AlertRule.objects.filter(
                        template=template, field_key=spec["field_key"],
                        kind=AlertRuleKind.BAND, category=None,
                    ) if (r.config or {}).get("trigger_labels") == labels),
                    None,
                )
                if rule is None:
                    rule = AlertRule.objects.create(
                        template=template, field_key=spec["field_key"],
                        kind=AlertRuleKind.BAND, category=None,
                        config=spec["config"], severity=spec["severity"],
                        message_template=spec["message_template"],
                    )
                    action = "created"
                else:
                    # Preserve admin-tuned severity/message; just re-activate.
                    if not rule.is_active:
                        rule.is_active = True
                        rule.save(update_fields=["is_active"])
                    action = "exists"
                rules.append(rule)
                tag = f" {labels}" if labels else ""
                self.stdout.write(f"  {action}: {spec['field_key']}{tag} → {rule.severity}")

            if opts["no_backfill"]:
                continue
            fired = 0
            player_ids = (
                ExamResult.objects.filter(template=template)
                # order_by() clears the model's default ordering, which would
                # otherwise leak recorded_at into DISTINCT and undo it.
                .order_by().values_list("player_id", flat=True).distinct()
            )
            for pid in player_ids:
                latest = (
                    ExamResult.objects.filter(template=template, player_id=pid)
                    .order_by("-recorded_at").first()
                )
                if latest is not None:
                    fired += len(evaluate_threshold_rules_for_result(latest))
            self.stdout.write(self.style.SUCCESS(
                f"  backfill: {len(player_ids)} player(s) evaluated, {fired} alert(s) fired/updated"
            ))
