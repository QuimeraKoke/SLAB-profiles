"""Backfill computed fields (IMC, masa_muscular, etc.) on ExamResults that were
created by the legacy migration without running the formula engine.

Usage:
    python manage.py backfill_calculated_fields --club "Universidad de Chile"
    python manage.py backfill_calculated_fields --template-slug pentacompartimental
    python manage.py backfill_calculated_fields --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from exams.calculations import compute_result_data
from exams.models import ExamResult


class Command(BaseCommand):
    help = "Recompute calculated fields (formulas) for migrated ExamResults"

    def add_arguments(self, parser):
        parser.add_argument(
            "--club",
            default="Universidad de Chile",
            help="Club name filter (default: Universidad de Chile)",
        )
        parser.add_argument(
            "--template-slug",
            default=None,
            help="Limit to one template slug (default: all templates with calculated fields)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show counts without writing anything",
        )

    def handle(self, *args, **options):
        club_name = options["club"]
        slug_filter = options["template_slug"]
        dry_run = options["dry_run"]

        qs = (
            ExamResult.objects
            .filter(template__department__club__name=club_name)
            .select_related("player", "template")
            .order_by("template__slug", "recorded_at")
        )
        if slug_filter:
            qs = qs.filter(template__slug=slug_filter)

        # Cache per-template whether it has calculated fields.
        _has_calc: dict[int, bool] = {}

        def _template_has_calc(tpl) -> bool:
            if tpl.id not in _has_calc:
                fields = (tpl.config_schema or {}).get("fields", []) or []
                _has_calc[tpl.id] = any(
                    isinstance(f, dict) and f.get("type") == "calculated"
                    for f in fields
                )
            return _has_calc[tpl.id]

        updated = skipped = errors = 0
        current_slug = None

        for er in qs.iterator(chunk_size=500):
            tpl = er.template
            if not _template_has_calc(tpl):
                skipped += 1
                continue

            if tpl.slug != current_slug:
                current_slug = tpl.slug
                self.stdout.write(f"  template: {tpl.slug}")

            try:
                new_data, snapshot = compute_result_data(tpl, er.result_data or {}, player=er.player)
                if not dry_run:
                    er.result_data = new_data
                    er.inputs_snapshot = snapshot
                    er.save(update_fields=["result_data", "inputs_snapshot"])
                updated += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                self.stderr.write(f"    ERROR result {er.id}: {exc}")

        mode = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            f"{mode}done — updated: {updated}, no-calc-fields: {skipped}, errors: {errors}"
        )
