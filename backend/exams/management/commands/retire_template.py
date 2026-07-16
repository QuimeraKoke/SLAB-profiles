"""Retire (delete) an exam template + its data, in FK-safe order.

Generic sibling of `retire_check_in`. Use for legacy/duplicate templates whose
data is redundant (e.g. a superseded GPS template fully mirrored by the unified
one). Deletes ExamResults first (ExamResult.template is PROTECT), then the
template (TemplateFields + AlertRules cascade); resolves polymorphic Alert
pointers. ABORTS if any other PROTECT reference (Episode / Goal / widget data
source) still points at the template — repoint those first.

Dry-run by default; pass --commit to delete. On Railway pass the POSTGRES_*
env vars (settings ignores DATABASE_URL for one-offs).

    python manage.py retire_template --slug gps_rendimiento_fisico_de_partido
    python manage.py retire_template --slug gps_rendimiento_fisico_de_partido --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Delete an exam template + its data (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Template slug to retire.")
        parser.add_argument("--club", default=None, help="Restrict to one club (name).")
        parser.add_argument("--commit", action="store_true",
                            help="Actually delete. Without it, only reports.")

    def handle(self, *args, **opts):
        from exams.models import Episode, ExamResult, ExamTemplate, TemplateField
        from goals.models import Alert, AlertRule, Goal
        from dashboards.models import TeamReportWidgetDataSource, WidgetDataSource

        slug = opts["slug"]
        tqs = ExamTemplate.objects.filter(slug=slug).select_related("department__club")
        if opts["club"]:
            tqs = tqs.filter(department__club__name=opts["club"])
        templates = list(tqs)
        if not templates:
            self.stdout.write(f"No template with slug '{slug}' found — nothing to do.")
            return

        tids = [t.id for t in templates]
        rule_ids = list(AlertRule.objects.filter(template_id__in=tids).values_list("id", flat=True))
        results = ExamResult.objects.filter(template_id__in=tids)
        fields = TemplateField.objects.filter(template_id__in=tids)
        rules = AlertRule.objects.filter(template_id__in=tids)
        alerts = Alert.objects.filter(source_id__in=list(rule_ids) + list(tids))

        for t in templates:
            self.stdout.write(f"{t.department.club.name} · {slug} (v{t.version})")
        self.stdout.write(f"  ExamResults:    {results.count()}  (PROTECT — deleted first)")
        self.stdout.write(f"  TemplateFields: {fields.count()}  (CASCADE)")
        self.stdout.write(f"  AlertRules:     {rules.count()}  (CASCADE)")
        self.stdout.write(f"  Alerts (poly):  {alerts.count()}  (resolved pointers)")

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
                f"Aborting — PROTECT references still point at '{slug}': {blocking}. "
                "Repoint or remove them first, then re-run."
            ))
            return

        # Cross-exam formula references: warn if another template's formulas
        # read [<slug>.field] — deleting would break those formulas.
        refd_by = [
            other.slug for other in ExamTemplate.objects.exclude(id__in=tids)
            if f"[{slug}." in str(other.config_schema)
        ]
        if refd_by:
            self.stderr.write(self.style.ERROR(
                f"Aborting — these templates reference '{slug}' in formulas: {refd_by}. "
                "Update those formulas first."
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
