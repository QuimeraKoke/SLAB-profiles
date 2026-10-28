"""GPS a lo largo del tiempo: team widgets, the profile's timeline, the MD chips.

What these pin:

* a session is a (day, microcycle day) and its value is the mean PER PLAYER —
  the squad's total would grow with the number of players who trained;
* sessions and matches share one axis (several sources merge);
* the axis groups by the club's MICRO, falling back to the ISO week;
* the "tipo de día" chips filter only widgets that opt in (`md_filter`) — a
  check-in on the same page has no microcycle day and must not be emptied;
* the KPI card's `last` reads text as text (the last opponent).
"""
from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from api.auth import issue_token
from core.models import Category, Club, Department, Player, StaffMembership
from dashboards import gps_timeline
from dashboards.aggregation import resolve_widget
from dashboards.models import (
    Aggregation,
    DepartmentLayout,
    LayoutSection,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
    Widget,
    WidgetDataSource,
)
from dashboards.team_aggregation import resolve_team_widget
from exams.models import ExamResult, ExamTemplate

User = get_user_model()

CAMPOS = [
    {"key": "tot_dist", "label": "Distancia total", "type": "number", "unit": "m"},
    {"key": "hsr", "label": "HSR", "type": "number", "unit": "m"},
    {"key": "max_vel", "label": "Velocidad máxima", "type": "number", "unit": "km/h"},
    {"key": "md_label", "label": "Día de microciclo", "type": "text"},
    {"key": "microciclo", "label": "Microciclo", "type": "number"},
    {"key": "opponent", "label": "Rival", "type": "text"},
]


def dia(d: int) -> datetime:
    return timezone.make_aware(datetime(2026, 10, d, 12))


class GpsTimelineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2010", cohort_year=2010)
        cls.a = Player.objects.create(category=cls.cat, first_name="Ana", last_name="A")
        cls.b = Player.objects.create(category=cls.cat, first_name="Beto", last_name="B")
        cls.sesion = ExamTemplate.objects.create(
            department=cls.fisico, name="GPS sesión", slug="gps_sesion",
            config_schema={"fields": CAMPOS})
        cls.partido = ExamTemplate.objects.create(
            department=cls.fisico, name="GPS partido", slug="gps_partido",
            config_schema={"fields": CAMPOS})
        checkin = ExamTemplate.objects.create(
            department=cls.fisico, name="Check-in", slug="checkin",
            config_schema={"fields": [{"key": "sueno", "label": "Sueño", "type": "number"}]})

        def r(t, p, d, **datos):
            ExamResult.objects.create(template=t, player=p, recorded_at=dia(d), result_data=datos)

        # Micro 40: MD-2 (two players), MD (match); micro 41: MD-4.
        r(cls.sesion, cls.a, 20, tot_dist=4000, hsr=200, max_vel=28, md_label="MD-2", microciclo=40)
        r(cls.sesion, cls.b, 20, tot_dist=6000, hsr=400, max_vel=31, md_label="MD-2", microciclo=40)
        r(cls.partido, cls.a, 22, tot_dist=8000, hsr=700, max_vel=33, md_label="MD",
          microciclo=40, opponent="UNION ESPAÑOLA")
        r(cls.sesion, cls.a, 27, tot_dist=5000, hsr=300, max_vel=27, md_label="MD-4", microciclo=41)
        r(checkin, cls.a, 27, sueno=8)
        cls.checkin = checkin

    # ── helpers ─────────────────────────────────────────────────────────
    def team_widget(self, chart_type, keys, cfg, templates=None):
        layout, _ = TeamReportLayout.objects.get_or_create(
            department=self.fisico, category=self.cat, scope="period", slug="gps-tiempo",
            defaults={"name": "GPS en el tiempo"})
        section = TeamReportSection.objects.create(layout=layout, title="S")
        w = TeamReportWidget.objects.create(section=section, chart_type=chart_type,
                                            title="W", display_config=cfg)
        for i, t in enumerate(templates or [self.sesion, self.partido]):
            TeamReportWidgetDataSource.objects.create(
                widget=w, template=t, field_keys=keys, aggregation=Aggregation.ALL, sort_order=i)
        return w

    def player_widget(self, chart_type, keys, cfg, templates):
        layout, _ = DepartmentLayout.objects.get_or_create(
            department=self.fisico, category=self.cat, defaults={"name": "Físico"})
        section = LayoutSection.objects.create(layout=layout, title="S")
        w = Widget.objects.create(section=section, chart_type=chart_type, title="W",
                                  display_config=cfg)
        for i, t in enumerate(templates):
            WidgetDataSource.objects.create(widget=w, template=t, field_keys=keys,
                                            aggregation=Aggregation.ALL, sort_order=i)
        return w

    # ── shared rules ────────────────────────────────────────────────────
    def test_orden_de_microciclo(self):
        labels = ["MD+1", "MD", "MD-1", "MD-5", "otro", "MD+2"]
        self.assertEqual(sorted(labels, key=gps_timeline.md_sort_key),
                         ["MD-5", "MD-1", "MD", "MD+1", "MD+2", "otro"])

    def test_parse_md_descarta_lo_que_no_es_un_dia(self):
        self.assertEqual(gps_timeline.parse_md("md-2, MD ,MD+1,foo,,MD-2"), ["MD-2", "MD", "MD+1"])

    # ── team ────────────────────────────────────────────────────────────
    def test_cada_punto_es_una_sesion_con_la_media_por_jugador(self):
        w = self.team_widget("team_dual_axis_bar_line", ["tot_dist", "hsr"],
                             {"bars": "tot_dist", "line": "hsr"})
        p = resolve_team_widget(w, self.cat)["points"]
        self.assertEqual([x["md_label"] for x in p], ["MD-2", "MD", "MD-4"],
                         "sesiones y partidos en el mismo eje")
        self.assertEqual((p[0]["bars"], p[0]["line"], p[0]["n"]), (5000, 300, 2))
        self.assertEqual([x["micro"] for x in p], [40, 40, 41])

    def test_sin_micro_agrupa_por_semana(self):
        ExamResult.objects.filter(template=self.sesion).update(result_data={"tot_dist": 1, "hsr": 1})
        w = self.team_widget("team_dual_axis_bar_line", ["tot_dist", "hsr"], {},
                             templates=[self.sesion])
        p = resolve_team_widget(w, self.cat)["points"]
        self.assertTrue(all(x["micro"] is None and x["week"].startswith("2026-W") for x in p))

    def test_los_chips_filtran_solo_a_quien_los_sigue(self):
        sigue = self.team_widget("team_dual_axis_bar_line", ["tot_dist", "hsr"], {"md_filter": True})
        no = self.team_widget("team_dual_axis_bar_line", ["tot_dist", "hsr"], {})
        self.assertEqual([x["md_label"] for x in resolve_team_widget(
            sigue, self.cat, md_labels=["MD-4"])["points"]], ["MD-4"])
        self.assertEqual(len(resolve_team_widget(no, self.cat, md_labels=["MD-4"])["points"]), 3)

    def test_los_chips_no_ensanchan_el_only_values_del_widget(self):
        w = self.team_widget("team_dual_axis_bar_line", ["tot_dist", "hsr"],
                             {"md_filter": True, "only_values": {"md_label": ["MD-2"]}})
        self.assertEqual(resolve_team_widget(w, self.cat, md_labels=["MD-4"])["points"], [])

    def test_kpi_promedio_maximo_y_ultimo_texto(self):
        media = self.team_widget("team_kpi_card", ["tot_dist"], {"field": "tot_dist", "agg": "mean"})
        maximo = self.team_widget("team_kpi_card", ["max_vel"], {"field": "max_vel", "agg": "max"})
        rival = self.team_widget("team_kpi_card", ["opponent"], {"field": "opponent", "agg": "last"},
                                 templates=[self.partido])
        micro = self.team_widget("team_kpi_card", ["microciclo"], {"field": "microciclo", "agg": "last"})
        d = resolve_team_widget(media, self.cat)
        self.assertEqual((d["value"], d["n"]), (round((5000 + 8000 + 5000) / 3, 2), 3))
        d = resolve_team_widget(maximo, self.cat)
        self.assertEqual((d["value"], d["subject"]), (33, "Ana A"))
        d = resolve_team_widget(rival, self.cat)
        self.assertEqual((d["text"], d["value"], d["empty"]), ("UNION ESPAÑOLA", None, False))
        self.assertEqual(resolve_team_widget(micro, self.cat)["value"], 41)

    def test_la_tabla_es_una_fila_por_jugador_y_sesion(self):
        w = self.team_widget("team_session_log", ["tot_dist", "hsr"], {"limit": 3})
        d = resolve_team_widget(w, self.cat)
        self.assertEqual((len(d["rows"]), d["total"]), (3, 4))
        primera = d["rows"][0]
        self.assertEqual((primera["recorded_at"], primera["player"], primera["md_label"],
                          primera["micro"]), ("2026-10-27", "Ana A", "MD-4", 41))
        self.assertEqual(d["rows"][1]["note"], "UNION ESPAÑOLA")
        self.assertEqual([c["key"] for c in d["columns"]], ["tot_dist", "hsr"])

    # ── profile ─────────────────────────────────────────────────────────
    def test_perfil_une_sesion_y_partido_con_microciclo(self):
        w = self.player_widget("dual_axis_bar_line", ["tot_dist", "hsr"], {},
                               [self.sesion, self.partido])
        p = resolve_widget(w, self.a.id)["points"]
        self.assertEqual([(x["md_label"], x["micro"]) for x in p],
                         [("MD-2", 40), ("MD", 40), ("MD-4", 41)])

    def test_perfil_los_chips_no_vacian_lo_que_no_es_gps(self):
        gps = self.player_widget("session_log", ["tot_dist"], {"md_filter": True},
                                 [self.sesion, self.partido])
        check = self.player_widget("session_log", ["sueno"], {}, [self.checkin])
        self.assertEqual(len(resolve_widget(gps, self.a.id, md_labels=["MD"])["rows"]), 1)
        self.assertEqual(len(resolve_widget(check, self.a.id, md_labels=["MD"])["rows"]), 1)

    # ── API ─────────────────────────────────────────────────────────────
    def client_for(self):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        u = User.objects.create_user(username="staff", password="x")
        u.groups.add(Group.objects.get(name="Editor"))
        m = StaffMembership.objects.create(user=u, club=self.club, all_departments=True)
        m.categories.add(self.cat)
        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(u)[0]}")

    def test_el_reporte_ofrece_los_dias_que_hay_y_aplica_los_elegidos(self):
        self.team_widget("team_dual_axis_bar_line", ["tot_dist", "hsr"], {"md_filter": True})
        c = self.client_for()
        q = {"category_id": str(self.cat.id), "layout": "gps-tiempo",
             "date_from": "2026-10-01", "date_to": "2026-10-31"}
        d = c.get("/api/reports/fisico", q | {"md": "MD,MD-9"}).json()["layout"]
        self.assertEqual(d["md_filter"], {"enabled": True, "options": ["MD-4", "MD-2", "MD"],
                                          "selected": ["MD"]})
        pts = d["sections"][0]["widgets"][0]["data"]["points"]
        self.assertEqual([x["md_label"] for x in pts], ["MD"])

    def test_el_perfil_ofrece_los_dias_del_jugador(self):
        self.player_widget("session_log", ["tot_dist"], {"md_filter": True},
                           [self.sesion, self.partido])
        d = self.client_for().get(f"/api/players/{self.b.id}/views",
                                  {"department": "fisico"}).json()["layout"]
        self.assertEqual(d["md_filter"]["options"], ["MD-2"])
