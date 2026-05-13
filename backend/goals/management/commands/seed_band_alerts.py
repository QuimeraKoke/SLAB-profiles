"""Seed BAND alert rules + backfill current alerts.

What it does, in order:

1. Walks every ExamTemplate (the active version of each family by default)
   and inspects each declared `reference_ranges` field. For fields whose
   bands include at least one "alert" band — detected by the heuristic in
   `exams.bands.alert_bands()` (reddest-band wins, with explicit
   `alert: true/false` overrides) — it creates an `AlertRule(kind=BAND)`
   tied to (template, field_key) and `category=None` (applies to every
   category that uses the template). Severity defaults to CRITICAL.

2. Idempotency: re-running the command never duplicates rules. We key on
   `(template_id, field_key, kind=BAND, category=None)`. If a matching
   rule already exists, we leave the admin's custom severity /
   message_template alone. Only `is_active` is re-asserted to True
   (since the field still has alert bands).

3. Backfill: for every player who has at least one ExamResult on each
   rule's template, we fetch their *latest* result and run it through
   `evaluate_threshold_rules_for_result`. This populates the Alert table
   with the CURRENT state — no historical noise. The auto-resolve path
   in the evaluator handles the "value is now safe" case.

Edge cases handled:
- Fields with bands but no reddish color: skipped. The heuristic returns
  an empty list → no rule created. Admin can add `alert: true` explicitly.
- Templates with no `applicable_categories`: skipped (we have nothing to
  backfill).
- Older template versions in a family: not touched by default. Pass
  `--include-all-versions` to seed rules on every version. Useful if
  you're forking templates frequently and need rules on every version.
"""
from __future__ import annotations

from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from core.models import Player
from exams.bands import alert_bands
from exams.models import ExamResult, ExamTemplate
from goals.evaluator import evaluate_threshold_rules_for_result
from goals.models import AlertRule, AlertRuleKind, AlertSeverity


class Command(BaseCommand):
    help = (
        "Seed BAND alert rules for every numeric/calculated field that has "
        "reference_ranges including an alert-worthy band, then fire/resolve "
        "alerts based on each player's latest result."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would happen, but don't write rules or fire alerts.",
        )
        parser.add_argument(
            "--include-all-versions", action="store_true",
            help=(
                "Seed rules on every template version (not just the active "
                "one). Useful when older versions still receive results."
            ),
        )
        parser.add_argument(
            "--no-backfill", action="store_true",
            help="Create / update rules only; skip the historical alert backfill.",
        )
        parser.add_argument(
            "--severity",
            default=AlertSeverity.CRITICAL,
            choices=[s.value for s in AlertSeverity],
            help="Default severity for newly-created rules (default: critical).",
        )

    # ----------------------------------------------------------------------

    def handle(self, *args, **opts):
        dry_run = bool(opts["dry_run"])
        all_versions = bool(opts["include_all_versions"])
        no_backfill = bool(opts["no_backfill"])
        default_severity = opts["severity"]

        template_qs = ExamTemplate.objects.all()
        if not all_versions:
            template_qs = template_qs.filter(is_active_version=True)
        template_qs = template_qs.select_related("department")

        rules_created = 0
        rules_updated = 0
        rules_reactivated = 0
        rules_deactivated = 0
        fields_skipped_no_alert_band = 0
        templates_seen = 0

        for template in template_qs.iterator():
            templates_seen += 1
            schema = template.config_schema or {}
            for field_def in (schema.get("fields") or []):
                if not isinstance(field_def, dict):
                    continue
                key = field_def.get("key")
                ftype = field_def.get("type")
                ranges = field_def.get("reference_ranges") or []
                if not key or ftype not in {"number", "calculated"}:
                    continue
                if not ranges:
                    continue

                detected = alert_bands(ranges)
                if not detected:
                    fields_skipped_no_alert_band += 1
                    # If a rule was previously seeded but the bands now
                    # have no alert band (admin removed the red color),
                    # deactivate it so it stops firing.
                    if not dry_run:
                        n = AlertRule.objects.filter(
                            template=template,
                            field_key=key,
                            kind=AlertRuleKind.BAND,
                            category=None,
                            is_active=True,
                        ).update(is_active=False)
                        rules_deactivated += n
                    continue

                # Upsert the rule. Default severity / empty message only on
                # creation; preserve admin edits on updates.
                if dry_run:
                    exists = AlertRule.objects.filter(
                        template=template,
                        field_key=key,
                        kind=AlertRuleKind.BAND,
                        category=None,
                    ).exists()
                    if exists:
                        rules_updated += 1
                    else:
                        rules_created += 1
                    continue

                rule, created = AlertRule.objects.get_or_create(
                    template=template,
                    field_key=key,
                    kind=AlertRuleKind.BAND,
                    category=None,
                    defaults={
                        "config": {},
                        "severity": default_severity,
                        "message_template": "",
                        "is_active": True,
                    },
                )
                if created:
                    rules_created += 1
                else:
                    # Re-assert is_active=True without touching severity /
                    # message_template / config so admin edits survive.
                    if not rule.is_active:
                        rule.is_active = True
                        rule.save(update_fields=["is_active", "updated_at"])
                        rules_reactivated += 1
                    rules_updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Templates inspected: {templates_seen}"
        ))
        self.stdout.write(
            f"Rules created: {rules_created} · updated: {rules_updated} · "
            f"reactivated: {rules_reactivated} · deactivated: {rules_deactivated}"
        )
        self.stdout.write(
            f"Fields with bands but no alert color: {fields_skipped_no_alert_band}"
        )

        if no_backfill or dry_run:
            self.stdout.write("(skipping backfill)")
            return

        # ------------ Backfill ----------------------------------------------

        summary = self._backfill_active_alerts()
        self.stdout.write(self.style.SUCCESS(
            f"Backfill: evaluated {summary['evaluated']} (player × rule) "
            f"latest results; {summary['alerts_active_after']} alerts now active."
        ))

    # ----------------------------------------------------------------------

    def _backfill_active_alerts(self) -> dict:
        """For every active BAND rule × player that uses the rule's template,
        evaluate the player's latest result. The evaluator's existing
        idempotency + auto-resolve do the rest.
        """
        rules = (
            AlertRule.objects
            .filter(kind=AlertRuleKind.BAND, is_active=True)
            .select_related("template")
        )

        evaluated = 0
        for rule in rules:
            # Scope players to those whose category uses the template, and
            # who have at least one result on it. We evaluate ONLY the
            # latest result per player — historical noise stays out.
            applicable_category_ids = list(
                rule.template.applicable_categories.values_list("id", flat=True)
            )
            if not applicable_category_ids:
                continue

            player_ids = (
                Player.objects
                .filter(category_id__in=applicable_category_ids, is_active=True)
                .values_list("id", flat=True)
            )
            for pid in player_ids:
                latest = (
                    ExamResult.objects
                    .filter(template_id=rule.template_id, player_id=pid)
                    .order_by("-recorded_at")
                    .first()
                )
                if latest is None:
                    continue
                evaluate_threshold_rules_for_result(latest)
                evaluated += 1

        from goals.models import Alert, AlertStatus
        alerts_active_after = Alert.objects.filter(
            status=AlertStatus.ACTIVE,
            source_type="threshold",
        ).count()

        return {
            "evaluated": evaluated,
            "alerts_active_after": alerts_active_after,
        }
