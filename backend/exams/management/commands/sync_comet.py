"""Pull PLAYED matches from COMET LIVE (federation match record) into SLAB.

Manual / backfill trigger for what the hourly beat otherwise runs
(`exams.tasks.sync_all_comet_clubs`). Dry-run by default: it reports what it
WOULD write plus the competition and player review queues, touching nothing.

Configuration lives in Django admin → "Integración COMET" (one row per club,
holding the four values the federation issues). One team id covers every
category, so the category comes from each match's competition — see
"Competencias COMET" for that mapping.

    # Probe a club (no writes) — confirms the key, the team, the category
    # mapping and the player match-rate:
    manage.py sync_comet --club "Universidad de Chile"

    # Only the last week, verbose:
    manage.py sync_comet --club "Universidad de Chile" --days 7 --verbose

    # Write:
    manage.py sync_comet --club "Universidad de Chile" --commit
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from exams.models import CometIntegration
from exams.services import comet_sync


class Command(BaseCommand):
    help = "Sync played matches from COMET into the ficha template + match Events."

    def add_arguments(self, parser):
        parser.add_argument("--club", help="Club name (icontains). Omit → all enabled.")
        parser.add_argument("--days", type=int,
                            help="Override the integration's lookback_days.")
        parser.add_argument("--commit", action="store_true",
                            help="Write. Without it: dry-run (nothing written).")
        parser.add_argument("--verbose", action="store_true",
                            help="List the review queues in full.")

    def handle(self, *args, **opts):
        dry_run = not opts["commit"]
        qs = CometIntegration.objects.select_related("club")
        if opts["club"]:
            qs = qs.filter(club__name__icontains=opts["club"])
        integrations = list(qs)
        if not integrations:
            raise CommandError(
                "No hay integraciones COMET"
                + (f" para club~{opts['club']!r}" if opts["club"] else "")
                + ". Creá una en Django admin → «Integración COMET»."
            )

        since = (
            timezone.now() - timedelta(days=opts["days"]) if opts["days"] else None
        )

        self.stdout.write(
            self.style.WARNING("DRY-RUN — nada escrito.\n") if dry_run else
            self.style.SUCCESS("COMMIT\n")
        )
        for integ in integrations:
            rep = comet_sync.sync_club(integ, dry_run=dry_run, since=since)
            self._render(rep, verbose=opts["verbose"])

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — volvé a correr con --commit para escribir."
            ))

    def _render(self, rep: dict, *, verbose: bool):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{rep['club']}"))
        if rep.get("status") != "ok":
            self.stdout.write(self.style.WARNING(
                f"  omitido: {rep.get('reason')}"
            ))
            return

        self.stdout.write(
            f"  partidos: vistos {rep['matches_seen']} · "
            f"procesados {rep['matches_ingested']} · "
            f"no jugados {rep['skipped_not_played']}"
        )
        self.stdout.write(
            f"  fichas:   nuevas {rep['results_created']} · "
            f"ya existían {rep['skipped_existing']}"
        )
        self.stdout.write(
            f"  eventos:  actualizados {rep['events_updated']} · "
            f"creados {rep['events_created']} · "
            f"sin evento en SLAB {rep['skipped_no_event']}"
        )
        if rep["competitions_new"]:
            self.stdout.write(f"  competencias nuevas detectadas: {rep['competitions_new']}")

        if rep["skipped_unmapped_competition"]:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {rep['skipped_unmapped_competition']} partido(s) omitido(s): "
                f"competencia sin categoría asignada"
            ))
            for c in (rep["unmapped_competitions"] if verbose else rep["unmapped_competitions"][:6]):
                self.stdout.write(f"      · {c}")
            self.stdout.write(
                "    → asignalas en Django admin → «Competencias COMET»"
            )
        if rep["players_unresolved"]:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {rep['players_unresolved']} jugador(es) sin vincular"
            ))
            for p in (rep["unresolved_players"] if verbose else rep["unresolved_players"][:8]):
                self.stdout.write(f"      · {p}")
            self.stdout.write(
                "    → vinculalos en Django admin → «Vínculos jugador COMET» "
                "(el personId es estable, se hace una sola vez)"
            )
        for e in rep.get("errors") or []:
            self.stdout.write(self.style.ERROR(f"  error: {e}"))
