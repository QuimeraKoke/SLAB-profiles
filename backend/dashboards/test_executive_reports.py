"""Executive reports: the period every Word report covers, the indicators it
picks, and the period-scoped player summaries behind the Resumen S-LAB."""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from docx import Document

from core.models import Category, Club, Department, Player
from dashboards.docx import executive as ex
from dashboards.report_period import Periodo, formato
from exams.models import ExamResult, ExamTemplate
from goals.models import Alert, AlertSeverity

AHORA = timezone.make_aware(datetime(2026, 10, 21, 12))
N = {"resumen": "Resumen del período.", "hallazgos": ["h1", "h2", "h3", "h4"],
     "objetivos": [{"foco": "Foco", "estrategia": "Plan"}], "analisis": ["a1"],
     "conclusiones": ["c1"]}


def dias(n):
    return AHORA - timedelta(days=n)


class PeriodoTests(TestCase):
    def test_por_defecto_treinta_dias_y_el_anterior_de_igual_largo(self):
        p = Periodo.de(None, AHORA)
        self.assertEqual(p.dias, 30)
        a = p.anterior()
        self.assertEqual(a.dias, 30)
        self.assertLess(a.hasta, p.desde)

    def test_formato_desconocido_es_ejecutivo(self):
        self.assertEqual(formato("pdf"), "ejecutivo")
        self.assertEqual(formato("completo"), "completo")


class ReportesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fis = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.cat = Category.objects.create(club=cls.club, name="SUB-20")
        cls.cat.departments.add(cls.fis)
        cls.p = Player.objects.create(category=cls.cat, first_name="Ana", last_name="Soto")
        cls.q = Player.objects.create(category=cls.cat, first_name="Beto", last_name="Rios")
        cls.wellness = cls._tpl("checkin", [
            {"key": f"q{i}", "label": f"Pregunta {i}", "type": "number",
             "reference_ranges": [{"label": "Normal", "min": 0, "max": 10}]} for i in range(5)])
        cls.saltos = cls._tpl("neuromuscular", [
            {"key": "cmj_1", "label": "CMJ 1", "type": "number"},
            {"key": "cmj_best", "label": "CMJ — mejor", "type": "calculated",
             "direction_of_good": "up"},
            {"key": "cmj_prom", "label": "CMJ — promedio", "type": "calculated",
             "direction_of_good": "up"}])
        cls.gps = cls._tpl("gps_sesion", [
            {"key": "tot_dist", "label": "Distancia", "type": "number", "unit": "m",
             "chart_type": "line"}])

    @classmethod
    def _tpl(cls, slug, fields):
        t = ExamTemplate.objects.create(department=cls.fis, name=slug, slug=slug,
                                        config_schema={"fields": fields})
        t.applicable_categories.add(cls.cat)
        return t

    def leer(self, t, p, cuando, **data):
        ExamResult.objects.create(player=p, template=t, recorded_at=cuando, result_data=data)

    def periodo(self):
        return Periodo.de(dias(30), AHORA)

    # -- indicators ---------------------------------------------------------
    def test_mejora_o_empeora_segun_la_direccion(self):
        self.leer(self.saltos, self.p, dias(40), cmj_best=40.0)
        self.leer(self.saltos, self.p, dias(5), cmj_best=36.0)
        i = next(x for x in ex.indicadores([self.saltos], self.cat, [self.p.id], self.periodo())
                 if x.label == "CMJ — mejor")
        self.assertEqual((i.valor, i.previo, round(i.cambio_pct)), (36.0, 40.0, -10))
        self.assertEqual(i.lectura_cambio, "empeora")

    def test_un_test_un_numero_y_ningun_intento_crudo(self):
        self.leer(self.saltos, self.p, dias(5), cmj_1=35.0, cmj_best=36.0, cmj_prom=35.5)
        labels = [i.label for i in ex.indicadores([self.saltos], self.cat, [self.p.id],
                                                  self.periodo())]
        self.assertEqual(labels, ["CMJ — mejor"])

    def test_dos_por_plantilla_para_que_entren_todas(self):
        for d in (3, 6, 9):
            self.leer(self.wellness, self.p, dias(d), **{f"q{i}": 5.0 for i in range(5)})
        self.leer(self.saltos, self.p, dias(5), cmj_best=36.0)
        self.leer(self.gps, self.p, dias(5), tot_dist=6000.0)
        items = ex.indicadores([self.wellness, self.saltos, self.gps], self.cat, [self.p.id],
                               self.periodo())
        self.assertEqual(sum(1 for i in items if i.label.startswith("Pregunta")), 2)
        self.assertIn("Distancia", [i.label for i in items], "la carga GPS también entra")

    def test_el_plantel_es_la_media_de_todos(self):
        self.leer(self.gps, self.p, dias(5), tot_dist=6000.0)
        self.leer(self.gps, self.q, dias(4), tot_dist=8000.0)
        self.leer(self.gps, self.q, dias(3), tot_dist=7000.0)
        i = ex.indicadores([self.gps], self.cat, [self.p.id, self.q.id], self.periodo())[0]
        self.assertEqual((i.valor, i.agregacion), (7000.0, "media"))

    # -- the Resumen S-LAB, period-scoped --------------------------------------
    def test_las_alertas_del_resumen_son_las_del_periodo(self):
        from api.triage import build_triage_payload

        vieja = Alert.objects.create(player=self.p, severity=AlertSeverity.WARNING,
                                     message="vieja", source_type="threshold")
        Alert.objects.filter(pk=vieja.pk).update(fired_at=dias(60), last_fired_at=dias(60))
        Alert.objects.create(player=self.p, severity=AlertSeverity.CRITICAL,
                             message="nueva", source_type="threshold")
        con = build_triage_payload(self.p, dias(30), timezone.now())
        self.assertEqual([a["message"] for a in con["alerts"]], ["nueva"])

    # -- the documents ------------------------------------------------------------
    def _doc(self, b):
        d = Document(BytesIO(b))
        return [p.text for p in d.paragraphs]

    @mock.patch("dashboards.pdf.narrative.generate_player_narrative", return_value=N)
    def test_informe_ejecutivo_del_jugador(self, _):
        from dashboards.docx.player_report_docx import render_or_get_player_docx

        self.leer(self.saltos, self.p, timezone.now() - timedelta(days=3), cmj_best=36.0)
        textos = self._doc(render_or_get_player_docx(
            player=self.p, department=self.fis, date_from=None, date_to=None,
            formato="ejecutivo"))
        for titulo in ("Lo esencial", "Indicadores del período", "Disponibilidad",
                       "Alertas del período", "Próximos pasos"):
            self.assertIn(titulo.upper(), [t.upper() for t in textos])
        self.assertIn("h3", textos)
        self.assertNotIn("h4", textos, "tres hallazgos, no todos")

    @mock.patch("dashboards.pdf.narrative.generate_player_narrative", return_value=N)
    def test_informe_completo_del_jugador_trae_el_periodo(self, _):
        from dashboards.docx.player_report_docx import render_or_get_player_docx

        textos = self._doc(render_or_get_player_docx(
            player=self.p, department=self.fis, date_from=dias(10), date_to=AHORA,
            formato="completo"))
        self.assertTrue(any("(10 días)" in t for t in textos), "el período está en la portada")

    @mock.patch("dashboards.pdf.narrative.generate_player_analysis_narrative", return_value=N)
    def test_resumen_ejecutivo(self, _):
        from dashboards.docx.player_triage_docx import render_or_get_triage_docx

        textos = self._doc(render_or_get_triage_docx(self.p, periodo=self.periodo(),
                                                     formato="ejecutivo"))
        self.assertIn("PARTIDOS DEL PERÍODO", [t.upper() for t in textos])

    @mock.patch("dashboards.pdf.narrative.generate_player_narrative", return_value=N)
    def test_informe_ejecutivo_del_equipo(self, _):
        from dashboards.docx.team_report_docx import render_team_docx

        self.leer(self.gps, self.p, timezone.now() - timedelta(days=2), tot_dist=6000.0)
        textos = self._doc(render_team_docx(department=self.fis, category=self.cat,
                                            formato="ejecutivo"))
        self.assertIn("INDICADORES DEL PLANTEL", [t.upper() for t in textos])
