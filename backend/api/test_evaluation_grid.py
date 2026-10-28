"""Centro de mando — "Evaluaciones físicas" grid (`api.evaluation_grid`).

Pins: the band is the CATEGORY's (not the field's shared default), the value is
the last reading OF THAT FIELD (a later session that skipped it doesn't blank
it), and a category without bands — the Primer Equipo — gets no grid at all.
"""
from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from api.auth import issue_token
from api.evaluation_grid import build_evaluation_grid
from core.models import Category, Club, Department, Player, StaffMembership
from exams.models import ExamResult, ExamTemplate
from goals.models import AlertRule, AlertRuleKind

User = get_user_model()

BANDAS_CMJ = [
    {"max": 36, "color": "#FF0000", "label": "Muy Deficiente"},
    {"min": 36, "max": 45, "color": "#FFFF00", "label": "Regular"},
    {"min": 45, "color": "#0000FF", "label": "Elite"},
]


class EvaluationGridTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2010", cohort_year=2010)
        cls.primer = Category.objects.create(club=cls.club, name="Primer Equipo")
        cls.a = Player.objects.create(category=cls.cat, first_name="Ana", last_name="A")
        cls.b = Player.objects.create(category=cls.cat, first_name="Beto", last_name="B")
        cls.pro = Player.objects.create(category=cls.primer, first_name="Pro", last_name="P")
        cls.neuro = ExamTemplate.objects.create(
            department=cls.fisico, name="Neuromuscular", slug="neuromuscular",
            config_schema={"fields": [
                {"key": "cmj_best", "label": "CMJ", "type": "number", "unit": "cm"},
                {"key": "tiro_best", "label": "Tiro", "type": "number", "unit": "km/h"}]})
        AlertRule.objects.create(
            template=cls.neuro, field_key="cmj_best", kind=AlertRuleKind.BAND,
            category=cls.cat, config={"ranges": BANDAS_CMJ}, is_active=True)

        def r(p, d, **datos):
            ExamResult.objects.create(template=cls.neuro, player=p, result_data=datos,
                                      recorded_at=timezone.make_aware(datetime(2026, 9, d, 12)))

        r(cls.a, 1, cmj_best=47.0, tiro_best=100)
        r(cls.a, 20, tiro_best=104)               # skipped the CMJ this time
        r(cls.b, 5, cmj_best=33.5)
        r(cls.pro, 5, cmj_best=50.0)

    def test_una_fila_por_jugador_con_el_ultimo_valor_y_su_banda(self):
        d = build_evaluation_grid(self.cat)
        self.assertEqual([(g["name"], [c["key"] for c in g["columns"]]) for g in d["groups"]],
                         [("Neuromuscular", ["cmj_best"])],
                         "sólo los tests con bandas en la categoría")
        filas = {r["name"]: r["cells"] for r in d["rows"]}
        self.assertEqual(set(filas), {"Ana A", "Beto B"})
        self.assertEqual((filas["Ana A"]["cmj_best"]["value"], filas["Ana A"]["cmj_best"]["band"],
                          filas["Ana A"]["cmj_best"]["date"]), (47.0, "Elite", "2026-09-01"),
                         "una sesión posterior sin CMJ no borra el último CMJ")
        self.assertEqual((filas["Beto B"]["cmj_best"]["band"],
                          filas["Beto B"]["cmj_best"]["color"]), ("Muy Deficiente", "#FF0000"))
        self.assertEqual([b["label"] for b in d["legend"]],
                         ["Muy Deficiente", "Regular", "Elite"])

    def test_sin_bandas_no_hay_tabla(self):
        self.assertEqual(build_evaluation_grid(self.primer),
                         {"groups": [], "rows": [], "legend": []})

    def test_el_endpoint_respeta_el_alcance_del_usuario(self):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        u = User.objects.create_user(username="staff", password="x")
        u.groups.add(Group.objects.get(name="Editor"))
        m = StaffMembership.objects.create(user=u, club=self.club, all_departments=True)
        m.categories.add(self.cat)
        c = Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(u)[0]}")
        ok = c.get("/api/command-center/evaluations", {"category_id": str(self.cat.id)})
        self.assertEqual((ok.status_code, len(ok.json()["rows"])), (200, 2))
        fuera = c.get("/api/command-center/evaluations", {"category_id": str(self.primer.id)})
        self.assertEqual(fuera.status_code, 404)
