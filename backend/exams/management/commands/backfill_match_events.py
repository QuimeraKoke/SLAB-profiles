"""Link orphan ExamResults to match Events, or create synthetic events.

Runs over every ExamTemplate flagged `link_to_match=True` and looks for
ExamResult rows on that template with `event=None`. For each orphan,
the command:

1. Tries to find an existing match Event in the same category whose
   `starts_at` falls within ±N days of the result's `recorded_at`. The
   closest match wins.
2. If none found AND `--create-synthetic` is set, creates a synthetic
   match Event for that date with a generic title (e.g. "Partido
   sintético — 2026-04-15") so the result has somewhere to live.
3. If none found and `--create-synthetic` is NOT set, the result is
   left orphan and reported in the summary.

Idempotent: results already linked are skipped untouched.

Examples:
    docker compose exec backend python manage.py backfill_match_events
    docker compose exec backend python manage.py backfill_match_events \\
        --create-synthetic --window-days 2 --dry-run
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Category
from events.models import Event
from exams.models import ExamResult, ExamTemplate


class Command(BaseCommand):
    help = (
        "Link orphan ExamResults on link_to_match templates to existing "
        "match Events (within ±N days), optionally creating synthetic ones."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would happen, but don't write.")
        parser.add_argument("--window-days", type=int, default=3,
                            help="Match window in days. Default: 3.")
        parser.add_argument("--create-synthetic", action="store_true",
                            help=(
                                "When no existing Event matches, create a "
                                "synthetic one for the result's recorded_at."
                            ))

    def handle(self, *args, **opts):
        dry_run = bool(opts["dry_run"])
        window = max(1, int(opts["window_days"]))
        create_synthetic = bool(opts["create_synthetic"])

        templates = list(ExamTemplate.objects.filter(link_to_match=True))
        if not templates:
            self.stdout.write(self.style.WARNING(
                "No templates with link_to_match=True. Nothing to do."
            ))
            return

        family_ids = {t.family_id for t in templates}
        orphans = list(
            ExamResult.objects
            .filter(template__family_id__in=family_ids, event__isnull=True)
            .select_related("template", "player", "player__category")
        )
        self.stdout.write(
            f"Templates en scope: {len(templates)}. "
            f"Resultados huérfanos: {len(orphans)}."
        )
        if not orphans:
            return

        linked = 0
        synthetic = 0
        still_orphan = 0

        # Group by (category_id, department_id) so we can prefetch
        # candidate matches in batches.
        for result in orphans:
            category = result.player.category
            if category is None:
                still_orphan += 1
                continue
            ref_dt = result.recorded_at
            lower = ref_dt - timedelta(days=window)
            upper = ref_dt + timedelta(days=window)

            # Find best candidate by absolute time delta.
            candidates = (
                Event.objects
                .filter(
                    event_type=Event.TYPE_MATCH,
                    club_id=category.club_id,
                    category_id=category.id,
                    starts_at__gte=lower,
                    starts_at__lte=upper,
                )
            )
            best = None
            best_delta = None
            for ev in candidates:
                delta = abs((ev.starts_at - ref_dt).total_seconds())
                if best is None or delta < best_delta:
                    best = ev
                    best_delta = delta

            if best is not None:
                if not dry_run:
                    result.event = best
                    result.save(update_fields=["event"])
                linked += 1
                continue

            if create_synthetic:
                if not dry_run:
                    department = result.template.department
                    title = f"Partido sintético — {ref_dt:%Y-%m-%d}"
                    syn = Event.objects.create(
                        club_id=category.club_id,
                        department=department,
                        event_type=Event.TYPE_MATCH,
                        title=title,
                        starts_at=ref_dt,
                        scope=Event.SCOPE_CATEGORY,
                        category=category,
                        metadata={"synthetic": True, "source": "backfill_match_events"},
                    )
                    result.event = syn
                    result.save(update_fields=["event"])
                synthetic += 1
                linked += 1
                continue

            still_orphan += 1

        self.stdout.write(self.style.SUCCESS(
            f"Linked: {linked} (incluyendo {synthetic} sintéticos). "
            f"Quedan huérfanos: {still_orphan}."
        ))
