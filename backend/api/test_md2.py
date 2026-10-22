"""MD+2 screen (`api/md2.py`): the match it picks, who played, saving and the lights."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from api import md2
from core.models import Category, Club, Department, Player
from events.models import Event, EventParticipant
from exams.models import ExamResult, ExamTemplate


class Md2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.med = Department.objects.create(club=cls.club, name="Médico", slug="medico")
        cls.cat = Category.objects.create(club=cls.club, name="Primer Equipo", is_senior=True)
        cls.otra = Category.objects.create(club=cls.club, name="Serie 2015")
        cls.a = Player.objects.create(category=cls.cat, first_name="Ana", last_name="Soto")
        cls.b = Player.objects.create(category=cls.cat, first_name="Beto", last_name="Rios")

        def tpl(slug, fields):
            t = ExamTemplate.objects.create(department=cls.med, name=slug, slug=slug,
                                            config_schema={"fields": fields},
                                            input_config={"input_modes": ["team_table"]})
            t.applicable_categories.add(cls.cat)
            return t
        cls.ck = tpl("ck", [{"key": "valor", "label": "CK", "type": "number", "unit": "U/L",
                             "reference_ranges": [
                                 {"label": "Normal", "max": 500, "color": "#16a34a"},
                                 {"label": "Elevada", "min": 500, "max": 1000, "color": "#f59e0b"},
                                 {"label": "Alta", "min": 1000, "color": "#dc2626", "alert": True}]}])
        cls.cmj = tpl("cmj", [{"key": "jump_height", "label": "Altura", "type": "number",
                               "unit": "cm"}])
        cls.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")

        hace = timezone.now() - timedelta(days=2)
        # The real game: a sheet with players.
        cls.partido = Event.objects.create(club=cls.club, category=cls.cat, department=cls.med,
                                           event_type="match", title="FC vs Rival", starts_at=hace)
        EventParticipant.objects.create(event=cls.partido, player=cls.a, match_role="titular")
        EventParticipant.objects.create(event=cls.partido, player=cls.b,
                                        match_role="suplente_no_ingresa")
        # Its duplicate fixture (no sheet) a day later, and a scheduled cup today.
        Event.objects.create(club=cls.club, category=cls.cat, department=cls.med,
                             event_type="match", title="FC vs Rival (fixture)",
                             starts_at=hace + timedelta(days=1))
        Event.objects.create(club=cls.club, category=cls.cat, department=cls.med,
                             event_type="match", title="Copa", starts_at=timezone.now(),
                             metadata={"status": "SCHEDULED"})

    def ctx(self):
        return md2.contexto(self.cat, md2.partidos_jugados(self.cat)[0])

    def test_elige_el_ultimo_partido_jugado(self):
        self.assertEqual(md2.partidos_jugados(self.cat)[0], self.partido)

    def test_jugaron_primero_segun_el_rol(self):
        filas = md2.payload(self.ctx())["jugadores"]
        self.assertEqual([(f["nombre"], f["jugo"]) for f in filas],
                         [("Ana Soto", True), ("Beto Rios", False)])

    def test_solo_las_pruebas_de_la_categoria(self):
        self.assertEqual([p.key for p, _ in self.ctx().pruebas], ["ck", "cmj"])
        self.assertEqual(md2.contexto(self.otra, self.partido).pruebas, [])

    def test_guarda_vinculado_y_actualiza_sin_duplicar(self):
        ctx = self.ctx()
        permitidos = {str(self.a.id), str(self.b.id)}
        out = md2.guardar(ctx, [{"player_id": str(self.a.id), "valores": {"ck": {"valor": "1250"}}}],
                          allowed_players=permitidos)
        self.assertEqual(out, {"creados": 1, "actualizados": 0})
        r = ExamResult.objects.get(template=self.ck)
        self.assertEqual((r.event, r.result_data["md_label"], r.result_data["valor"]),
                         (self.partido, "MD+2", 1250.0))
        self.assertEqual(timezone.localtime(r.recorded_at).date(), md2.fecha_md2(self.partido))
        out = md2.guardar(ctx, [{"player_id": str(self.a.id), "valores": {"ck": {"valor": "900"}}}],
                          allowed_players=permitidos)
        self.assertEqual(out, {"creados": 0, "actualizados": 1})
        self.assertEqual(ExamResult.objects.get(template=self.ck).result_data["valor"], 900.0)

    def test_no_guarda_jugadores_fuera_de_su_alcance(self):
        out = md2.guardar(self.ctx(), [{"player_id": str(self.a.id), "valores": {"ck": {"valor": 1}}}],
                          allowed_players=set())
        self.assertEqual(out["creados"], 0)

    def test_semaforo_ck_por_banda_y_cmj_frente_a_su_referencia(self):
        for d, v in ((40, 40.0), (30, 40.0), (20, 40.0)):
            ExamResult.objects.create(player=self.a, template=self.cmj, result_data={"jump_height": v},
                                      recorded_at=timezone.now() - timedelta(days=d))
        md2.guardar(self.ctx(), [{"player_id": str(self.a.id),
                                  "valores": {"ck": {"valor": 1250}, "cmj": {"jump_height": 35}}}],
                    allowed_players={str(self.a.id)})
        fila = md2.payload(self.ctx())["jugadores"][0]
        self.assertEqual(fila["luces"]["ck"]["nivel"], "rojo")
        self.assertEqual(fila["luces"]["cmj"]["cambio_pct"], -12.5)
        self.assertEqual(fila["luces"]["cmj"]["nivel"], "rojo")
        self.assertEqual(fila["general"], "rojo")

    def test_colores_del_club_a_semaforo(self):
        self.assertEqual(md2._nivel_de_color("#FF0000"), "rojo")
        self.assertEqual(md2._nivel_de_color("#FF9900"), "amarillo")
        self.assertEqual(md2._nivel_de_color("#FFFF00"), "amarillo")
        self.assertEqual(md2._nivel_de_color("#92D050"), "verde")
        self.assertEqual(md2._nivel_de_color("#0000FF"), "verde")

    def test_endpoint(self):
        from api.routers import md2_view

        r = RequestFactory().get("/x")
        r.user = self.su
        out = md2_view(r, category_id=str(self.cat.id))
        self.assertEqual(out["partido"]["id"], str(self.partido.id))
        self.assertEqual(len(out["opciones"]), 1, "el duplicado vacío no es una opción")
