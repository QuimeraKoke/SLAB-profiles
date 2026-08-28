"""Medicación con varios registros independientes en una pantalla.

El modo `team_table` se probó primero y no servía acá: impone UNA carga
compartida repartida entre jugadores, y cada indicación es su propia receta —su
droga, su dosis, sus fechas—. Así que la grilla obligaba a fingir que había algo
en común. `multi` es el formulario individual apilado N veces.

Lo que estos tests protegen, por orden de qué dolería más:

  1. Que las alertas WADA sigan disparando POR REGISTRO. Una carga múltiple que
     las saltee sería peor que no tenerla: el médico creería estar cubierto.
  2. Que cada registro conserve LO SUYO. Es la diferencia entera con la grilla;
     si se filtran entre sí, el modo no sirve para nada.
  3. Que un registro sin dosis se guarde. `is_blank` contaba sólo `row_fields` y
     los descartaba sin decir nada.
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


class MedicacionMultiTests(TestCase):
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

    def _drug(self, level: str) -> str:
        field = next(f for f in self.template.config_schema["fields"]
                     if f["key"] == "medicamento")
        return next(o for o, r in (field.get("option_risk") or {}).items()
                    if (r or "").upper() == level)

    def _post(self, rows):
        return self.client.post("/api/results/team", data=json.dumps({
            "template_id": str(self.template.id),
            "category_id": str(self.cat.id),
            "recorded_at": "2026-08-26T12:00:00-04:00",
            # Vacío: en este modo cada fila trae TODO lo suyo. Es lo que
            # distingue esta forma de la grilla.
            "shared_data": {},
            "rows": rows,
        }), content_type="application/json")

    def _row(self, player, **data):
        return {"player_id": str(player.id), "result_data": data}

    # ── configuración ───────────────────────────────────────────────────
    def test_the_mode_is_offered_and_the_grid_is_not(self):
        modes = self.template.input_config["input_modes"]
        self.assertIn("multi", modes)
        # Se probó y la experiencia era forzada. Está fuera a propósito.
        self.assertNotIn("team_table", modes)

    def test_single_stays_the_default(self):
        self.assertEqual(self.template.input_config["default_input_mode"], "single")

    # ── lo que la grilla no permitía ────────────────────────────────────
    def test_each_record_keeps_its_own_everything(self):
        permitido, prohibido = self._drug("PERMITIDO"), self._drug("PROHIBIDO")
        r = self._post([
            self._row(self.players[0], medicamento=prohibido, dosis="40 mg",
                      via_admin="Oral", fecha_inicio="2026-08-26",
                      motivo="Lumbalgia"),
            self._row(self.players[1], medicamento=permitido, dosis="1 g",
                      via_admin="Oral", fecha_inicio="2026-08-20",
                      fecha_fin="2026-08-27", motivo="Cefalea"),
        ])
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r.json()["created"], 2)

        got = {
            er.player.last_name: er.result_data
            for er in ExamResult.objects.filter(
                template=self.template).select_related("player")
        }
        self.assertEqual(got["Apellido0"]["medicamento"], prohibido)
        self.assertEqual(got["Apellido0"]["motivo"], "Lumbalgia")
        self.assertEqual(got["Apellido1"]["medicamento"], permitido)
        self.assertEqual(got["Apellido1"]["fecha_fin"], "2026-08-27")
        # Y no se contaminan entre sí:
        self.assertNotIn("fecha_fin", got["Apellido0"])

    def test_a_record_without_a_dose_is_saved(self):
        """Un tópico sin dosis numérica es una indicación real y debe guardarse."""
        r = self._post([
            self._row(self.players[0], medicamento=self._drug("PERMITIDO"),
                      via_admin="Tópico", fecha_inicio="2026-08-26",
                      motivo="Contractura"),
        ])
        self.assertEqual(r.json()["created"], 1)
        self.assertEqual(r.json()["skipped"], 0)

    def test_declared_row_fields_do_not_silently_drop_a_record(self):
        """El caso donde `is_blank` importa, montado a propósito.

        `is_blank` contaba SÓLO los `row_fields` declarados: correcto para la
        grilla —ahí una fila jamás lleva otra cosa que sus celdas— y silencioso
        para `multi`, donde cada fila trae todos los campos. Con `row_fields:
        ["dosis"]` declarado, un tópico sin dosis desaparecía y la respuesta
        decía "guardado".

        Medicación ya no declara `team_table`, así que el escenario hay que
        armarlo: una plantilla puede tener los dos modos, y ahí el bug vuelve.
        """
        self.template.input_config = {
            **self.template.input_config,
            "input_modes": ["single", "multi", "team_table"],
            "team_table": {"shared_fields": [], "row_fields": ["dosis"]},
        }
        self.template.save(update_fields=["input_config"])

        r = self._post([
            self._row(self.players[0], medicamento=self._drug("PERMITIDO"),
                      via_admin="Tópico", fecha_inicio="2026-08-26",
                      motivo="Contractura"),
        ])
        self.assertEqual(r.json()["created"], 1, "el registro se descartó en silencio")
        self.assertEqual(r.json()["skipped"], 0)

    def test_a_row_with_only_a_player_is_skipped(self):
        # El otro lado: un bloque que el médico abrió y no llenó no debe crear
        # un registro vacío.
        r = self._post([self._row(self.players[0])])
        self.assertEqual(r.json()["created"], 0)
        self.assertEqual(r.json()["skipped"], 1)

    def test_the_same_player_twice_creates_two_records(self):
        # Dos indicaciones distintas el mismo día es normal, así que no se
        # deduplica. El formulario avisa, no bloquea.
        med = self._drug("PERMITIDO")
        r = self._post([
            self._row(self.players[0], medicamento=med, dosis="1 g",
                      fecha_inicio="2026-08-26"),
            self._row(self.players[0], medicamento=med, dosis="2 g",
                      fecha_inicio="2026-08-26"),
        ])
        self.assertEqual(r.json()["created"], 2)

    # ── lo que más importa ──────────────────────────────────────────────
    def test_wada_alerts_fire_per_record_not_per_submission(self):
        prohibido, permitido = self._drug("PROHIBIDO"), self._drug("PERMITIDO")
        self._post([
            self._row(self.players[0], medicamento=prohibido, dosis="40 mg",
                      fecha_inicio="2026-08-26"),
            self._row(self.players[1], medicamento=permitido, dosis="1 g",
                      fecha_inicio="2026-08-26"),
            self._row(self.players[2], medicamento=prohibido, dosis="20 mg",
                      fecha_inicio="2026-08-26"),
        ])
        alerts = Alert.objects.filter(player__in=self.players)
        self.assertEqual(alerts.count(), 2)
        self.assertEqual(
            {a.player.last_name for a in alerts}, {"Apellido0", "Apellido2"})
        for a in alerts:
            self.assertEqual(a.severity, "critical")
            self.assertIn("WADA", a.message)

    def test_a_conditional_drug_warns(self):
        self._post([
            self._row(self.players[0], medicamento=self._drug("CONDICIONAL"),
                      dosis="1 g", fecha_inicio="2026-08-26"),
        ])
        a = Alert.objects.get(player=self.players[0])
        self.assertEqual(a.severity, "warning")

    def test_a_template_with_neither_mode_is_refused(self):
        self.template.input_config = {
            **self.template.input_config, "input_modes": ["single"]}
        self.template.save(update_fields=["input_config"])
        r = self._post([
            self._row(self.players[0], medicamento=self._drug("PERMITIDO"),
                      dosis="1 g"),
        ])
        self.assertEqual(r.status_code, 400)

    def test_the_response_only_carries_created_rows_and_keeps_their_order(self):
        """De esto depende que un adjunto termine en el registro correcto.

        El componente sube los archivos DESPUÉS, contra el id de cada resultado.
        El servidor omite las filas vacías, así que `results` no se alinea con
        los bloques por índice — hay que rehacer la regla de "vacío" del lado del
        cliente y zipear en orden. Si el servidor dejara de devolverlos en orden
        de creación, los adjuntos se pegarían al jugador equivocado y nada
        fallaría a la vista.
        """
        med = self._drug("PERMITIDO")
        r = self._post([
            self._row(self.players[0]),                                  # vacía
            self._row(self.players[1], medicamento=med, dosis="1 g",
                      fecha_inicio="2026-08-27"),
            self._row(self.players[2], medicamento=med, dosis="2 g",
                      fecha_inicio="2026-08-27"),
        ])
        body = r.json()
        self.assertEqual((body["created"], body["skipped"]), (2, 1))
        self.assertEqual(
            [row["player_id"] for row in body["results"]],
            [str(self.players[1].id), str(self.players[2].id)],
        )
