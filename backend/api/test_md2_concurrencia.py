"""MD+2: two people saving the same player's test at the same instant end in
ONE record (the advisory lock in `md2._bloquear`), against the real database."""
from __future__ import annotations

import threading
from datetime import timedelta

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from api import md2
from core.models import Category, Club, Department, Player
from events.models import Event, EventParticipant
from exams.models import ExamResult, ExamTemplate


class Md2ConcurrenciaTests(TransactionTestCase):
    def test_guardados_simultaneos_no_duplican(self):
        if connection.vendor != "postgresql":
            self.skipTest("advisory locks are Postgres-only")
        club = Club.objects.create(name="FC")
        med = Department.objects.create(club=club, name="Médico", slug="medico")
        cat = Category.objects.create(club=club, name="Primer Equipo", is_senior=True)
        a = Player.objects.create(category=cat, first_name="Ana", last_name="Soto")
        t = ExamTemplate.objects.create(department=med, name="ck", slug="ck",
                                        config_schema={"fields": [{"key": "valor", "type": "number"}]})
        t.applicable_categories.add(cat)
        ev = Event.objects.create(club=club, category=cat, department=med, event_type="match",
                                  title="FC vs X", starts_at=timezone.now() - timedelta(days=2))
        EventParticipant.objects.create(event=ev, player=a, match_role="titular")
        ctx = md2.contexto(cat, ev)

        barrera = threading.Barrier(4)
        errores = []

        def guardar(v):
            try:
                barrera.wait()
                md2.guardar(ctx, [{"player_id": str(a.id), "valores": {"ck": {"valor": v}}}],
                            allowed_players={str(a.id)})
            except Exception as e:  # noqa: BLE001
                errores.append(e)
            finally:
                connection.close()

        hilos = [threading.Thread(target=guardar, args=(v,)) for v in (100, 200, 300, 400)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(errores, [])
        self.assertEqual(ExamResult.objects.filter(event=ev, template=t).count(), 1)
