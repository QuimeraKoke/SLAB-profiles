"""Capture today's PlayerStateSnapshot for all active players.

Manual run of the weekly Celery job (`dashboards.tasks.snapshot_player_states`)
— useful for backfilling or testing the evolution charts.

    python manage.py snapshot_player_states
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Capture today's player-state snapshot for all active players."

    def handle(self, *args, **options):
        from dashboards.tasks import snapshot_player_states

        result = snapshot_player_states()
        self.stdout.write(self.style.SUCCESS(
            f"Snapshotted {result['snapshotted']} player(s) for {result['date']}."
        ))
