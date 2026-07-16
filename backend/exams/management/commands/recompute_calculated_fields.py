"""Recompute calculated fields on EXISTING results.

Backfill after a template's `config_schema` gains or changes a calculated
field (e.g. the GPS per-minute fields `hsr_min`, `sprint_dist_min`, …). Feeds
each result's stored `result_data` back through the formula engine and merges
the (re)computed calculated fields — raw values are untouched, so this is
purely additive/idempotent.

Dry-run by default; pass --commit to write. Safe to re-run.

    python manage.py recompute_calculated_fields --template-slug gps_partido gps_sesion --commit
    python manage.py recompute_calculated_fields --template-slug gps_sesion --club "Universidad de Chile"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

_BATCH = 500


class Command(BaseCommand):
    help = "Recompute calculated fields on existing results for the given templates."

    def add_arguments(self, parser):
        parser.add_argument("--template-slug", nargs="+", required=True,
                            help="One or more template slugs to recompute.")
        parser.add_argument("--club", default=None, help="Restrict to one club (name).")
        parser.add_argument("--commit", action="store_true",
                            help="Write changes (default: dry-run).")

    def handle(self, *args, **opts):
        from exams.models import ExamResult, ExamTemplate
        from exams.calculations import compute_result_data

        commit = opts["commit"]
        qs = ExamTemplate.objects.filter(slug__in=opts["template_slug"]).select_related(
            "department__club"
        )
        if opts["club"]:
            qs = qs.filter(department__club__name=opts["club"])
        templates = list(qs)
        if not templates:
            self.stdout.write("No templates matched — nothing to do.")
            return

        grand_changed = grand_total = 0
        for t in templates:
            calc_keys = [
                f["key"] for f in (t.config_schema or {}).get("fields", []) or []
                if isinstance(f, dict) and f.get("type") == "calculated" and f.get("key")
            ]
            club = t.department.club.name
            if not calc_keys:
                self.stdout.write(f"[{club}] {t.slug}: no calculated fields — skipped.")
                continue

            results = list(ExamResult.objects.filter(template=t).select_related("player"))
            changed = []
            for r in results:
                new_data, new_snap = compute_result_data(t, dict(r.result_data or {}), player=r.player)
                if new_data != (r.result_data or {}):
                    r.result_data = new_data
                    if new_snap:
                        r.inputs_snapshot = new_snap
                    changed.append(r)

            if commit and changed:
                for i in range(0, len(changed), _BATCH):
                    ExamResult.objects.bulk_update(
                        changed[i:i + _BATCH], ["result_data", "inputs_snapshot"]
                    )

            verb = "updated" if commit else "would change"
            self.stdout.write(
                f"[{club}] {t.slug}: {len(changed)}/{len(results)} {verb} "
                f"· calc fields: {', '.join(calc_keys)}"
            )
            grand_changed += len(changed)
            grand_total += len(results)

        verb = "updated" if commit else "would change"
        self.stdout.write(self.style.SUCCESS(f"\nTotal: {grand_changed}/{grand_total} {verb}."))
        if not commit:
            self.stdout.write(self.style.WARNING("DRY-RUN — pass --commit to write."))
