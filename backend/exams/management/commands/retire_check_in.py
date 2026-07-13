"""Retire the legacy `check_in` wellness template (superseded by
`checkin_fisico`).

The `check_in` data is the 2025 season only (no overlap with the live 2026
`checkin_fisico` feed) and the medical team confirmed it's no longer of
interest — client-approved for deletion. This removes the template and its
dependents in FK-safe order (`ExamResult.template` is PROTECT, so results are
deleted first; TemplateFields + AlertRules cascade with the template).

Dry-run by default — pass --commit to actually delete. Safe to run on dev and
on prod (Railway: pass the POSTGRES_* env vars, since settings ignores
DATABASE_URL for one-offs).

    python manage.py retire_check_in            # dry-run: report only
    python manage.py retire_check_in --commit   # delete
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

SLUG = "check_in"


class Command(BaseCommand):
    help = "Delete the legacy check_in wellness template + its data (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually delete. Without it, only reports what would be removed.",
        )

    def handle(self, *args, **opts):
        from exams.models import Episode, ExamResult, ExamTemplate, TemplateField
        from goals.models import Alert, AlertRule, Goal
        from dashboards.models import TeamReportWidgetDataSource, WidgetDataSource

        templates = list(ExamTemplate.objects.filter(slug=SLUG))
        if not templates:
            self.stdout.write("No `check_in` template found — nothing to do.")
            return

        tids = [t.id for t in templates]
        rule_ids = list(AlertRule.objects.filter(template_id__in=tids).values_list("id", flat=True))

        results = ExamResult.objects.filter(template_id__in=tids)
        fields = TemplateField.objects.filter(template_id__in=tids)
        rules = AlertRule.objects.filter(template_id__in=tids)
        alerts = Alert.objects.filter(source_id__in=list(rule_ids) + list(tids))

        self.stdout.write(f"check_in templates: {len(templates)}")
        self.stdout.write(f"  ExamResults:    {results.count()}  (PROTECT — deleted first)")
        self.stdout.write(f"  TemplateFields: {fields.count()}  (CASCADE)")
        self.stdout.write(f"  AlertRules:     {rules.count()}  (CASCADE)")
        self.stdout.write(f"  Alerts (poly):  {alerts.count()}  (resolved pointers)")

        # Guard: refuse if any PROTECT reference other than ExamResult still
        # points at check_in (would block/orphan a delete). All should be 0.
        blockers = {
            "Episode": Episode.objects.filter(template_id__in=tids).count(),
            "Goal": Goal.objects.filter(template_id__in=tids).count(),
            "WidgetDataSource": WidgetDataSource.objects.filter(template_id__in=tids).count(),
            "TeamReportWidgetDataSource":
                TeamReportWidgetDataSource.objects.filter(template_id__in=tids).count(),
        }
        blocking = {k: v for k, v in blockers.items() if v}
        if blocking:
            self.stderr.write(self.style.ERROR(
                f"Aborting — references still point at check_in: {blocking}. "
                "Repoint or remove them first, then re-run."
            ))
            return

        if not opts["commit"]:
            self.stdout.write(self.style.WARNING("\nDRY-RUN — nothing deleted. Pass --commit to delete."))
            return

        with transaction.atomic():
            n_alerts = alerts.delete()[0]
            n_results = results.delete()[0]
            cascade = ExamTemplate.objects.filter(id__in=tids).delete()

        self.stdout.write(self.style.SUCCESS(
            f"\nDeleted — alerts={n_alerts}, results={n_results}, "
            f"template+cascade={cascade[1]}"
        ))
