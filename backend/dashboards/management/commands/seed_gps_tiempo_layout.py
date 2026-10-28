"""Físico › "GPS en el tiempo": the club's GPS timeline, for the team and each player.

The formativo's Power BI reads its GPS as a timeline — one bar per session,
labelled with its microcycle day and grouped under the club's microcycle
(MICRO), a second metric as a line on its own axis — with a strip of period
numbers on top and the per-player GPS table below. This builds it twice:

    Team layout "GPS en el tiempo" (slug gps-tiempo), per formativo category:
      Resumen del período    KPI cards: distance, duration, HSR, top speed,
                             AC, DEC, last opponent, current microcycle
      Carga por sesión       five bars + line charts, mean per player per session
      Registro de sesiones   one row per player and session (the club's table)

    Player profile, Físico tab, a first section "GPS en el tiempo" with the
    same charts for the player alone.

Both read `gps_sesion` and `gps_partido` together, the team one from the
category's TEAM sheet (`display_config.team`, see `dashboards.team_scope`), and
every widget but the last-opponent and microcycle cards follows the page's
"tipo de día" chips (`display_config.md_filter`).

Categories with session GPS only (SUB-20 and Series 2008–2015 today).
Idempotent; `--rebuild` replaces what an earlier run built.

    docker compose exec backend python manage.py seed_gps_tiempo_layout            # plan
    docker compose exec backend python manage.py seed_gps_tiempo_layout --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Max

from core.models import Category, Department
from dashboards.models import (
    Aggregation,
    ChartType,
    DepartmentLayout,
    LayoutSection,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
    Widget,
    WidgetDataSource,
)
from exams.models import ExamResult, ExamTemplate

NOMBRE = "GPS en el tiempo"
SLUG = "gps-tiempo"
SECCION_PERFIL = "GPS en el tiempo"
PERIODO_DIAS = 90
MIN_SESIONES = 10       # fewer GPS sessions than this is not a timeline

FORMATIVO = ["SUB-20"] + [f"Serie {y}" for y in range(2008, 2019)]

EQUIPO = {"team": True, "md_filter": True}
FILTRA = {"md_filter": True}

# (title, bars, line, description) — the pairs the club reads together.
PARES = [
    ("Distancia total y duración", "tot_dist", "tot_dur", None),
    ("Distancia total y HSR", "tot_dist", "hsr", None),
    ("Distancia total y metros por minuto", "tot_dist", "mpm", None),
    ("Aceleraciones y desaceleraciones", "acc", "dec", "Más de 3 m/s²."),
    ("Sprint: metros y cantidad", "sprint_dist", "sprints", "Más de 25 km/h."),
]

# (title, field, agg, follows the chips, sources) — "both" = sesión + partido.
TARJETAS = [
    ("Distancia total", "tot_dist", "mean", True, "both"),
    ("Duración", "tot_dur", "mean", True, "both"),
    ("HSR", "hsr", "mean", True, "both"),
    ("Velocidad máxima", "max_vel", "max", True, "both"),
    ("Aceleraciones", "acc", "mean", True, "both"),
    ("Desaceleraciones", "dec", "mean", True, "both"),
    # The last opponent is the last MATCH's, and the microcycle is "where we
    # are now": neither moves with the day-type chips.
    ("Última actividad", "opponent", "last", False, "partido"),
    ("Microciclo", "microciclo", "last", False, "both"),
]

TABLA = ["tot_dur", "tot_dist", "hsr", "mpm", "acc", "dec", "sprint_dist", "max_vel"]


def secciones_equipo() -> list[dict]:
    return [
        {"title": "Resumen del período", "widgets": [
            {"chart_type": ChartType.TEAM_KPI_CARD.value, "title": t, "column_span": 3,
             "description": "",
             "display_config": {"team": True, "field": f, "agg": agg}
             | ({"md_filter": True} if filtra else {}),
             "keys": [f], "sources": src}
            for t, f, agg, filtra, src in TARJETAS]},
        {"title": "Carga por sesión", "widgets": [
            {"chart_type": ChartType.TEAM_DUAL_AXIS_BAR_LINE.value, "title": t,
             "column_span": 12,
             "description": "Media por jugador en cada sesión" + (f" · {d}" if d else "."),
             "display_config": EQUIPO | {"bars": b, "line": l},
             "keys": [b, l], "sources": "both"}
            for t, b, l, d in PARES]},
        {"title": "Registro de sesiones", "widgets": [
            {"chart_type": ChartType.TEAM_SESSION_LOG.value, "title": "Sesión por jugador",
             "column_span": 12,
             "description": "Una fila por jugador y sesión, lo más reciente arriba.",
             "display_config": EQUIPO | {"limit": 500},
             "keys": TABLA, "sources": "both"}]},
    ]


def widgets_perfil() -> list[dict]:
    tarjetas = [
        {"chart_type": ChartType.KPI_CARD.value, "title": t, "column_span": 3,
         "display_config": {"field": f, "agg": agg} | FILTRA, "keys": [f]}
        for t, f, agg in (("Distancia total", "tot_dist", "mean"), ("HSR", "hsr", "mean"),
                          ("Velocidad máxima", "max_vel", "max"),
                          ("Aceleraciones", "acc", "mean"))]
    graficos = [
        {"chart_type": ChartType.DUAL_AXIS_BAR_LINE.value, "title": t, "column_span": 12,
         "description": d or "", "display_config": FILTRA | {"bars": b, "line": l},
         "keys": [b, l]}
        for t, b, l, d in PARES]
    tabla = [{"chart_type": ChartType.SESSION_LOG.value, "title": "Registro de sesiones",
              "column_span": 12, "display_config": dict(FILTRA), "keys": TABLA}]
    return tarjetas + graficos + tabla


class Command(BaseCommand):
    help = "Crea Físico › GPS en el tiempo (equipo y perfil) en las categorías formativas."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", action="append", dest="categories")
        parser.add_argument("--rebuild", action="store_true")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        fisico = Department.objects.filter(club__name=opts["club"], slug="fisico").first()
        if fisico is None:
            raise CommandError("El club no tiene departamento Físico.")
        plantillas = {}
        for slug in ("gps_sesion", "gps_partido"):
            plantillas[slug] = ExamTemplate.objects.filter(
                department=fisico, slug=slug, is_active_version=True).first()
            if plantillas[slug] is None:
                raise CommandError(f"Falta la plantilla {slug} en Físico.")
        cats = Category.objects.filter(club__name=opts["club"],
                                       name__in=opts.get("categories") or FORMATIVO)
        if not cats.exists():
            raise CommandError("Ninguna categoría para ese filtro.")
        with transaction.atomic():
            for cat in cats.order_by("name"):
                sesiones = ExamResult.objects.filter(
                    player__category=cat,
                    template__family_id=plantillas["gps_sesion"].family_id).count()
                if sesiones < MIN_SESIONES:
                    self.stdout.write(f"  {cat.name:<14} sin GPS de sesión ({sesiones}) — nada que hacer")
                    continue
                equipo = self._equipo(fisico, cat, plantillas, opts["rebuild"])
                perfil = self._perfil(fisico, cat, plantillas, opts["rebuild"])
                self.stdout.write(f"  {cat.name:<14} equipo: {equipo} · perfil: {perfil}")
            if not opts["commit"]:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            "APLICADO" if opts["commit"] else "PLAN — nada escrito, repetir con --commit"))

    @staticmethod
    def _fuentes(plantillas, cuales: str):
        if cuales == "partido":
            return [plantillas["gps_partido"]]
        return [plantillas["gps_sesion"], plantillas["gps_partido"]]

    def _equipo(self, fisico, cat, plantillas, rebuild) -> str:
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
        layout.save(update_fields=["default_period_days", "updated_at"])
        n = 0
        for i, sec in enumerate(secciones_equipo()):
            section = TeamReportSection.objects.create(
                layout=layout, title=sec["title"], is_collapsible=True,
                default_collapsed=False, sort_order=i)
            for j, w in enumerate(sec["widgets"]):
                widget = TeamReportWidget.objects.create(
                    section=section, chart_type=w["chart_type"], title=w["title"],
                    description=w["description"], column_span=w["column_span"],
                    display_config=w["display_config"], sort_order=j)
                for k, t in enumerate(self._fuentes(plantillas, w["sources"])):
                    TeamReportWidgetDataSource.objects.create(
                        widget=widget, template=t, field_keys=w["keys"],
                        aggregation=Aggregation.ALL, sort_order=k)
                n += 1
        return f"{accion} ({n} widgets)"

    def _perfil(self, fisico, cat, plantillas, rebuild) -> str:
        layout = DepartmentLayout.objects.filter(department=fisico, category=cat).first()
        if layout is None:
            layout = DepartmentLayout.objects.create(
                department=fisico, category=cat, name="Físico", is_active=True)
        existente = layout.sections.filter(title=SECCION_PERFIL).first()
        if existente and not rebuild:
            return "ya estaba"
        if existente:
            existente.delete()
            accion = "reconstruida"
        else:
            # First in the tab: it's the view the staff opens the profile for.
            layout.sections.update(sort_order=F("sort_order") + 1)
            accion = "creada"
        section = LayoutSection.objects.create(
            layout=layout, title=SECCION_PERFIL, is_collapsible=True,
            default_collapsed=False, sort_order=0)
        ws = widgets_perfil()
        for j, w in enumerate(ws):
            widget = Widget.objects.create(
                section=section, chart_type=w["chart_type"], title=w["title"],
                description=w.get("description", ""), column_span=w["column_span"],
                display_config=w["display_config"], sort_order=j)
            for k, t in enumerate(self._fuentes(plantillas, "both")):
                WidgetDataSource.objects.create(
                    widget=widget, template=t, field_keys=w["keys"],
                    aggregation=Aggregation.ALL, sort_order=k)
        return f"sección {accion} ({len(ws)} widgets)"
