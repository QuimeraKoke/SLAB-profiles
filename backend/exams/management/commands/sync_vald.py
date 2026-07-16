"""Sync VALD Hub tests (ForceDecks/ForceFrame/NordBord) into ExamResults.

Manual / backfill trigger for the integration otherwise run by Celery beat
(`exams.tasks.sync_all_vald_clubs`). Always dry-run-friendly: without `--commit`
it reports what it *would* create + the profile-match summary, writing nothing.

Examples:
    # Probe one club (no writes) — confirms token/region + profile matches:
    manage.py sync_vald --club "Universidad de Chile" --full

    # Real full backfill:
    manage.py sync_vald --club "Universidad de Chile" --full --commit

    # Just refresh the profile→player links (review queue), no test ingest:
    manage.py sync_vald --club "Universidad de Chile" --profiles-only --commit

    # Only one product, incremental:
    manage.py sync_vald --club "Universidad de Chile" --product nordbord --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams.models import ValdIntegration
from exams.services.vald_sync import _PRODUCTS, sync_all_bound_clubs, sync_club


class Command(BaseCommand):
    help = "Pull VALD Hub tests into the strength templates (cmj/imtp/hip_adab/nordico)."

    def add_arguments(self, parser):
        parser.add_argument("--club", help="Club name (icontains). Omit → all enabled clubs.")
        parser.add_argument("--full", action="store_true",
                            help="Ignore cursors and pull all history.")
        parser.add_argument("--profiles-only", action="store_true",
                            help="Only refresh profile→player links; skip test ingest.")
        parser.add_argument("--product", choices=list(_PRODUCTS),
                            help="Limit ingestion to one product.")
        parser.add_argument("--since", metavar="YYYY-MM-DD",
                            help="Override the cursor: only pull data modified on/after "
                                 "this UTC date. Use to chunk a large backfill or probe.")
        parser.add_argument("--commit", action="store_true",
                            help="Write results. Without it: dry-run (nothing written).")

    def handle(self, *args, **opts):
        dry_run = not opts["commit"]
        # Explicit --product bypasses the club's per-product toggles; omitting
        # it (None) lets sync_club honor the toggles on the integration.
        products = (opts["product"],) if opts["product"] else None
        since = f"{opts['since']}T00:00:00Z" if opts["since"] else None

        if opts["club"]:
            club = Club.objects.filter(name__icontains=opts["club"]).first()
            if club is None:
                raise CommandError(f"No club matches {opts['club']!r}.")
            if not ValdIntegration.objects.filter(club=club, enabled=True).exists():
                raise CommandError(
                    f"'{club.name}' has no enabled VALD integration. "
                    "Create one in the Django admin (VALD integration) first."
                )
            reports = [sync_club(
                club, full=opts["full"], products=products,
                profiles_only=opts["profiles_only"], dry_run=dry_run, since=since,
            )]
        else:
            reports = sync_all_bound_clubs(full=opts["full"], dry_run=dry_run)

        mode = "COMMIT" if opts["commit"] else "DRY-RUN (nothing written)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"VALD sync — {mode}"))
        for r in reports:
            if r.get("status") != "ok":
                self.stdout.write(
                    f"  {r.get('club', '?')}: {r.get('status')} — {r.get('reason', '')}"
                )
                continue
            self.stdout.write(
                f"  {r['club']}: profiles seen={r['profiles_seen']} "
                f"new={r['profiles_new']} unresolved={r['profiles_unresolved']} | "
                f"results created={r['created']} skipped={r['skipped']} "
                f"unmatched={r['unmatched']} no-metrics={r['no_metrics']}"
            )
            for err in r.get("errors", []):
                self.stdout.write(self.style.WARNING(f"    ! {err}"))
        if dry_run:
            self.stdout.write(self.style.NOTICE("Re-run with --commit to write results."))
