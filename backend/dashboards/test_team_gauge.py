"""Físico › Evaluaciones: the gauge widget, the trend display options, the seed."""
from __future__ import annotations

from datetime import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from dashboards.models import (
    Aggregation,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
)
from dashboards.team_aggregation import resolve_team_widget
from dashboards.team_gauge import _reciprocal
from exams.models import ExamResult, ExamTemplate

# T10 in seconds: lower is better, so the fastest band is the one with no min.
BANDAS_T10 = [
    {"label": "Lento", "min": 1.8},
    {"label": "Medio", "min": 1.6, "max": 1.8},
    {"label": "Rápido", "max": 1.6},
]


def dt(y, m, d):
    return timezone.make_aware(datetime(y, m, d, 12))


class TeamGaugeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2010")
        cls.t = ExamTemplate.objects.create(
            department=cls.fisico, name="Carreras", slug="carreras", config_schema={"fields": [
                {"key": "t10_best", "label": "T10", "type": "number", "unit": "s",
                 "reference_ranges": BANDAS_T10},
                {"key": "t10_kmh", "label": "T10 km/h", "type": "number", "unit": "km/h"},
            ]})
        cls.a = Player.objects.create(category=cls.cat, first_name="Ana", last_name="Soto")
        cls.b = Player.objects.create(category=cls.cat, first_name="Beto", last_name="Rios")
        layout = TeamReportLayout.objects.create(department=cls.fisico, category=cls.cat,
                                                 name="General")
        cls.sec = TeamReportSection.objects.create(layout=layout, title="x", sort_order=0)

    def gauge(self, **cfg):
        w = TeamReportWidget.objects.create(section=self.sec, chart_type="team_gauge",
                                            title="Velocidad", display_config=cfg)
        TeamReportWidgetDataSource.objects.create(widget=w, template=self.t,
                                                  field_keys=["t10_kmh"],
                                                  aggregation=Aggregation.LATEST)
        return w

    def leer(self, p, when, **data):
        ExamResult.objects.create(player=p, template=self.t, recorded_at=dt(*when),
                                  result_data=data)

    def test_reciproco_invierte_y_cambia_de_lado(self):
        b = _reciprocal(BANDAS_T10, 36)
        self.assertEqual([x["label"] for x in b], ["Lento", "Medio", "Rápido"],
                         "ordenadas de menor a mayor km/h")
        self.assertEqual(b[0], {"label": "Lento", "max": 20.0})
        self.assertEqual(b[1], {"label": "Medio", "min": 20.0, "max": 22.5})
        self.assertEqual(b[2], {"label": "Rápido", "min": 22.5})

    def test_media_del_ultimo_valor_de_cada_jugador(self):
        self.leer(self.a, (2026, 1, 10), t10_kmh=18.0)
        self.leer(self.a, (2026, 6, 10), t10_kmh=20.0)   # el último de Ana
        self.leer(self.b, (2026, 6, 10), t10_kmh=22.0)
        f = resolve_team_widget(self.gauge(), self.cat)["fields"][0]
        self.assertEqual((f["value"], f["n"], f["min"], f["max"]), (21.0, 2, 20.0, 22.0))
        self.assertIsNone(f["subject"])
        self.assertEqual(f["bands"], [], "sin bands_from, km/h no tiene bandas propias")

    def test_un_jugador_filtrado_es_su_propio_valor(self):
        self.leer(self.a, (2026, 6, 10), t10_kmh=20.0)
        self.leer(self.b, (2026, 6, 10), t10_kmh=22.0)
        f = resolve_team_widget(self.gauge(), self.cat, player_ids=[self.b.id])["fields"][0]
        self.assertEqual((f["value"], f["subject"]), (22.0, "Beto Rios"))

    def test_bandas_prestadas_de_los_segundos(self):
        self.leer(self.a, (2026, 6, 10), t10_kmh=20.0)
        w = self.gauge(bands_from={"t10_kmh": {"field": "t10_best", "k": 36}})
        f = resolve_team_widget(w, self.cat)["fields"][0]
        self.assertEqual([b["label"] for b in f["bands"]], ["Lento", "Medio", "Rápido"])

    def test_sin_datos_en_el_periodo(self):
        self.leer(self.a, (2025, 1, 10), t10_kmh=20.0)
        out = resolve_team_widget(self.gauge(), self.cat, date_from=dt(2026, 1, 1))
        self.assertTrue(out["empty"])
        self.assertIsNone(out["fields"][0]["value"])

    def test_opciones_de_la_tendencia(self):
        self.leer(self.a, (2026, 6, 10), t10_best=1.7)
        w = TeamReportWidget.objects.create(
            section=self.sec, chart_type="team_trend_line", title="t",
            display_config={"point_labels": "value_pct", "style": "area", "series": "nope"})
        TeamReportWidgetDataSource.objects.create(widget=w, template=self.t,
                                                  field_keys=["t10_best"],
                                                  aggregation=Aggregation.ALL)
        out = resolve_team_widget(w, self.cat)
        self.assertEqual(out["display"],
                         {"point_labels": "value_pct", "style": "area", "series": "select"})


class SeedEvaluacionesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.t = {}
        for slug in ("carreras", "neuromuscular", "resistencia", "fuerza"):
            cls.t[slug] = ExamTemplate.objects.create(department=cls.fisico, name=slug,
                                                      slug=slug, config_schema={"fields": []})
        cls.mayor = Category.objects.create(club=cls.club, name="Serie 2010")
        cls.menor = Category.objects.create(club=cls.club, name="Serie 2016")
        for cat, slugs in ((cls.mayor, cls.t), (cls.menor, ["carreras", "neuromuscular"])):
            p = Player.objects.create(category=cat, first_name="X", last_name=cat.name)
            for slug in slugs:
                for d in range(5):
                    # The younger series runs carreras without the COD.
                    data = {"t10_best": 1.8, "cmj_best": 30, "palier": 15, "rm_estimado": 90}
                    data["cod_izq_best"] = 2.5 if cat == cls.mayor else None
                    ExamResult.objects.create(player=p, template=cls.t[slug],
                                              recorded_at=dt(2026, 3, d + 1), result_data=data)
        TeamReportLayout.objects.create(department=cls.fisico, category=cls.mayor,
                                        name="General", slug="general", sort_order=0)

    def seed(self, *extra):
        call_command("seed_evaluaciones_layout", "--club", "FC", "--commit", *extra,
                     stdout=StringIO())

    def secciones(self, cat):
        layout = TeamReportLayout.objects.get(department=self.fisico, category=cat,
                                              slug="evaluaciones")
        return layout, list(layout.sections.order_by("sort_order").values_list("title", flat=True))

    def test_cada_categoria_con_sus_bloques(self):
        self.seed()
        layout, mayor = self.secciones(self.mayor)
        self.assertEqual(mayor[0], "Última evaluación del plantel")
        self.assertIn("Resistencia — Yo-Yo IR1", mayor)
        self.assertEqual((layout.sort_order, layout.default_period_days), (1, 365),
                         "después de General, abre en el último año")
        _, menor = self.secciones(self.menor)
        self.assertNotIn("Fuerza — Sentadilla", menor)
        self.assertNotIn("Resistencia — Yo-Yo IR1", menor)
        self.assertNotIn("Cambio de dirección (505)", menor, "carreras sin COD")
        self.assertIn("Cambio de dirección (505)", mayor)
        matriz = TeamReportWidget.objects.get(section__layout__category=self.menor,
                                              chart_type="team_roster_matrix")
        self.assertEqual(sorted(matriz.data_sources.values_list("template__slug", flat=True)),
                         ["carreras", "neuromuscular"])

    def test_idempotente_y_rebuild(self):
        self.seed()
        self.seed()
        self.assertEqual(TeamReportLayout.objects.filter(slug="evaluaciones").count(), 2)
        layout, antes = self.secciones(self.mayor)
        layout.sections.first().delete()
        self.seed()
        self.assertEqual(len(self.secciones(self.mayor)[1]), len(antes) - 1, "sin --rebuild no toca")
        self.seed("--rebuild")
        self.assertEqual(self.secciones(self.mayor)[1], antes)
