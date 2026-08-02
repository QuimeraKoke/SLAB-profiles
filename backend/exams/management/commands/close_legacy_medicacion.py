"""Close open legacy `medicacion` records by stamping fecha_fin = fecha_inicio.

The 2025 medication history was bulk-imported with no "Fin del tratamiento",
and the active-medication view treats a blank `fecha_fin` as *still running*
(`fecha_inicio <= as_of AND (fecha_fin >= as_of OR blank)`). So year-old
courses kept surfacing as active prescriptions on the team + player layouts.

Closing each row on its own `fecha_inicio` retires them from the active list
while keeping the treatment dates plausible (a same-day course), rather than
implying a multi-month course by closing everything on the import date.

Only rows with a blank/missing `fecha_fin` are touched, so re-running is a
no-op and deliberately open current treatments are never closed. Rows missing
`fecha_inicio` are skipped and reported — there's nothing to close them on.

Updating (rather than creating) fires no side effects: every ExamResult
post_save receiver early-returns on `if not created`.

Examples:
    # Dry run — prints the batch breakdown + samples, writes nothing:
    manage.py close_legacy_medicacion --club "Universidad de Chile"

    # Real run:
    manage.py close_legacy_medicacion --club "Universidad de Chile" --commit

    # Restrict to the legacy import, leaving anything created later alone:
    manage.py close_legacy_medicacion --club "Universidad de Chile" \
        --created-before 2026-06-01 --commit
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from exams.models import ExamResult

SLUG = "medicacion"
START_KEY = "fecha_inicio"
END_KEY = "fecha_fin"


class Command(BaseCommand):
    help = "Close open legacy medicacion records (fecha_fin := fecha_inicio)."

    def add_arguments(self, parser):
        parser.add_argument("--club", required=True,
                            help="Club name (icontains). Scopes via template department.")
        parser.add_argument("--created-before", metavar="YYYY-MM-DD",
                            help="Only rows created strictly before this date. "
                                 "Omit → every open row for the club.")
        parser.add_argument("--commit", action="store_true",
                            help="Write. Without it: dry-run (nothing written).")

    def handle(self, *args, **opts):
        dry_run = not opts["commit"]
        cutoff = None
        if opts["created_before"]:
            try:
                cutoff = date.fromisoformat(opts["created_before"])
            except ValueError as exc:
                raise CommandError(f"--created-before must be YYYY-MM-DD: {exc}")

        qs = ExamResult.objects.filter(
            template__slug=SLUG,
            template__department__club__name__icontains=opts["club"],
        ).select_related("player", "template")
        if cutoff is not None:
            qs = qs.filter(created_at__date__lt=cutoff)

        # `fecha_fin` blank OR key absent both mean "open". Filter in Python:
        # a JSONB key-missing test is awkward in the ORM and the set is small.
        open_rows, closable, no_start = [], [], []
        for r in qs.iterator():
            data = r.result_data or {}
            if str(data.get(END_KEY) or "").strip():
                continue
            open_rows.append(r)
            (closable if str(data.get(START_KEY) or "").strip() else no_start).append(r)

        if not open_rows:
            self.stdout.write(self.style.SUCCESS("No open medicacion rows — nothing to do."))
            return

        batches = Counter(r.created_at.date().isoformat() for r in open_rows)
        self.stdout.write(
            f"Open rows: {len(open_rows)}  "
            f"(closable: {len(closable)}, missing {START_KEY}: {len(no_start)})"
        )
        self.stdout.write("By creation date:")
        for day, n in sorted(batches.items()):
            self.stdout.write(f"    {day}  {n}")

        self.stdout.write("Samples:")
        for r in closable[:5]:
            d = r.result_data
            self.stdout.write(
                f"    {r.player.first_name} {r.player.last_name}: "
                f"{d.get('medicamento')!r}  {d[START_KEY]} → fin {d[START_KEY]}"
            )
        for r in no_start[:5]:
            self.stdout.write(self.style.WARNING(
                f"    SKIP (no {START_KEY}): {r.player.first_name} "
                f"{r.player.last_name} {r.result_data.get('medicamento')!r}"
            ))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — would close {len(closable)} row(s). Re-run with --commit."
            ))
            return

        with transaction.atomic():
            for r in closable:
                r.result_data[END_KEY] = r.result_data[START_KEY]
                r.save(update_fields=["result_data"])

        self.stdout.write(self.style.SUCCESS(f"\nClosed {len(closable)} row(s)."))
        if no_start:
            self.stdout.write(self.style.WARNING(
                f"Left {len(no_start)} row(s) open — no {START_KEY} to close them on."
            ))
