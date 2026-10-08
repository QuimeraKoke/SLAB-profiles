"""Físico › "GPS partido": the club's match GPS sheet as a match-based team layout.

The page opens on the latest match of the category's TEAM (a selector of match
DAYS taken from the GPS itself — `dashboards.match_days` — because part of the
formativo's match GPS has no Event, and the U11 has no fixtures at all), with
everyone who played it: players of other cohorts are flagged like call-ups
(`dashboards.team_scope`). It reads in two halves:

    El partido                    the chosen match
      Resumen del partido         mean per player with ≥ ⅔ of a match, vs the 5 before
      Velocidad y distancia       gauge: squad mean in its range + the top, and whose
      HSR por jugador             ranking
      Jugador por jugador         every player's numbers, against the squad
    Evolución por partido         the page's period (a year by default)
      Carga externa               one point per match, metric selector
      Aceleraciones y desaceleraciones   both lines together

What changed from the club's Power BI and why is in STATUS.md (§3.64): its
cards summed a season, its gauge summed top speeds (16.159 km/h), its five
two-axis charts are one chart with a selector, and its means counted a
10-minute substitute like a full match.

Categories with match GPS only (SUB-20 and Series 2008–2015 today).
Idempotent; `--rebuild` replaces the sections of an existing one.

    docker compose exec backend python manage.py seed_gps_partido_layout            # plan
    docker compose exec backend python manage.py seed_gps_partido_layout --commit
"""
from __future__ import annotations

from statistics import median

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from core.models import Category, Department
from dashboards.models import (
    Aggregation,
    ChartType,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
)
from exams.models import ExamResult, ExamTemplate

NOMBRE = "GPS partido"
SLUG = "gps-partido"
PERIODO_DIAS = 365
MIN_DIAS = 3            # fewer match days than this is not an evolution
# A substitute is whoever played under ⅔ of a full match — and a full match
# is 90+ minutes for SUB-20 but under 60 for the U11, so the threshold comes
# from each category's own data (median of the longest duration per match).
FRACCION_TITULAR = 2 / 3
PREVIOS = 5

FORMATIVO = ["SUB-20"] + [f"Serie {y}" for y in range(2008, 2019)]

# `team`: the category's TEAM's matches with everyone who played them,
# other cohorts flagged like call-ups (`dashboards.team_scope`).
SELECTOR = {"enabled": True, "source": "gps_days", "team": True, "required": True,
            "label": "Partido", "show_recent": 0}

PARTIDO = {"scope": "match"}


def secciones(min_min: int) -> list[dict]:
    SIN_SUPLENTES = {"min_values": {"tot_dur": min_min}}
    MIN_MINUTOS = min_min
    return [
        {"title": "El partido", "widgets": [
            {"chart_type": ChartType.TEAM_MATCH_SUMMARY.value, "title": "Resumen del partido",
             "description": f"Media por jugador con ≥ {MIN_MINUTOS} min, frente a los "
                            f"{PREVIOS} partidos anteriores.",
             "column_span": 12,
             "display_config": PARTIDO | SIN_SUPLENTES | {
                 "headline": "avg", "compare_previous": PREVIOS,
                 "per_player_aggregator": "latest"},
             "keys": ["tot_dist", "hsr", "mpm", "sprint_dist", "sprints", "max_vel", "acc", "dec"],
             "aggregation": Aggregation.LATEST},
            {"chart_type": ChartType.TEAM_GAUGE.value, "title": "Velocidad y distancia",
             "description": "Media del plantel entre el menor y el mayor registro, y el máximo.",
             "column_span": 4, "display_config": PARTIDO | {"show_top": True},
             "keys": ["max_vel", "tot_dist"], "aggregation": Aggregation.LATEST},
            {"chart_type": ChartType.TEAM_LEADERBOARD.value, "title": "HSR por jugador",
             "description": "Metros a más de 20 km/h en el partido.",
             "column_span": 8,
             "display_config": PARTIDO | {"aggregator": "latest", "limit": 20, "order": "desc"},
             "keys": ["hsr"], "aggregation": Aggregation.LATEST},
            {"chart_type": ChartType.TEAM_ROSTER_MATRIX.value, "title": "Jugador por jugador",
             "description": "Cada celda frente al resto del plantel en el partido.",
             "column_span": 12,
             "display_config": PARTIDO | {"coloring": "vs_team_range"},
             "keys": ["tot_dur", "tot_dist", "mpm", "hsr", "sprint_dist", "sprints", "max_vel",
                      "acc", "dec"],
             "aggregation": Aggregation.LATEST},
        ]},
        {"title": "Evolución por partido", "widgets": [
            {"chart_type": ChartType.TEAM_TREND_LINE.value, "title": "Carga externa",
             "description": f"Media por jugador con ≥ {MIN_MINUTOS} min, un punto por partido.",
             "column_span": 12,
             "display_config": SIN_SUPLENTES | {"bucket_size": "day", "point_labels": "value",
                                                "style": "area"},
             "keys": ["tot_dist", "hsr", "mpm", "tot_dur", "sprint_dist", "sprints", "max_vel"],
             "aggregation": Aggregation.ALL},
            {"chart_type": ChartType.TEAM_TREND_LINE.value,
             "title": "Aceleraciones y desaceleraciones",
             "description": f"Media por jugador con ≥ {MIN_MINUTOS} min (> 3 m/s²).",
             "column_span": 12,
             "display_config": SIN_SUPLENTES | {"bucket_size": "day", "series": "all",
                                                "point_labels": "value"},
             "keys": ["acc", "dec"], "aggregation": Aggregation.ALL},
        ]},
    ]


class Command(BaseCommand):
    help = "Crea el layout de equipo Físico › GPS partido en las categorías formativas."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", action="append", dest="categories")
        parser.add_argument("--rebuild", action="store_true")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        fisico = Department.objects.filter(club__name=opts["club"], slug="fisico").first()
        if fisico is None:
            raise CommandError("El club no tiene departamento Físico.")
        template = ExamTemplate.objects.filter(department=fisico, slug="gps_partido",
                                               is_active_version=True).first()
        if template is None:
            raise CommandError("Falta la plantilla gps_partido en Físico.")
        cats = Category.objects.filter(club__name=opts["club"],
                                       name__in=opts.get("categories") or FORMATIVO)
        if not cats.exists():
            raise CommandError("Ninguna categoría para ese filtro.")
        with transaction.atomic():
            for cat in cats.order_by("name"):
                self.stdout.write(f"  {cat.name:<14} {self._layout(fisico, cat, template, opts['rebuild'])}")
            if not opts["commit"]:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            "APLICADO" if opts["commit"] else "PLAN — nada escrito, repetir con --commit"))

    def _layout(self, fisico, cat, template, rebuild) -> str:
        from dashboards import team_scope

        equipo = team_scope.for_category(cat)
        filas = (ExamResult.objects.filter(equipo.rows) if equipo else
                 ExamResult.objects.filter(player__category=cat,
                                           template__family_id=template.family_id))
        maximos: dict = {}
        for dia, dur in filas.values_list("recorded_at__date", "result_data__tot_dur"):
            if isinstance(dur, (int, float)):
                maximos[dia] = max(maximos.get(dia, 0), dur)
        dias = len(maximos)
        if dias < MIN_DIAS:
            return f"sin GPS de partido ({dias} días) — nada que hacer"
        layout = TeamReportLayout.objects.filter(department=fisico, category=cat,
                                                 scope="period", slug=SLUG).first()
        if layout and layout.sections.exists() and not rebuild:
            return "ya estaba"
        if layout:
            layout.sections.all().delete()
            accion = "reconstruido"
        else:
            ultimo = TeamReportLayout.menu_for(fisico, cat).aggregate(m=Max("sort_order"))["m"]
            layout = TeamReportLayout.objects.create(
                department=fisico, category=cat, scope="period", name=NOMBRE, slug=SLUG,
                is_active=True, sort_order=(ultimo + 1) if ultimo is not None else 0)
            accion = "creado"
        layout.default_period_days = PERIODO_DIAS
        layout.match_selector_config = SELECTOR
        layout.save(update_fields=["default_period_days", "match_selector_config", "updated_at"])

        completo = median(maximos.values())
        min_min = max(30, int(round(completo * FRACCION_TITULAR / 5) * 5))
        n = 0
        for i, sec in enumerate(secciones(min_min)):
            section = TeamReportSection.objects.create(
                layout=layout, title=sec["title"], is_collapsible=True,
                default_collapsed=False, sort_order=i)
            for j, w in enumerate(sec["widgets"]):
                widget = TeamReportWidget.objects.create(
                    section=section, chart_type=w["chart_type"], title=w["title"],
                    description=w.get("description", ""), column_span=w["column_span"],
                    display_config=w["display_config"], sort_order=j)
                TeamReportWidgetDataSource.objects.create(
                    widget=widget, template=template, field_keys=w["keys"],
                    aggregation=w["aggregation"], sort_order=0)
                n += 1
        return (f"{accion}: {n} widgets ({dias} días con GPS de partido; partido completo "
                f"≈ {completo:.0f} min → cuenta desde {min_min} min)")
