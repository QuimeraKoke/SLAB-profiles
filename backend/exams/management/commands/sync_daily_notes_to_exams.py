"""Mirror existing Daily meeting notes into each área's "Notas diarias".

New and edited notes are mirrored live by a signal (`exams/daily_note_sync.py`);
this backfills the ones written before the link existed. Idempotent: a second
run reports everything as `igual`.

    docker compose exec backend python manage.py sync_daily_notes_to_exams            # dry run
    docker compose exec backend python manage.py sync_daily_notes_to_exams --commit
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import DailyNote
from exams import daily_note_sync


class Command(BaseCommand):
    help = "Backfill: copia las notas del Daily a las 'Notas diarias' de su área."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Escribe (por defecto: simulación).")

    def handle(self, *args, **opts):
        notas = DailyNote.objects.select_related("department", "created_by").order_by("date")
        c = Counter()
        sin_plantilla = Counter()
        with transaction.atomic():
            for n in notas:
                accion = daily_note_sync.sync(n)
                c[accion] += 1
                if accion == "sin_espejo" and n.kind == n.KIND_PAUTA and n.department_id:
                    sin_plantilla[n.department.name] += 1
            if not opts["commit"]:
                transaction.set_rollback(True)

        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{modo}\n"))
        self.stdout.write(f"  notas del Daily       : {sum(c.values())}")
        for k in ("creada", "actualizada", "igual", "borrada", "sin_espejo"):
            self.stdout.write(f"    {k:<20}: {c[k]}")
        self.stdout.write("  (sin_espejo = generales sin área, planes de trabajo, o área sin plantilla)")
        if sin_plantilla:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ área sin 'Notas diarias' — correr seed_daily_notes: {dict(sin_plantilla)}"))
