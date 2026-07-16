"""Additive bulk-import of serialized records (players, exam results) into the
current DB WITHOUT firing per-row signals — for local→prod historical migrations.

`bulk_create(..., ignore_conflicts=True)` inserts only the PKs that don't yet
exist (never overwrites an existing prod row) and fires NO `post_save`, so the
alert engine / per-row state recompute don't run (no flood of historical
alerts, and fast over a remote connection). Players are inserted before results
so the FK resolves. Dry-run by default.

    # local — dump the records to migrate:
    python manage.py dumpdata core.Player      --pks <ids> -o /tmp/players.json
    python manage.py dumpdata exams.examresult --pks <ids> -o /tmp/results.json
    # prod (POSTGRES_* → prod) — import them, signal-free:
    python manage.py import_records_bulk /tmp/players.json /tmp/results.json          # dry-run
    python manage.py import_records_bulk /tmp/players.json /tmp/results.json --commit
"""
from __future__ import annotations

from django.core import serializers
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Additively bulk-import players + exam results from JSON fixtures (no signals)."

    def add_arguments(self, parser):
        parser.add_argument("fixtures", nargs="+", help="Django JSON fixture file(s).")
        parser.add_argument("--commit", action="store_true", help="Write (default: dry-run).")
        parser.add_argument("--recompute", action="store_true",
                            help="After import, recompute Player.status for affected players once.")

    def handle(self, *args, **opts):
        from core.models import Player
        from exams.models import ExamResult

        players: list = []
        results: list = []
        other = 0
        for path in opts["fixtures"]:
            with open(path) as fh:
                for d in serializers.deserialize("json", fh.read(), ignorenonexistent=True):
                    obj = d.object
                    if isinstance(obj, Player):
                        players.append(obj)
                    elif isinstance(obj, ExamResult):
                        results.append(obj)
                    else:
                        other += 1

        p_pks = [p.pk for p in players]
        r_pks = [r.pk for r in results]
        existing_p = set(Player.objects.filter(pk__in=p_pks).values_list("pk", flat=True))
        existing_r = set(ExamResult.objects.filter(pk__in=r_pks).values_list("pk", flat=True))
        new_players = len(players) - len(existing_p)
        new_results = len(results) - len(existing_r)

        self.stdout.write(f"Parsed: {len(players)} players, {len(results)} results"
                          + (f", {other} otros (ignorados)" if other else ""))
        self.stdout.write(f"  Players: {new_players} nuevos, {len(existing_p)} ya existen")
        self.stdout.write(f"  Results: {new_results} nuevos, {len(existing_r)} ya existen")

        if not opts["commit"]:
            self.stdout.write(self.style.WARNING("\nDRY-RUN — nada escrito. Pasá --commit para importar."))
            return

        with transaction.atomic():
            if players:
                Player.objects.bulk_create(players, ignore_conflicts=True, batch_size=200)
            if results:
                ExamResult.objects.bulk_create(results, ignore_conflicts=True, batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f"\nImportado (aditivo, sin señales): +{new_players} jugadores, +{new_results} resultados."
        ))

        if opts["recompute"]:
            from exams.episode_lifecycle import recompute_player_status
            affected = {r.player_id for r in results} | set(p_pks)
            n = 0
            for pid in affected:
                pl = Player.objects.filter(pk=pid).first()
                if pl:
                    recompute_player_status(pl)
                    n += 1
            self.stdout.write(self.style.SUCCESS(f"Recalculado Player.status de {n} jugadores."))
