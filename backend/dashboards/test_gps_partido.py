"""Físico › GPS partido: match days as the selector, per-widget scope, the
substitutes filter, "vs previous matches", per-match buckets, the seed."""
from __future__ import annotations

from datetime import datetime
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from dashboards import match_days
from dashboards.models import (
    Aggregation,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
)
from dashboards.team_aggregation import resolve_team_widget
from events.models import Event
from exams.models import ExamResult, ExamTemplate


def dia(m, d):
    return timezone.make_aware(datetime(2026, m, d))


class GpsPartidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.cat = Category.objects.create(club=cls.club, name="SUB-20")
        cls.t = ExamTemplate.objects.create(
            department=cls.fisico, name="GPS partido", slug="gps_partido",
            config_schema={"fields": [
                {"key": "tot_dur", "label": "Duración", "type": "number", "unit": "min"},
                {"key": "tot_dist", "label": "Distancia", "type": "number", "unit": "m"},
                {"key": "max_vel", "label": "Vmáx", "type": "number", "unit": "km/h"},
            ]})
        cls.a = Player.objects.create(category=cls.cat, first_name="Ana", last_name="Soto")
        cls.b = Player.objects.create(category=cls.cat, first_name="Beto", last_name="Rios")
        cls.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")

    def gps(self, p, when, rival="PALESTINO", hoja="U20", event=None, **data):
        return ExamResult.objects.create(
            player=p, template=self.t, recorded_at=when, event=event,
            result_data={"sesion": f"Partido {when.date()} · MD · {rival}",
                         "origen_hoja": hoja} | data)

    def layout(self):
        layout = TeamReportLayout.objects.create(
            department=self.fisico, category=self.cat, name="GPS partido", slug="gps-partido",
            match_selector_config={"enabled": True, "source": "gps_days", "required": True})
        sec = TeamReportSection.objects.create(layout=layout, title="x", sort_order=0)
        return sec

    def widget(self, sec, chart_type, keys, agg=Aggregation.LATEST, **cfg):
        w = TeamReportWidget.objects.create(section=sec, chart_type=chart_type, title=chart_type,
                                            display_config=cfg,
                                            sort_order=sec.widgets.count())
        TeamReportWidgetDataSource.objects.create(widget=w, template=self.t, field_keys=keys,
                                                  aggregation=agg)
        return w

    def report(self, match=None):
        from api.routers import get_team_report

        r = RequestFactory().get("/x")
        r.user = self.su
        return get_team_report(r, department_slug="fisico", category_id=str(self.cat.id),
                               layout="gps-partido", match_id=match,
                               date_from="2026-01-01", date_to="2026-12-31")

    # -- match days -------------------------------------------------------
    def test_opciones_son_los_dias_con_rival_y_equipos(self):
        ev = Event.objects.create(club=self.club, category=self.cat, event_type="match",
                                  department=self.fisico,
                                  title="Universidad de Chile vs DEPORTES TEMUCO",
                                  starts_at=dia(9, 26).replace(hour=15))
        self.gps(self.a, dia(9, 26), event=ev, tot_dist=9000)
        self.gps(self.b, dia(9, 26), hoja="U18", rival="DEPORTES TEMUCO", tot_dist=8000)
        self.gps(self.a, dia(9, 5), rival="SANTIAGO WANDERERS", tot_dist=8500)
        opts = match_days.options([self.a.id, self.b.id])
        self.assertEqual([o["id"] for o in opts], ["2026-09-26", "2026-09-05"])
        self.assertEqual(opts[0]["title"], "vs Deportes Temuco")
        self.assertEqual(opts[0]["location"], "U20 · U18")
        self.assertEqual(opts[1]["title"], "vs Santiago Wanderers", "sin evento: rival de la sesión")

    def test_el_widget_de_partido_lee_el_dia_y_el_de_periodo_lo_marca(self):
        sec = self.layout()
        self.widget(sec, "team_match_summary", ["tot_dist"], scope="match", headline="avg")
        self.widget(sec, "team_trend_line", ["tot_dist"], Aggregation.ALL, bucket_size="day")
        self.gps(self.a, dia(9, 5), tot_dist=8000)
        self.gps(self.a, dia(9, 26), tot_dist=9000)
        out = self.report()
        sel = out["layout"]["match_selector"]
        self.assertEqual((sel["source"], sel["selected_id"]), ("gps_days", "2026-09-26"))
        resumen, tendencia = [w["data"] for w in out["layout"]["sections"][0]["widgets"]]
        self.assertEqual(resumen["cards"][0]["avg"], 9000, "solo el partido elegido")
        self.assertEqual(len(tendencia["buckets"]), 2, "la tendencia sigue el período")
        self.assertEqual(tendencia["highlight_iso"], "2026-09-26")
        self.assertEqual(tendencia["buckets"][0]["detail"], "vs Palestino")
        out = self.report(match="2026-09-05")
        self.assertEqual(out["layout"]["sections"][0]["widgets"][0]["data"]["cards"][0]["avg"], 8000)
        out = self.report(match="basura")
        self.assertEqual(out["layout"]["match_selector"]["selected_id"], "2026-09-26")

    def test_equipo_partidos_del_equipo_y_convocados_marcados(self):
        """SUB-20 ve el partido de la U20 con todos los que lo jugaron — un
        Serie 2008 que jugó arriba, marcado como convocado —, y no el partido
        de la U18 del mismo día de sus propios jugadores."""
        from core.models import Bracket, TeamSeason

        sub20 = Bracket.objects.create(code="S20", name="Sub 20", age=20, order=8)
        sub18 = Bracket.objects.create(code="S18", name="Sub 18", age=18, order=7)
        s2008 = Category.objects.create(club=self.club, name="Serie 2008")
        TeamSeason.objects.create(team=self.cat, season=2026, bracket=sub20)
        TeamSeason.objects.create(team=s2008, season=2026, bracket=sub18)
        prestado = Player.objects.create(category=s2008, first_name="Ciro", last_name="Paz")
        sec = self.layout()
        TeamReportLayout.objects.filter(pk=sec.layout_id).update(match_selector_config={
            "enabled": True, "source": "gps_days", "required": True, "team": True})
        self.widget(sec, "team_roster_matrix", ["tot_dist"], scope="match")
        self.gps(self.a, dia(9, 26), hoja="U20", tot_dist=9000)
        self.gps(prestado, dia(9, 26), hoja="U20", tot_dist=8000)
        self.gps(self.b, dia(9, 26), hoja="U18", tot_dist=7000)     # la U18, no la U20
        self.gps(self.b, dia(9, 20), hoja="U18", tot_dist=7000)     # día solo de la U18
        out = self.report()
        sel = out["layout"]["match_selector"]
        self.assertEqual([o["id"] for o in sel["options"]], ["2026-09-26"])
        data = out["layout"]["sections"][0]["widgets"][0]["data"]
        valor = lambda r: (r["cells"].get("tot_dist") or {}).get("value")
        jugaron = {r["player_id"]: valor(r) for r in data["rows"] if valor(r) is not None}
        self.assertEqual(jugaron, {str(self.a.id): 9000, str(prestado.id): 8000})
        self.assertEqual(data["call_up_player_ids"], [str(prestado.id)])

    def test_equipo_no_mezcla_clubes(self):
        """Un club demo con su Sub 20 no ve los partidos de la U20 del club
        real (ni a sus jugadores), aunque la hoja y el bracket se llamen igual."""
        from core.models import Bracket, TeamSeason

        from dashboards import team_scope

        sub20 = Bracket.objects.create(code="S20", name="Sub 20", age=20, order=8)
        TeamSeason.objects.create(team=self.cat, season=2026, bracket=sub20)
        otro = Club.objects.create(name="Demo")
        cat_demo = Category.objects.create(club=otro, name="Sub 20")
        TeamSeason.objects.create(team=cat_demo, season=2026, bracket=sub20)
        self.gps(self.a, dia(9, 26), hoja="U20", tot_dist=9000)
        scope = team_scope.for_category(cat_demo)
        self.assertFalse(ExamResult.objects.filter(scope.rows).exists())
        self.assertEqual(scope.players, frozenset())

    # -- substitutes, previous matches, gauge -----------------------------
    def test_min_values_deja_fuera_a_los_suplentes(self):
        sec = self.layout()
        w = self.widget(sec, "team_match_summary", ["tot_dist"], headline="avg",
                        min_values={"tot_dur": 60})
        self.gps(self.a, dia(9, 26), tot_dur=90, tot_dist=9000)
        self.gps(self.b, dia(9, 26), tot_dur=12, tot_dist=1500)
        self.assertEqual(resolve_team_widget(w, self.cat)["cards"][0]["avg"], 9000)

    def test_only_values_filtra_por_dia_de_microciclo(self):
        sec = self.layout()
        w = self.widget(sec, "team_match_summary", ["tot_dist"], headline="avg",
                        only_values={"md_label": ["MD-1"]})
        self.gps(self.a, dia(9, 25), tot_dist=4000, md_label="MD-1")
        self.gps(self.b, dia(9, 23), tot_dist=6000, md_label="MD-3")
        self.assertEqual(resolve_team_widget(w, self.cat)["cards"][0]["avg"], 4000)

    def test_compara_con_los_partidos_anteriores(self):
        sec = self.layout()
        w = self.widget(sec, "team_match_summary", ["tot_dist"], headline="avg",
                        compare_previous=2)
        for d, v in ((1, 7000), (8, 8000), (15, 10000), (22, 9900)):
            self.gps(self.a, dia(8, d), tot_dist=v)
        lo, hi = match_days.day_bounds(dia(8, 22).date())
        card = resolve_team_widget(w, self.cat, date_from=lo, date_to=hi)["cards"][0]
        self.assertEqual(card["prev_avg"], 9000, "media de 8 y 15 de agosto, no del 1")
        self.assertEqual(card["delta_pct"], 10.0)

    def test_gauge_muestra_la_media_y_el_maximo_con_su_dueno(self):
        sec = self.layout()
        w = self.widget(sec, "team_gauge", ["max_vel"], show_top=True)
        self.gps(self.a, dia(9, 26), max_vel=30.0)
        self.gps(self.b, dia(9, 26), max_vel=32.0)
        f = resolve_team_widget(w, self.cat)["fields"][0]
        self.assertEqual((f["value"], f["top"], f["top_subject"]), (31.0, 32.0, "Beto Rios"))

    # -- seed ---------------------------------------------------------------
    def test_seed_umbral_de_suplente_segun_la_categoria(self):
        for d in range(1, 5):
            self.gps(self.a, dia(8, d), tot_dur=90, tot_dist=9000)
            self.gps(self.b, dia(8, d), tot_dur=20, tot_dist=2000)
        call_command("seed_gps_partido_layout", "--club", "FC", "--commit", stdout=StringIO())
        call_command("seed_gps_partido_layout", "--club", "FC", "--commit", stdout=StringIO())
        layout = TeamReportLayout.objects.get(slug="gps-partido", category=self.cat)
        self.assertEqual(layout.match_selector_config["source"], "gps_days")
        self.assertEqual(layout.default_period_days, 365)
        resumen = TeamReportWidget.objects.get(section__layout=layout,
                                               chart_type="team_match_summary")
        self.assertEqual(resumen.display_config["min_values"], {"tot_dur": 60})
        self.assertEqual(TeamReportWidget.objects.filter(section__layout=layout).count(), 6,
                         "correrlo dos veces no duplica")
