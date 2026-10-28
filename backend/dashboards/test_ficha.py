"""Ficha integral (`dashboards.pdf.ficha`): judgement, text and the endpoint.

Pins: the band wins over the percentile; a strength/weakness comes from the
club's ladder whatever order its bands are declared in; a % field's change
reads in points; and every department with a spec renders while a notes-only
one says it has no ficha.
"""
from __future__ import annotations

from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from api.auth import issue_token
from core.models import Category, Club, Department, Player, StaffMembership
from dashboards.pdf import ficha
from exams.models import ExamResult, ExamTemplate
from goals.models import AlertRule, AlertRuleKind

User = get_user_model()

BANDAS = [  # declared best → worst, on purpose
    {"min": 45, "label": "Elite", "color": "#0000FF"},
    {"min": 36, "max": 45, "label": "Regular", "color": "#FFFF00"},
    {"max": 36, "label": "Muy Deficiente", "color": "#FF0000"},
]


def R(m, pts, direction="up", unit="", band=None, level=None, pct=None):
    r = ficha.Reading(m, points=[(date(2026, 1, i + 1), v) for i, v in enumerate(pts)],
                      direction=direction, unit=unit, band=band, level=level, percentile=pct)
    return r


class FichaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.kine = Department.objects.create(club=cls.club, name="Kinesiológico", slug="kinesiologico")
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2010", cohort_year=2010)
        cls.player = Player.objects.create(category=cls.cat, first_name="Ana", last_name="A",
                                           date_of_birth=date(2010, 2, 1))
        for i in range(6):
            Player.objects.create(category=cls.cat, first_name=f"P{i}", last_name="X")
        cls.neuro = ExamTemplate.objects.create(
            department=cls.fisico, name="Neuromuscular", slug="neuromuscular",
            config_schema={"fields": [{"key": "cmj_best", "label": "CMJ", "type": "number",
                                       "unit": "cm", "direction_of_good": "up"}]})
        AlertRule.objects.create(template=cls.neuro, field_key="cmj_best", kind=AlertRuleKind.BAND,
                                 category=cls.cat, config={"ranges": BANDAS}, is_active=True)
        for d, v in ((1, 40.0), (20, 47.0)):
            ExamResult.objects.create(template=cls.neuro, player=cls.player,
                                      recorded_at=timezone.make_aware(datetime(2026, 9, d, 12)),
                                      result_data={"cmj_best": v})

    def test_la_banda_de_la_categoria_juzga_el_ultimo_valor(self):
        m = ficha.M("neuromuscular", "cmj_best", "CMJ", "saltabilidad", "cm", 1)
        r = ficha._Data(self.player).reading(m)
        self.assertEqual((r.last, r.prev, r.band["label"], r.verdict), (47.0, 40.0, "Elite", "strong"))
        self.assertTrue(ficha._improved(r))

    def test_la_escala_se_lee_por_nombre_no_por_orden(self):
        self.assertEqual(ficha._level(BANDAS[2], BANDAS), 0)
        self.assertEqual(ficha._level(BANDAS[0], BANDAS), 6)

    def test_sintesis_nombra_fortalezas_y_prioridades(self):
        fuerte = R(ficha.M("x", "a", "A", "resistencia"), [1, 2], level=6)
        debil = R(ficha.M("x", "b", "B", "aceleración"), [2, 1], level=0)
        sin = R(ficha.M("x", "c", "C", "fuerza"), [])
        txt = ficha.synthesis([fuerte, debil, sin])
        self.assertIn("Fortalezas: resistencia.", txt["lines"])
        self.assertIn("A priorizar: aceleración.", txt["lines"])
        self.assertIn("Sin datos de fuerza.", txt["lines"])
        self.assertEqual(txt["plazos"][0][1], "Abordar aceleración y asegurar disponibilidad.")

    def test_sin_bandas_juzga_por_percentil(self):
        self.assertEqual(R(ficha.M("x", "a", "A", "a"), [1], pct=80).verdict, "strong")
        self.assertEqual(R(ficha.M("x", "a", "A", "a"), [1], pct=20).verdict, "weak")
        self.assertIsNone(R(ficha.M("x", "a", "A", "a"), [1], pct=50).verdict)

    def test_un_porcentaje_cambia_en_puntos(self):
        r = R(ficha.M("x", "d", "Δ", "basal", "%", 1), [0.3, -2.6], unit="%")
        self.assertIn("-2,9 pts vs la anterior", ficha.card_line(r))
        self.assertNotIn("897", ficha.card_line(r))

    # ── endpoint ────────────────────────────────────────────────────────
    def staff_client(self):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        u = User.objects.create_user(username="staff", password="x")
        u.groups.add(Group.objects.get(name="Editor"))
        m = StaffMembership.objects.create(user=u, club=self.club, all_departments=True)
        m.categories.add(self.cat)
        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(u)[0]}")

    def test_cada_ficha_es_un_pdf_de_una_pagina(self):
        c = self.staff_client()
        for dept in ("", "fisico"):
            r = c.get(f"/api/players/{self.player.id}/ficha.pdf",
                      {"department": dept} if dept else {})
            self.assertEqual(r.status_code, 200, dept)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r.content.startswith(b"%PDF"))
            self.assertEqual(r.content.count(b"/Type /Page\n") + r.content.count(b"/Type /Page "),
                             1, dept)
        for slug in ficha.SPECS:
            self.assertTrue(ficha.render_ficha_pdf(self.player, slug, slug).startswith(b"%PDF"), slug)

    def test_un_area_de_notas_no_tiene_ficha(self):
        r = self.staff_client().get(f"/api/players/{self.player.id}/ficha.pdf",
                              {"department": "kinesiologico"})
        self.assertEqual(r.status_code, 404)


class LateralidadYPeriodoTests(TestCase):
    def test_lado_mejor_y_su_relacion_con_el_perfil(self):
        der = R(ficha.M("carreras", "cod_der_best", "D", "cod der", "s"), [2.40], direction="down")
        izq = R(ficha.M("carreras", "cod_izq_best", "I", "cod izq", "s"), [2.60], direction="down")
        txt = ficha.laterality([der, izq], "right")
        self.assertEqual(txt[0], "Perfil: derecho.")
        self.assertIn("mejor hacia la derecha", txt[1])
        self.assertIn("su lado hábil", txt[1])
        txt = ficha.laterality([der, izq], "left")
        self.assertIn("el contrario a su perfil", txt[1])

    def test_menos_de_3_por_ciento_es_simetrico(self):
        der = R(ficha.M("carreras", "cod_der_best", "D", "d", "s"), [2.50], direction="down")
        izq = R(ficha.M("carreras", "cod_izq_best", "I", "i", "s"), [2.52], direction="down")
        self.assertIn("simétrico", ficha.laterality([der, izq], "")[0])

    def test_el_periodo_es_este_anio_y_el_anterior(self):
        self.assertEqual(ficha.period_start(date(2026, 10, 28)).date(), date(2025, 1, 1))
