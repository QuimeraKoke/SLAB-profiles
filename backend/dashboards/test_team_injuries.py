"""Team injury widgets: the counting rules, on real episodes."""
from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player, Position
from dashboards.models import TeamReportLayout, TeamReportSection, TeamReportWidget
from dashboards.team_aggregation import resolve_team_widget
from exams.models import Episode, ExamResult, ExamTemplate

HOY = date(2026, 9, 30)


def dt(y, m, d, h=12):
    return timezone.make_aware(datetime(y, m, d, h))


class TeamInjuryWidgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.medico = Department.objects.create(club=cls.club, name="Médico", slug="medico")
        call_command("seed_lesiones", "--club", "FC", "--create-if-missing", stdout=StringIO())
        cls.t = ExamTemplate.objects.get(slug="lesiones")
        cls.cat = Category.objects.create(club=cls.club, name="SUB-20")
        defensa = Position.objects.create(club=cls.club, abbreviation="DC", name="Central",
                                          role="Defensa", sort_order=1)
        cls.a = Player.objects.create(category=cls.cat, first_name="Ana", last_name="Soto",
                                      position=defensa)
        cls.b = Player.objects.create(category=cls.cat, first_name="Beto", last_name="Rios")
        layout = TeamReportLayout.objects.create(department=cls.medico, category=cls.cat,
                                                 name="Médico", scope="period")
        cls.sec = TeamReportSection.objects.create(layout=layout, title="Lesiones", sort_order=0)

    def lesion(self, p, inicio, fin=None, **datos):
        ep = Episode.objects.create(player=p, template=self.t, started_at=dt(*inicio))
        base = {"body_part": "Muslo", "lado": "Derecho", "modo": "Sobreuso/Gradual"} | datos
        ExamResult.objects.create(player=p, template=self.t, episode=ep, recorded_at=dt(*inicio),
                                  result_data=base | {"stage": "aguda"})
        if fin:
            ExamResult.objects.create(player=p, template=self.t, episode=ep,
                                      recorded_at=dt(*fin, h=18),
                                      result_data=base | {"stage": "closed"})
        return ep

    def widget(self, chart_type, **cfg):
        return TeamReportWidget.objects.create(section=self.sec, chart_type=chart_type,
                                               title="w", display_config=cfg)

    def resolver(self, w, desde=(2026, 3, 1)):
        with mock.patch("dashboards.team_injuries._hoy", return_value=HOY):
            return resolve_team_widget(w, self.cat, date_from=dt(*desde, h=0))

    def test_cuenta_las_iniciadas_y_los_dias_dentro_del_periodo(self):
        self.lesion(self.a, (2026, 1, 1), (2026, 4, 1))           # antes del período: 31 días dentro
        self.lesion(self.a, (2026, 5, 1), (2026, 5, 21))          # 20
        self.lesion(self.a, (2026, 5, 11), (2026, 5, 31))         # se solapa: +10, no +20
        self.lesion(self.b, (2026, 9, 20))                        # abierta: 10 hasta hoy
        k = self.resolver(self.widget("team_injury_kpis"))
        self.assertEqual(k["injuries"], 3, "la de enero no es nueva")
        self.assertEqual(k["days_lost"], 31 + 20 + 10 + 10)
        self.assertEqual((k["injured_now"], k["open_injuries"]), (1, 1))

    def test_dias_por_jugador_sin_contar_dos_veces(self):
        self.lesion(self.a, (2026, 5, 1), (2026, 5, 21))
        self.lesion(self.a, (2026, 5, 11), (2026, 5, 31))
        d = self.resolver(self.widget("team_injury_breakdown", dimension="player", measure="days"))
        self.assertEqual(d["items"][0]["label"], "Ana Soto")
        self.assertEqual(d["items"][0]["value"], 30)
        self.assertEqual(d["items"][0]["n"], 2)

    def test_desglose_por_region_posicion_y_exposicion(self):
        self.lesion(self.a, (2026, 5, 1), (2026, 5, 9), exposicion_club="Partido")
        self.lesion(self.b, (2026, 6, 1), (2026, 6, 9), body_part="Rodilla",
                    exposicion="Partido oficial")
        self.lesion(self.b, (2026, 7, 1), (2026, 7, 9), exposicion="Entrenamiento")
        region = self.resolver(self.widget("team_injury_breakdown", dimension="body_part"))
        self.assertEqual([(i["label"], i["value"]) for i in region["items"]],
                         [("Muslo", 2), ("Rodilla", 1)])
        pos = self.resolver(self.widget("team_injury_breakdown", dimension="position"))
        self.assertEqual({i["label"]: i["value"] for i in pos["items"]},
                         {"Defensa": 1, "Sin dato": 2})
        expo = self.resolver(self.widget("team_injury_breakdown", dimension="exposicion"))
        self.assertEqual({i["label"]: i["value"] for i in expo["items"]},
                         {"Partido": 2, "Entrenamiento": 1},
                         "el 'Partido' del club y el oficial confirmado son lo mismo acá")

    def test_listado_abiertas_y_del_periodo(self):
        self.lesion(self.a, (2025, 12, 1))                         # abierta desde antes
        self.lesion(self.b, (2026, 5, 1), (2026, 5, 9))
        abiertas = self.resolver(self.widget("team_injury_list", status="open"))
        self.assertEqual([r["player"] for r in abiertas["rows"]], ["Ana Soto"])
        self.assertEqual(abiertas["rows"][0]["days"], (HOY - date(2025, 12, 1)).days)
        periodo = self.resolver(self.widget("team_injury_list", status="period"))
        self.assertEqual([r["player"] for r in periodo["rows"]], ["Beto Rios"])

    def test_limite_agrupa_el_resto(self):
        for i, zona in enumerate(["Muslo", "Rodilla", "Tobillo", "Cadera"]):
            self.lesion(self.a, (2026, 5, 1 + i), (2026, 5, 9 + i), body_part=zona)
        d = self.resolver(self.widget("team_injury_breakdown", dimension="body_part", limit=2))
        self.assertEqual(d["items"][-1]["label"], "Otros (2)")
        self.assertEqual(d["total"], 4)

    def test_acepta_la_ventana_ingenua_de_la_api(self):
        """`/reports/{dept}` parsea `?date_from=` a un datetime SIN zona."""
        self.lesion(self.a, (2026, 5, 1), (2026, 5, 21))
        w = self.widget("team_injury_kpis")
        with mock.patch("dashboards.team_injuries._hoy", return_value=HOY):
            k = resolve_team_widget(w, self.cat, date_from=datetime(2026, 3, 1),
                                    date_to=datetime(2026, 9, 30))
        self.assertEqual((k["injuries"], k["days_lost"]), (1, 20))
