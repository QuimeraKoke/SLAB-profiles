"""Físico › "Evaluaciones": the club's physical-evaluation sheet as a team layout.

It replicates the Power BI evaluation pages of the formativo — one evolution
chart per test (squad mean per evaluation day, value + % change on each
point), the sprint speed gauges, and one table with every player's latest
result in every test, bordered by the category's bands:

    Última evaluación del plantel   one matrix, all tests
    Fuerza — Sentadilla             1RM / Fuerza relativa / Velocidad última carga
    Velocidad                       T10 / T30 (s)  +  gauge T10 / T30 km/h
    Cambio de dirección (505)       izquierda + derecha together, asimetría
    Neuromuscular                   CMJ / Tiro
    Resistencia — Yo-Yo IR1         Palier / Metros / VAM / VO2max

A category only gets the blocks it has results for — per charted field, not
per template (Series 2014 and younger run no Yo-Yo or strength test, and
2016–2018 run carreras without the COD). The layout opens on the last year
(`default_period_days`): evaluations are a few days per season, and 30 days
would show nothing.

A second Físico layout, after the existing one, so the menu becomes
Dashboard → Físico → General / Evaluaciones. Idempotent: a category that
already has it is left alone, unless `--rebuild`, which replaces its
sections (losing edits made to them in the page).

    docker compose exec backend python manage.py seed_evaluaciones_layout            # plan
    docker compose exec backend python manage.py seed_evaluaciones_layout --commit
    docker compose exec backend python manage.py seed_evaluaciones_layout --category "Serie 2010" --rebuild --commit
"""
from __future__ import annotations

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

NOMBRE = "Evaluaciones"
SLUG = "evaluaciones"
PERIODO_DIAS = 365
# Below this many results a test is noise for the category, not a block.
MIN_RESULTADOS = 5

FORMATIVO = ["SUB-20"] + [f"Serie {y}" for y in range(2008, 2019)]

TENDENCIA = {"bucket_size": "week", "week_label": "date",
             "point_labels": "value_pct", "style": "area"}

# Columns of "Última evaluación", per template, in reading order.
MATRIZ = [
    ("carreras", ["t10_best", "t30_best", "cod_izq_best", "cod_der_best"]),
    ("neuromuscular", ["cmj_best", "tiro_best"]),
    ("resistencia", ["palier", "vo2_max"]),
    ("fuerza", ["rm_estimado", "fr"]),
]


def _trend(title, slug, keys, span=12, **display):
    return {"chart_type": ChartType.TEAM_TREND_LINE.value, "title": title, "column_span": span,
            "display_config": TENDENCIA | display,
            "sources": [(slug, keys, Aggregation.ALL)]}


BLOQUES = [
    {"title": "Fuerza — Sentadilla", "requires": ("fuerza", "rm_estimado"), "widgets": [
        _trend("Evolución del plantel", "fuerza", ["rm_estimado", "fr", "ultima_carga_ms"]),
    ]},
    {"title": "Velocidad", "requires": ("carreras", "t10_best"), "widgets": [
        _trend("Evolución del plantel", "carreras", ["t10_best", "t30_best"], span=8),
        {"chart_type": ChartType.TEAM_GAUGE.value, "title": "Velocidad media", "column_span": 4,
         "description": "Última evaluación de cada jugador, entre el más lento y el más rápido del plantel.",
         "display_config": {"bands_from": {"t10_kmh": {"field": "t10_best", "k": 36},
                                           "t30_kmh": {"field": "t30_best", "k": 108}}},
         "sources": [("carreras", ["t10_kmh", "t30_kmh"], Aggregation.LATEST)]},
    ]},
    {"title": "Cambio de dirección (505)", "requires": ("carreras", "cod_izq_best"), "widgets": [
        _trend("Izquierda y derecha", "carreras", ["cod_izq_best", "cod_der_best"], span=8,
               series="all", point_labels="value", style="line"),
        _trend("Asimetría", "carreras", ["cod_asimetria"], span=4, point_labels="value"),
    ]},
    {"title": "Neuromuscular", "requires": ("neuromuscular", "cmj_best"), "widgets": [
        _trend("Evolución del plantel", "neuromuscular", ["cmj_best", "tiro_best"]),
    ]},
    {"title": "Resistencia — Yo-Yo IR1", "requires": ("resistencia", "palier"), "widgets": [
        _trend("Evolución del plantel", "resistencia", ["palier", "metros", "vam", "vo2_max"]),
    ]},
]


class Command(BaseCommand):
    help = "Crea el layout de equipo Físico › Evaluaciones en las categorías formativas."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", action="append", dest="categories",
                            help="Limitar a una categoría (repetible). Por defecto: SUB-20 y "
                                 "Series 2008–2018.")
        parser.add_argument("--rebuild", action="store_true",
                            help="Reemplaza las secciones de un «Evaluaciones» que ya existe.")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        fisico = Department.objects.filter(club__name=opts["club"], slug="fisico").first()
        if fisico is None:
            raise CommandError("El club no tiene departamento Físico.")
        templates = {t.slug: t for t in ExamTemplate.objects.filter(
            department=fisico, is_active_version=True,
            slug__in=[s for s, _ in MATRIZ])}
        faltan = {s for s, _ in MATRIZ} - templates.keys()
        if faltan:
            raise CommandError(f"Faltan plantillas en Físico: {', '.join(sorted(faltan))}.")

        cats = Category.objects.filter(club__name=opts["club"],
                                       name__in=opts.get("categories") or FORMATIVO)
        if not cats.exists():
            raise CommandError("Ninguna categoría para ese filtro.")

        with transaction.atomic():
            for cat in cats.order_by("name"):
                self.stdout.write(f"  {cat.name:<14} {self._layout(fisico, cat, templates, opts['rebuild'])}")
            if not opts["commit"]:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            "APLICADO" if opts["commit"] else "PLAN — nada escrito, repetir con --commit"))

    def _layout(self, fisico, cat, templates, rebuild) -> str:
        def hay(slug, key=None):
            qs = ExamResult.objects.filter(player__category=cat,
                                           template__family_id=templates[slug].family_id)
            if key:
                # A calculated field is stored as null when its inputs are
                # missing: has_key alone would count those.
                qs = qs.filter(result_data__has_key=key).exclude(**{f"result_data__{key}": None})
            return qs.count() >= MIN_RESULTADOS

        # A block needs the field it charts, not just the template: Series
        # 2016–2018 run carreras without the COD test.
        con_datos = {slug for slug in templates if hay(slug)}
        bloques = [b for b in BLOQUES if hay(*b["requires"])]
        if not con_datos:
            return "sin evaluaciones — nada que hacer"

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
        if layout.default_period_days != PERIODO_DIAS:
            layout.default_period_days = PERIODO_DIAS
            layout.save(update_fields=["default_period_days", "updated_at"])

        secciones = [{"title": "Última evaluación del plantel", "widgets": [{
            "chart_type": ChartType.TEAM_ROSTER_MATRIX.value,
            "title": "Último resultado por jugador",
            "description": "Cada celda con la banda de la categoría.",
            "column_span": 12, "display_config": {"source_suffix": False},
            "sources": [(s, cols, Aggregation.LATEST) for s, keys in MATRIZ
                        if s in con_datos and (cols := [k for k in keys if hay(s, k)])],
        }]}] + bloques

        n = 0
        for i, sec in enumerate(secciones):
            section = TeamReportSection.objects.create(
                layout=layout, title=sec["title"], is_collapsible=True,
                default_collapsed=False, sort_order=i)
            for j, w in enumerate(sec["widgets"]):
                widget = TeamReportWidget.objects.create(
                    section=section, chart_type=w["chart_type"], title=w["title"],
                    description=w.get("description", ""), column_span=w["column_span"],
                    display_config=w.get("display_config", {}), sort_order=j)
                for k, (slug, keys, agg) in enumerate(w["sources"]):
                    TeamReportWidgetDataSource.objects.create(
                        widget=widget, template=templates[slug], field_keys=keys,
                        aggregation=agg, sort_order=k)
                n += 1
        nombres = ", ".join(s["title"].split(" — ")[0] for s in secciones[1:])
        return f"{accion}: {n} widgets ({nombres})"
