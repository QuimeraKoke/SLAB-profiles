"""Rebuild PlayerMetricState from raw ExamResults.

The materialized state is a read model — this rebuilds it from the source of
truth, for backfill, after recompute-logic changes (bump STATE_VERSION), or
when the trigger was bypassed (bulk import without Celery).

    python manage.py rebuild_player_state            # all active players
    python manage.py rebuild_player_state --player <uuid>
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Rebuild PlayerMetricState for all active players (or one) from raw data."

    def add_arguments(self, parser):
        parser.add_argument("--player", help="Player UUID (default: all active players).")

    def handle(self, *args, **options):
        from core.models import Player
        from dashboards.player_state import upsert_player_state

        qs = Player.objects.select_related("category", "position")
        qs = qs.filter(pk=options["player"]) if options.get("player") else qs.filter(is_active=True)

        n = with_load = 0
        for player in qs.iterator():
            obj = upsert_player_state(player)
            n += 1
            if (obj.state or {}).get("weekly_load"):
                with_load += 1
            if n % 50 == 0:
                self.stdout.write(f"  {n}…")
        self.stdout.write(self.style.SUCCESS(
            f"Rebuilt {n} player state(s); {with_load} with weekly-load data."
        ))
