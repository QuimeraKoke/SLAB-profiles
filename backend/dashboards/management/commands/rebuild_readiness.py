"""Recompute + cache agent-refined readiness for active players.

    docker compose exec backend python manage.py rebuild_readiness \\
        --club "Universidad de Chile" --category "Primer Equipo"

Signature-gated: unchanged players are skipped unless --force. Runs the
per-player agent calls in parallel (bounded).
"""

from __future__ import annotations

import concurrent.futures

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Recompute + cache player readiness (deterministic + agent)."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None)
        parser.add_argument("--category", default=None)
        parser.add_argument("--force", action="store_true",
                            help="Recompute even if inputs are unchanged.")
        parser.add_argument("--workers", type=int, default=6)

    def handle(self, *args, **opts):
        from core.models import Player
        from dashboards.readiness import compute_readiness

        qs = Player.objects.filter(is_active=True).select_related("category", "position")
        if opts["club"]:
            qs = qs.filter(category__club__name=opts["club"])
        if opts["category"]:
            qs = qs.filter(category__name=opts["category"])
        players = list(qs)
        if not players:
            self.stderr.write("No active players match.")
            return

        # DB connections aren't shared across threads — close before fan-out.
        from django.db import connections
        connections.close_all()

        def work(p):
            try:
                r = compute_readiness(p, force=opts["force"])
                return (p, r.score, r.source)
            except Exception as e:  # noqa: BLE001
                return (p, None, f"error: {type(e).__name__}")

        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=opts["workers"]) as pool:
            for p, score, source in pool.map(work, players):
                done += 1
                self.stdout.write(f"  {p.first_name} {p.last_name}: {score} ({source})")
        self.stdout.write(self.style.SUCCESS(f"Readiness computed for {done} players."))
