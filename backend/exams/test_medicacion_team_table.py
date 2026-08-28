"""Medicación por equipo: una receta, varios jugadores.

El caso es el que el club describió — vacunación, un suplemento, un
antiinflamatorio después de un partido: la MISMA indicación a varios. Así que la
receta se pregunta una vez y sólo la dosis es por jugador.

Lo que estos tests protegen, en orden de qué dolería más si se rompe:

  1. Que las alertas WADA sigan disparando por esta vía. Es el motivo por el que
     el template existe, y una carga masiva que las saltea sería peor que no
     tener carga masiva.
  2. Que `dosis` sea la única columna. No es preferencia: la grilla no tiene
     checkbox por fila, incluye a un jugador cuando alguna celda suya tiene dato
     (`isRowBlank`). Con `row_fields` vacío no habría forma de elegir a quién se
     le receta.
  3. Que `adjuntos` NO aparezca. Es `type: file`, y ni la celda ni el campo
     compartido saben renderizarlo: caerían al input de texto.
"""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase

from api.auth import issue_token
from core.models import Category, Club, Department, Player, StaffMembership
from exams.models import ExamResult, ExamTemplate
from goals.models import Alert

User = get_user_model()


class MedicacionTeamTableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.dept = Department.objects.create(
            club=cls.club, name="Médico", slug="medico")
        cls.cat = Category.objects.create(
            club=cls.club, name="Primer Equipo", is_senior=True)
        cls.cat.departments.add(cls.dept)
        call_command("seed_medicacion_template", "--create-if-missing",
                     "--club", "Universidad de Chile", verbosity=0)
        cls.template = ExamTemplate.objects.get(
            slug="medicacion", department=cls.dept, is_active_version=True)
        # El seed adjunta las categorías que tienen el departamento; en el test
        # la creamos después, así que la vinculamos a mano.
        cls.template.applicable_categories.add(cls.cat)
        cls.players = [
            Player.objects.create(
                category=cls.cat, first_name=f"J{i}", last_name=f"Apellido{i}")
            for i in range(3)
        ]

    def setUp(self):
        user = User.objects.create_superuser(username="root", password="x")
        m = StaffMembership.objects.create(
            user=user, club=self.club, all_departments=True)
        m.categories.add(self.cat)
        self.client = Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(user)[0]}")

    # ── la configuración ────────────────────────────────────────────────
    def _tt(self):
        return (self.template.input_config or {}).get("team_table") or {}

    def test_the_mode_is_offered(self):
        self.assertIn("team_table", self.template.input_config["input_modes"])

    def test_single_stays_the_default(self):
        # La mayoría de las indicaciones son a un jugador; la grilla es la
        # excepción, no el camino principal.
        self.assertEqual(self.template.input_config["default_input_mode"], "single")

    def test_the_prescription_is_asked_once(self):
        shared = set(self._tt().get("shared_fields") or [])
        self.assertEqual(
            shared,
            {"medicamento", "tipo", "via_admin", "fecha_inicio", "fecha_fin",
             "motivo"},
        )

    def test_dose_is_the_only_column_and_that_is_the_selector(self):
        self.assertEqual(self._tt().get("row_fields"), ["dosis"])

    def test_attachments_are_in_neither_list(self):
        tt = self._tt()
        for bucket in ("shared_fields", "row_fields"):
            self.assertNotIn("adjuntos", tt.get(bucket) or [], bucket)

    # ── el guardado ─────────────────────────────────────────────────────
    def _risk_option(self, level: str) -> str:
        field = next(f for f in self.template.config_schema["fields"]
                     if f["key"] == "medicamento")
        return next(o for o, r in (field.get("option_risk") or {}).items()
                    if (r or "").upper() == level)

    def _post(self, medicamento, doses=("500 mg", "600 mg", "700 mg")):
        return self.client.post("/api/results/team", data=json.dumps({
            "template_id": str(self.template.id),
            "category_id": str(self.cat.id),
            "recorded_at": "2026-08-25T12:00:00-04:00",
            "shared_data": {
                "medicamento": medicamento,
                "fecha_inicio": "2026-08-25",
                "motivo": "Profilaxis post-partido",
                "via_admin": "Oral",
            },
            "rows": [
                {"player_id": str(p.id), "result_data": {"dosis": d}}
                for p, d in zip(self.players, doses)
            ],
        }), content_type="application/json")

    def test_one_prescription_lands_on_every_player(self):
        med = self._risk_option("PERMITIDO")
        r = self._post(med)
        self.assertEqual(r.status_code, 200, r.content[:400])
        self.assertEqual(r.json()["created"], 3)

        rows = ExamResult.objects.filter(template=self.template)
        self.assertEqual(rows.count(), 3)
        for er in rows:
            self.assertEqual(er.result_data["medicamento"], med)
            self.assertEqual(er.result_data["motivo"], "Profilaxis post-partido")

    def test_each_player_keeps_his_own_dose(self):
        # La razón de que `dosis` no sea compartida: la dosis por peso es
        # práctica corriente.
        self._post(self._risk_option("PERMITIDO"))
        got = {
            er.player.last_name: er.result_data["dosis"]
            for er in ExamResult.objects.filter(
                template=self.template).select_related("player")
        }
        self.assertEqual(
            got, {"Apellido0": "500 mg", "Apellido1": "600 mg", "Apellido2": "700 mg"})

    def test_a_player_left_blank_is_skipped(self):
        r = self.client.post("/api/results/team", data=json.dumps({
            "template_id": str(self.template.id),
            "category_id": str(self.cat.id),
            "recorded_at": "2026-08-25T12:00:00-04:00",
            "shared_data": {"medicamento": self._risk_option("PERMITIDO"),
                            "fecha_inicio": "2026-08-25"},
            "rows": [
                {"player_id": str(self.players[0].id), "result_data": {"dosis": "500 mg"}},
                {"player_id": str(self.players[1].id), "result_data": {"dosis": None}},
            ],
        }), content_type="application/json")
        body = r.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["skipped"], 1)

    # ── lo que más importa ──────────────────────────────────────────────
    def test_a_prohibited_drug_alerts_every_player(self):
        """La razón por la que este template existe.

        Una carga por equipo que saltee las alertas WADA sería peor que no tener
        carga por equipo: el médico creería estar cubierto.
        """
        med = self._risk_option("PROHIBIDO")
        self._post(med)

        alerts = Alert.objects.filter(player__in=self.players)
        self.assertEqual(alerts.count(), 3)
        for a in alerts:
            self.assertEqual(a.severity, "critical")
            self.assertIn("WADA", a.message)
            self.assertIn("PROHIBIDO", a.message)

    def test_a_conditional_drug_warns(self):
        self._post(self._risk_option("CONDICIONAL"))
        alerts = Alert.objects.filter(player__in=self.players)
        self.assertEqual(alerts.count(), 3)
        self.assertEqual({a.severity for a in alerts}, {"warning"})

    def test_a_permitted_drug_stays_silent(self):
        self._post(self._risk_option("PERMITIDO"))
        self.assertEqual(Alert.objects.filter(player__in=self.players).count(), 0)
