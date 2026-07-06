"""Re-apply WADA medication alerts to EXISTING results after a config change.

The post-save signal (`exams.signals.medication_wada_alert_on_result_save`)
only fires on creation, so editing the `Medicación` template's risk map (e.g.
re-running `seed_medicacion_template` from a corrected medicamentos.csv) does
NOT retroactively fix alerts already raised from older results.

This command walks every medication result and reconciles its alert against
the CURRENT template config, using the same `medication_alert_payload` the
signal uses:

  - PROHIBIDO / CONDICIONAL → upsert the alert (updates message + severity
    in place via `_upsert_alert`, or creates it if missing).
  - PERMITIDO / no longer flagged → resolve any stale ACTIVE alert, so a
    medicine that was mis-flagged stops alerting.

Idempotent. Run after `seed_medicacion_template`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from exams.models import ExamResult
from exams.signals import medication_alert_payload
from goals.evaluator import _upsert_alert
from goals.models import Alert, AlertSource, AlertStatus


class Command(BaseCommand):
    help = "Reconcile WADA medication alerts with the current template config."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug", default="medicacion",
            help="Template slug to reconcile (default: medicacion).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **opts):
        slug = opts["slug"]
        dry = opts["dry_run"]

        results = (
            ExamResult.objects
            .filter(template__slug=slug)
            .select_related("player", "template")
        )

        upserted = resolved = silent = 0
        for r in results:
            payload = medication_alert_payload(r.template, r.result_data, r.recorded_at)
            existing = Alert.objects.filter(
                source_type=AlertSource.MEDICATION,
                source_id=r.id,
                player=r.player,
                status=AlertStatus.ACTIVE,
            ).first()

            if payload is not None:
                severity, message = payload
                if not dry:
                    _upsert_alert(
                        player=r.player,
                        source_type=AlertSource.MEDICATION,
                        source_id=r.id,
                        severity=severity,
                        message=message,
                    )
                upserted += 1
            elif existing is not None:
                # No longer flagged (e.g. reclassified to PERMITIDO) — retire
                # the stale alert instead of leaving a wrong one active.
                if not dry:
                    existing.status = AlertStatus.RESOLVED
                    existing.save(update_fields=["status"])
                resolved += 1
            else:
                silent += 1

        verb = "Would" if dry else "Reconciled"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {upserted} flagged (upserted), {resolved} stale resolved, "
            f"{silent} permitido/no-op · over {results.count()} '{slug}' results."
        ))
