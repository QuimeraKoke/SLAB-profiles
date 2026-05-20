"""Wipe the SLAB tables that the legacy migrator writes into.

Use this BEFORE re-running `migrate_legacy_data` when you want a clean
baseline (e.g. dev/test fixtures cluttered the DB and you want to see
only what the migration produced).

What stays:
  - auth_*, django_*, contenttypes, sessions
  - Club, Department, Category, Position (reference data the migrator
    LINKS to rather than recreates)
  - ExamTemplate + TemplateField + options (seeded templates)
  - User (staff accounts)

What gets wiped (in FK-safe order):
  exams.ExamResult  →  PROTECTs Episode, so must go first
  exams.Episode
  events.EventParticipant
  events.Event
  core.Contract
  core.Player          →  cascades to goals.Goal/Alert + core.PlayerAlias

Defaults to dry-run so an accidental invocation is a no-op. Pass
`--confirm` to actually delete.

Examples:

    # what would be deleted (safe to run any time):
    python manage.py wipe_legacy_target

    # actually wipe:
    python manage.py wipe_legacy_target --confirm

    # only wipe data for one club:
    python manage.py wipe_legacy_target --club 'Universidad de Chile' --confirm
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Club, Contract, Player
from events.models import Event, EventParticipant
from exams.models import Episode, ExamResult


# Order matters — children before parents to avoid PROTECT violations.
WIPE_PLAN: list[tuple[str, type]] = [
    ("exams.ExamResult", ExamResult),
    ("exams.Episode", Episode),
    ("events.EventParticipant", EventParticipant),
    ("events.Event", Event),
    ("core.Contract", Contract),
    ("core.Player", Player),
]


class Command(BaseCommand):
    help = "Wipe the SLAB tables the legacy migrator writes into. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm", action="store_true",
            help="Actually run the deletes. Without this, prints counts only.",
        )
        parser.add_argument(
            "--club", default=None,
            help="Scope the wipe to a single club by name. Without this, "
                 "ALL clubs' data in the listed models is wiped.",
        )

    def handle(self, *args, **opts):
        confirm = opts["confirm"]
        club_name = opts["club"]

        club = None
        if club_name:
            try:
                club = Club.objects.get(name=club_name)
            except Club.DoesNotExist:
                raise CommandError(
                    f"Club '{club_name}' not found. Existing: "
                    f"{list(Club.objects.values_list('name', flat=True))}"
                )

        # Build per-model querysets. Event has a direct club FK; Player
        # reaches club via category; the rest reach club via player or
        # event.
        def qs_for(model):
            if club is None:
                return model.objects.all()
            if model is Event:
                return model.objects.filter(club=club)
            if model is Player:
                return model.objects.filter(category__club=club)
            if model is Contract:
                return model.objects.filter(player__category__club=club)
            if model is EventParticipant:
                return model.objects.filter(event__club=club)
            if model is Episode:
                return model.objects.filter(player__category__club=club)
            if model is ExamResult:
                return model.objects.filter(player__category__club=club)
            return model.objects.none()

        # ---- Plan + counts ------------------------------------------
        plan_rows: list[tuple[str, int]] = []
        for label, model in WIPE_PLAN:
            plan_rows.append((label, qs_for(model).count()))

        scope = f"club='{club.name}'" if club else "ALL clubs"
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            f"wipe_legacy_target — scope: {scope}"
        ))
        self.stdout.write("")
        self.stdout.write("Will delete (in order):")
        for label, n in plan_rows:
            self.stdout.write(f"  {label:32s} {n:>8,} rows")
        total = sum(n for _, n in plan_rows)
        self.stdout.write(f"  {'TOTAL':32s} {total:>8,} rows")
        self.stdout.write("")

        if not confirm:
            self.stdout.write(self.style.NOTICE(
                "Dry run — no rows were deleted. Pass --confirm to execute."
            ))
            return

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        # ---- Execute -------------------------------------------------
        # Single transaction so a mid-wipe failure rolls everything back.
        with transaction.atomic():
            for label, model in WIPE_PLAN:
                deleted, _per_model = qs_for(model).delete()
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ deleted {deleted:,} rows from {label} (+cascades)"
                ))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "Wipe complete. Re-run the legacy migrator for a clean import."
        ))
