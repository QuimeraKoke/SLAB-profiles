"""The Daily shows only the last week's work plans."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from api.daily_report import PLAN_WINDOW_DAYS, plans_by_player
from core.models import Category, Club, DailyNote, Player


class DailyPlansWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        club = Club.objects.create(name="FC")
        cls.cat = Category.objects.create(club=club, name="Primer Equipo")
        cls.p = Player.objects.create(category=cls.cat, first_name="A", last_name="B")

    def plan(self, dia, texto):
        DailyNote.objects.create(player=self.p, kind=DailyNote.KIND_PLAN, date=dia, text=texto)

    def test_solo_la_ultima_semana_hasta_el_dia_de_la_reunion(self):
        hoy = date(2026, 9, 30)
        self.plan(hoy, "hoy")
        self.plan(hoy - timedelta(days=PLAN_WINDOW_DAYS - 1), "hace 6 días")   # entra
        self.plan(hoy - timedelta(days=PLAN_WINDOW_DAYS), "hace 7 días")        # queda afuera
        self.plan(hoy - timedelta(days=60), "hace dos meses")
        self.plan(hoy + timedelta(days=1), "mañana")                              # futuro: afuera
        textos = [n["text"] for n in plans_by_player(self.cat, hoy).get(self.p.id, [])]
        self.assertEqual(textos, ["hoy", "hace 6 días"])

    def test_la_ventana_sigue_a_la_fecha_consultada(self):
        """Mirar el Daily de un día anterior muestra los planes de ESA semana."""
        self.plan(date(2026, 8, 1), "agosto")
        textos = [n["text"] for n in plans_by_player(self.cat, date(2026, 8, 3)).get(self.p.id, [])]
        self.assertEqual(textos, ["agosto"])
