"""(Re)compute the microcycle-day label (`md_label`) on GPS results (§1.e).

Run after backfilling GPS sessions or after the fixture calendar changes, so
microcycle-scoped alert rules ("solo en MD-1") see up-to-date labels. Reads
the training template by default; pass --template-slug to widen.

    docker compose exec backend python manage.py backfill_md_labels \\
        [--club "Universidad de Chile"] [--template-slug gps_sesion] [--dry-run]
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from exams.microcycle import apply_md_labels
from exams.models import ExamResult


class Command(BaseCommand):
    help = "Recompute md_label (microcycle day) on GPS results from the match calendar."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--template-slug", default="gps_sesion")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        qs = (
            ExamResult.objects
            .filter(template__slug=opts["template_slug"],
                    template__department__club__name=opts["club"])
            .select_related("player")
            .order_by("recorded_at")
        )
        results = list(qs)
        changed = apply_md_labels(results)

        dist = Counter((r.result_data or {}).get("md_label") for r in results)
        if not opts["dry_run"] and changed:
            ExamResult.objects.bulk_update(changed, ["result_data"], batch_size=400)

        mode = "[DRY RUN] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{mode}{opts['template_slug']} @ {opts['club']}: "
            f"{len(results)} results, {len(changed)} relabelled."
        ))
        for label, n in sorted(dist.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            self.stdout.write(f"  {label or '(sin etiqueta)'}: {n}")
