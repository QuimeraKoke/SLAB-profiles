"""`GET /injuries/ranges` — a player's injuries as date ranges for charts."""
from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.models import Episode, ExamResult, ExamTemplate


def dt(*a):
    return timezone.make_aware(datetime(*a))


class InjuryRangesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from io import StringIO

        from django.core.management import call_command

        cls.club = Club.objects.create(name="FC")
        Department.objects.create(club=cls.club, name="Médico", slug="medico")
        call_command("seed_lesiones", "--club", "FC", "--create-if-missing", stdout=StringIO())
        cls.t = ExamTemplate.objects.get(slug="lesiones")
        cat = Category.objects.create(club=cls.club, name="Serie 2013")
        cls.a = Player.objects.create(category=cat, first_name="Ana", last_name="Soto")
        cls.b = Player.objects.create(category=cat, first_name="Beto", last_name="Rios")
        cls.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")

    def lesion(self, player, inicio, fin=None, **datos):
        ep = Episode.objects.create(player=player, template=self.t, started_at=inicio)
        base = {"body_part": "Muneca", "type": "Fractura/Estres oseo",
                "body_part_detail": "Fractura radio", "severity": "Severa"}
        base.update(datos)
        ExamResult.objects.create(player=player, template=self.t, episode=ep,
                                  recorded_at=inicio, result_data=dict(base, stage="aguda"))
        if fin:
            # A hand-made follow-up that does NOT carry the definition forward.
            ExamResult.objects.create(player=player, template=self.t, episode=ep,
                                      recorded_at=fin, result_data={"stage": "closed"})
        return ep

    def pedir(self, *players):
        from api.routers import list_injury_ranges

        req = RequestFactory().get("/injuries/ranges")
        req.user = self.su
        return list_injury_ranges(req, players=",".join(str(p.pk) for p in players))

    def test_rango_cerrado_con_resumen_fusionado(self):
        self.lesion(self.a, dt(2026, 3, 1), dt(2026, 4, 4), dias_perdidos=34)
        (r,) = self.pedir(self.a)
        self.assertEqual(r["status"], "closed")
        self.assertEqual(r["ended_at"].date().isoformat(), "2026-04-04")
        # The closing result has no definition; the summary keeps the opening's.
        self.assertEqual(r["summary"]["diagnosis"], "Fractura radio")
        self.assertEqual(r["summary"]["body_part"], "Muñeca", "la etiqueta, no la clave")
        self.assertEqual(r["summary"]["dias_perdidos"], 34)
        self.assertEqual(r["player_name"], "Ana Soto")

    def test_una_abierta_no_tiene_fin_y_trae_su_etapa(self):
        self.lesion(self.a, dt(2026, 9, 20))
        (r,) = self.pedir(self.a)
        self.assertIsNone(r["ended_at"])
        self.assertEqual(r["stage_label"], "Lesionado — fase aguda")

    def test_varios_jugadores_en_consultas_constantes(self):
        for i in range(6):
            self.lesion(self.a if i % 2 else self.b, dt(2025, 1 + i, 1), dt(2025, 1 + i, 20))
        with CaptureQueriesContext(connection) as q:
            out = self.pedir(self.a, self.b)
        self.assertEqual(len(out), 6)
        self.assertLessEqual(len(q), 6, "no una consulta por episodio")

    def test_otras_plantillas_episodicas_no_entran(self):
        otra = ExamTemplate.objects.create(name="Medicación", slug="medicacion",
                                           department=self.t.department, config_schema={})
        Episode.objects.create(player=self.a, template=otra, started_at=dt(2026, 1, 1))
        self.assertEqual(self.pedir(self.a), [])
