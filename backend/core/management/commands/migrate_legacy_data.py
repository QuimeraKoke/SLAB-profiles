"""Migrate the U. de Chile legacy Postgres DB into SLAB.

Phased, idempotent, dry-runnable. Default scope is calendar 2025+2026.
Source DB is read-only (uchile DB at 192.168.1.24); password comes
from the `LEGACY_DB_PASSWORD` env var — never via CLI flag.

Examples:

    # full run, real writes:
    LEGACY_DB_PASSWORD='...' python manage.py migrate_legacy_data

    # dry-run, just reference data:
    LEGACY_DB_PASSWORD='...' python manage.py migrate_legacy_data \\
        --dry-run --entities=phase0

    # widen the scope:
    LEGACY_DB_PASSWORD='...' python manage.py migrate_legacy_data \\
        --date-from=2024-01-01 --date-to=2026-12-31

    # only one club's data (when multi-club):
    LEGACY_DB_PASSWORD='...' python manage.py migrate_legacy_data \\
        --club 'Universidad de Chile'

Audit log lands in `migration_runs/run-YYYYMMDDTHHMM[-DRY].jsonl`.
"""
from __future__ import annotations

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from core.legacy_migration.audit import AuditLog
from core.legacy_migration.connection import (
    DEFAULT_DB, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_USER, LegacyDB,
)
from core.legacy_migration.phases import (
    phase0_reference,
    phase1_players,
    phase2_contracts,
    phase3_events,
    phase4_callups,
    phase5_episodes,
    phase6_results,
)
from core.legacy_migration.phases.context import MigrationContext


# Order matters — later phases depend on lookups populated by earlier ones.
ALL_PHASES: list[tuple[str, callable]] = [
    ("phase0", phase0_reference.run),    # categoria, posicion
    ("phase1", phase1_players.run),      # jugador (active set + photo copy)
    ("phase2", phase2_contracts.run),    # contrato
    ("phase3", phase3_events.run),       # partido → Event
    ("phase4", phase4_callups.run),      # citaciones + estadistica_interna → EventParticipant
    ("phase5", phase5_episodes.run),     # lesion → Episode + ExamResult
    ("phase6", phase6_results.run),      # antropometria / wellness / etc.
]


class Command(BaseCommand):
    help = "Migrate the U. de Chile legacy database into SLAB. See docstring for examples."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Plan + log everything but don't write to the SLAB DB. "
                 "Audit file gets a '-DRY' suffix.",
        )
        parser.add_argument(
            "--entities", default=None,
            help="Comma-separated phase names (e.g. 'phase0,phase1'). "
                 "Default: run every phase in order.",
        )
        parser.add_argument(
            "--date-from", default="2025-01-01",
            help="Scope start date (YYYY-MM-DD). Default: 2025-01-01.",
        )
        parser.add_argument(
            "--date-to", default="2026-12-31",
            help="Scope end date (YYYY-MM-DD). Default: 2026-12-31.",
        )
        parser.add_argument(
            "--club", default="Universidad de Chile",
            help="Destination SLAB club name. Default: 'Universidad de Chile'.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Per-phase row cap. Useful for a first small real run "
                 "before committing to the full ~25k-row import.",
        )
        parser.add_argument(
            "--skip-photos", action="store_true",
            help="Skip the per-player photo download/copy in phase 1. "
                 "Photo fetch is the slowest step; skipping makes a full "
                 "re-run minutes faster when photos aren't needed.",
        )
        # Source-DB overrides — useful in CI/local-testing setups.
        parser.add_argument("--legacy-host", default=DEFAULT_HOST)
        parser.add_argument("--legacy-port", type=int, default=DEFAULT_PORT)
        parser.add_argument("--legacy-db",   default=DEFAULT_DB)
        parser.add_argument("--legacy-user", default=DEFAULT_USER)

    def handle(self, *args, **opts):
        # ---- Resolve destination club ------------------------------
        try:
            club = Club.objects.get(name=opts["club"])
        except Club.DoesNotExist:
            raise CommandError(
                f"Destination club '{opts['club']}' not found. "
                f"Existing clubs: {list(Club.objects.values_list('name', flat=True))}"
            )

        # ---- Parse scope window ------------------------------------
        try:
            date_from = _parse_date(opts["date_from"])
            date_to = _parse_date(opts["date_to"])
        except ValueError as exc:
            raise CommandError(f"--date-from / --date-to: {exc}")

        if date_to < date_from:
            raise CommandError(f"--date-to must be on/after --date-from")

        # ---- Pick phases to run ------------------------------------
        entities = opts["entities"]
        phase_filter: set[str] | None = (
            {p.strip() for p in entities.split(",")} if entities else None
        )
        if phase_filter:
            unknown = phase_filter - {name for name, _ in ALL_PHASES}
            if unknown:
                raise CommandError(
                    f"Unknown phase(s): {sorted(unknown)}. "
                    f"Known: {[n for n, _ in ALL_PHASES]}"
                )

        # ---- Open audit log + legacy DB -----------------------------
        audit = AuditLog(dry_run=opts["dry_run"])
        self.stdout.write(self.style.NOTICE(
            f"Audit log: {audit.path}"
            + (" (DRY RUN)" if opts["dry_run"] else "")
        ))
        audit.info(
            "migration: start",
            club=str(club),
            dry_run=opts["dry_run"],
            date_from=str(date_from),
            date_to=str(date_to),
            legacy_dsn=f"{opts['legacy_host']}:{opts['legacy_port']}/{opts['legacy_db']}",
            phases=[n for n, _ in ALL_PHASES if not phase_filter or n in phase_filter],
        )

        try:
            with LegacyDB(
                host=opts["legacy_host"],
                port=opts["legacy_port"],
                dbname=opts["legacy_db"],
                user=opts["legacy_user"],
            ) as db:
                ctx = MigrationContext(
                    legacy_db=db,
                    audit=audit,
                    dry_run=opts["dry_run"],
                    date_from=date_from,
                    date_to=date_to,
                    club=club,
                    limit=opts["limit"],
                    skip_photos=opts["skip_photos"],
                )

                for name, fn in ALL_PHASES:
                    if phase_filter and name not in phase_filter:
                        audit.info(f"{name}: skipped (not in --entities filter)")
                        continue
                    self.stdout.write(self.style.NOTICE(f"→ Running {name}…"))
                    fn(ctx)

            # ---- Summary ---------------------------------------------
            audit.info("migration: done", summary=audit.summary())
            self._print_summary(audit)
        finally:
            audit.close()

    def _print_summary(self, audit: AuditLog) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Summary:"))
        for phase, actions in audit.summary().items():
            parts = ", ".join(f"{k}={v}" for k, v in sorted(actions.items()))
            self.stdout.write(f"  {phase}: {parts}")
        self.stdout.write("")
        self.stdout.write(f"Full log: {audit.path}")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()
