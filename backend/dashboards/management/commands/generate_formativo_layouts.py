"""Build a player dashboard per (serie, departamento) from the data that exists.

The Formativo had **zero** layouts — 5 player and 6 team layouts existed, all on
Primer Equipo — so the 19.247 physical results and 15.352 GPS rows we imported
were invisible outside the raw exam record. `DepartmentLayout` has a non-null FK
to `Category` and no inheritance, so a Serie 2011 player saw nothing because no
row existed for his category, not for want of data or permissions.

    docker compose exec backend python manage.py generate_formativo_layouts \\
        --club "Universidad de Chile"
    # ... read the report, then add --commit

Derived from the data, not from a list
--------------------------------------
Which widgets a category gets is decided by **which fields actually carry
values** for its players, not by the template schema and not by copying Primer
Equipo. Two reasons:

* The exams genuinely differ. Series 2016–2018 only run `carreras` and
  `neuromuscular`; Resistencia and Fuerza start at Sub 13. Generating the full
  set everywhere would give the youngest categories mostly empty charts.
* A hand-written widget list is a second copy of the template schema, free to
  drift from it. Reading the results keeps the dashboard a consequence of what
  the club measures.

So a field that exists in the schema but was never filled for that category
produces no widget, and a category with no data in a department gets no layout
at all rather than an empty one.

Chart choice
------------
`line_with_selector` for the trend, because it is one of the **five** chart
types that actually serialise reference bands to the frontend
(`comparison_table`, `line_with_selector` and `grouped_bar` for players;
`team_roster_matrix` and `team_distribution` for teams). `multi_line` computes
the field meta and never emits it, so a trend drawn with it would silently lose
the per-category thresholds we just seeded — which is most of the point.

`comparison_table` on top for the last takes, since that is what a physio reads
first: the current numbers with their band.

Rebuild, not append
-------------------
Re-running wipes each layout's sections and rebuilds them, the same policy as
`seed_demo_layouts`. That keeps the command idempotent as new data arrives (a
category that starts running Fuerza gains the section on the next run), at the
cost of discarding manual edits to a generated layout — so `--skip-existing`
is there for once the club starts tailoring them.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field as dc_field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from dashboards.models import (Aggregation, ChartType, DepartmentLayout,
                               LayoutSection, TeamReportLayout,
                               TeamReportSection, TeamReportWidget,
                               TeamReportWidgetDataSource, Widget,
                               WidgetDataSource)
from exams.models import ExamResult, ExamTemplate

# Departments to build for. Ordered as the club reads them.
DEPARTAMENTOS = ("fisico", "tactico", "nutricional", "medico")

# A field needs at least this many readings in the category before it earns a
# widget. One stray value does not make a trend, and a chart with a single
# point is noise on the page.
MIN_LECTURAS = 3

# Fields that carry provenance or labels rather than measurements.
NO_GRAFICABLES = frozenset({
    "origen", "origen_hoja", "origen_id", "origen_codigo",
    "fecha", "sesion", "tipo_sesion", "ejercicio", "observaciones",
})


@dataclass
class Reporte:
    layouts: int = 0
    layouts_equipo: int = 0
    widgets_equipo: int = 0
    reconstruidos: int = 0
    saltados: int = 0
    widgets: int = 0
    sin_datos: list[str] = dc_field(default_factory=list)
    huerfanos: list[str] = dc_field(default_factory=list)
    vinculados: list[str] = dc_field(default_factory=list)
    detalle: list[str] = dc_field(default_factory=list)


def campos_con_datos(category: Category, template: ExamTemplate) -> dict[str, int]:
    """field_key → how many readings it has for this category's players.

    Counts in Python rather than with a JSONB aggregate: the volume is a few
    thousand rows per (category, template) and the alternative is one query per
    field, which is worse.
    """
    cuenta: dict[str, int] = defaultdict(int)
    qs = (ExamResult.objects
          .filter(player__category=category, template__family_id=template.family_id)
          .only("result_data")
          .values_list("result_data", flat=True))
    for data in qs.iterator(chunk_size=2000):
        for key, valor in (data or {}).items():
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                cuenta[key] += 1
    return dict(cuenta)


def _plantillas_de_historial(category, department, aplicables) -> list:
    """Plantillas del departamento que la categoría NO corre pero de las que
    sus jugadores tienen resultados.

    Es el caso del ascendido, y en el plantel real no es marginal: 11 de los 35
    de Primer Equipo vienen del formativo y para ellos el historial juvenil es
    la mayor parte de lo que SLAB sabe — uno tenía 689 lecturas y ni un
    gráfico.
    """
    familias = {t.family_id for t in aplicables}
    ids = (ExamResult.objects
           .filter(player__category=category, template__department=department)
           .exclude(template__family_id__in=familias)
           .values_list("template__family_id", flat=True).distinct())
    return list(ExamTemplate.objects.filter(
        family_id__in=list(ids), is_active_version=True).distinct())


def secciones_para(category: Category, templates: list[ExamTemplate],
                   *, historial: bool = False) -> list[dict]:
    """One section per template that has data, its widgets from its own groups.

    `historial=True` marks the sections built from a template the category does
    NOT run: they exist for the player who changed category. `campos_con_datos`
    already counts by the category's PLAYERS rather than by applicability, so
    the only thing that changes is how the section presents itself.
    """
    secciones = []
    for template in templates:
        cuenta = campos_con_datos(category, template)
        if not cuenta:
            continue
        # Walk the schema, not the counts, so widgets keep the order the club
        # sees on the form instead of whatever the JSON happened to yield.
        por_grupo: dict[str, list[str]] = defaultdict(list)
        graficables: dict[str, list[str]] = defaultdict(list)
        for f in (template.config_schema or {}).get("fields") or []:
            key = f.get("key")
            if not key or key in NO_GRAFICABLES:
                continue
            if cuenta.get(key, 0) < MIN_LECTURAS:
                continue
            grupo = f.get("group") or template.name
            por_grupo[grupo].append(key)
            if f.get("chart_type"):
                graficables[grupo].append(key)
        if not por_grupo:
            continue

        widgets: list[dict] = []
        # La tabla lleva los campos que se LEEN, no los intentos crudos: los
        # tres `t10_intento_N` no tienen banda ni se miran de a uno, y metidos
        # en la tabla la vuelven 19 filas donde importan 4.
        leibles = [k for keys in graficables.values() for k in keys] or \
                  [k for keys in por_grupo.values() for k in keys]
        widgets.append({
            "chart_type": ChartType.COMPARISON_TABLE.value,
            "title": "Últimas tomas",
            "description": f"{template.name} — valores recientes con su banda.",
            "column_span": 12,
            "sources": [{"template": template, "field_keys": leibles,
                         "aggregation": Aggregation.LAST_N, "aggregation_param": 5}],
        })
        for grupo, keys in por_grupo.items():
            lineas = graficables.get(grupo) or keys
            widgets.append({
                "chart_type": ChartType.LINE_WITH_SELECTOR.value,
                "title": grupo,
                "column_span": 6 if len(por_grupo) > 1 else 12,
                "sources": [{"template": template, "field_keys": lineas,
                             "aggregation": Aggregation.ALL}],
            })
        secciones.append({
            "title": f"{template.name} · historial" if historial else template.name,
            "widgets": widgets,
            "historial": historial,
        })
    return secciones


def construir(department: Department, category: Category, secciones: list[dict],
              *, skip_existing: bool) -> tuple[str, int]:
    """Wipe + rebuild, the same policy as `seed_demo_layouts`."""
    existente = DepartmentLayout.objects.filter(
        department=department, category=category).first()
    if existente and skip_existing:
        return "saltado", 0
    if existente:
        existente.sections.all().delete()
        layout, accion = existente, "reconstruido"
    else:
        layout = DepartmentLayout.objects.create(
            department=department, category=category,
            name=department.name, is_active=True)
        accion = "creado"

    n = 0
    for i, sec in enumerate(secciones):
        section = LayoutSection.objects.create(
            layout=layout, title=sec["title"], is_collapsible=True,
            # Las de historial arrancan cerradas: en Primer Equipo son 11 de 35
            # los que traen historial del formativo, así que para los otros 24
            # serían paneles vacíos ocupando la pantalla.
            default_collapsed=bool(sec.get("historial")), sort_order=i)
        for j, w in enumerate(sec["widgets"]):
            widget = Widget.objects.create(
                section=section, chart_type=w["chart_type"], title=w["title"],
                description=w.get("description", ""),
                column_span=w.get("column_span", 12), sort_order=j)
            for k, src in enumerate(w.get("sources", [])):
                WidgetDataSource.objects.create(
                    widget=widget, template=src["template"],
                    field_keys=src["field_keys"],
                    aggregation=src.get("aggregation", Aggregation.LAST_N),
                    aggregation_param=src.get("aggregation_param", 3),
                    sort_order=k)
            n += 1
    return accion, n


def secciones_equipo(category: Category, templates: list[ExamTemplate]) -> list[dict]:
    """Team view of the same data: who is where, and how the squad spreads.

    Deliberately different widgets from the player layout. A coach reading a
    category asks "who is behind?" and "how does the squad distribute?", not
    "how did this one player evolve" — that is the player dashboard's job.

    `team_roster_matrix` and `team_distribution` are also the two team chart
    types that serialise reference bands, so the matrix colours each cell with
    the category's own thresholds instead of the shared scale.
    """
    secciones = []
    for template in templates:
        cuenta = campos_con_datos(category, template)
        if not cuenta:
            continue
        leibles = []
        for f in (template.config_schema or {}).get("fields") or []:
            key = f.get("key")
            if (not key or key in NO_GRAFICABLES
                    or cuenta.get(key, 0) < MIN_LECTURAS
                    or not f.get("chart_type")):
                continue
            leibles.append(key)
        if not leibles:
            continue

        widgets = [{
            "chart_type": ChartType.TEAM_ROSTER_MATRIX.value,
            "title": "Plantel — último valor por jugador",
            "description": f"{template.name}. Cada celda con la banda de la categoría.",
            "column_span": 12,
            "sources": [{"template": template, "field_keys": leibles,
                         "aggregation": Aggregation.LATEST}],
        }, {
            "chart_type": ChartType.TEAM_TREND_LINE.value,
            "title": "Promedio del plantel en el tiempo",
            "column_span": 12,
            "sources": [{"template": template, "field_keys": leibles,
                         "aggregation": Aggregation.ALL}],
        }]
        # A histogram needs one metric, so it goes on the first charted field:
        # more than one would be several widgets saying the same thing.
        widgets.append({
            "chart_type": ChartType.TEAM_DISTRIBUTION.value,
            "title": f"Distribución del plantel",
            "column_span": 6,
            "display_config": {"field_key": leibles[0]},
            "sources": [{"template": template, "field_keys": [leibles[0]],
                         "aggregation": Aggregation.LATEST}],
        })
        secciones.append({"title": template.name, "widgets": widgets})
    return secciones


def construir_equipo(department: Department, category: Category,
                     secciones: list[dict], *, skip_existing: bool) -> tuple[str, int]:
    existente = TeamReportLayout.objects.filter(
        department=department, category=category, scope="period").first()
    if existente and skip_existing:
        return "saltado", 0
    if existente:
        existente.sections.all().delete()
        layout, accion = existente, "reconstruido"
    else:
        layout = TeamReportLayout.objects.create(
            department=department, category=category, name=department.name,
            # `period` y no `match`: el formativo no tiene GPS de partido
            # ligado a evento en todas las categorías, y un layout de partido
            # sin evento no tiene de dónde colgarse.
            scope="period", is_active=True)
        accion = "creado"

    n = 0
    for i, sec in enumerate(secciones):
        section = TeamReportSection.objects.create(
            layout=layout, title=sec["title"], is_collapsible=True,
            default_collapsed=False, sort_order=i)
        for j, w in enumerate(sec["widgets"]):
            widget = TeamReportWidget.objects.create(
                section=section, chart_type=w["chart_type"], title=w["title"],
                description=w.get("description", ""),
                column_span=w.get("column_span", 12),
                display_config=w.get("display_config", {}), sort_order=j)
            for k, src in enumerate(w.get("sources", [])):
                TeamReportWidgetDataSource.objects.create(
                    widget=widget, template=src["template"],
                    field_keys=src["field_keys"],
                    aggregation=src.get("aggregation", Aggregation.LATEST),
                    aggregation_param=src.get("aggregation_param", 3),
                    sort_order=k)
            n += 1
    return accion, n


class Command(BaseCommand):
    help = "Genera un dashboard de jugador por serie y departamento, según sus datos."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--skip-existing", action="store_true",
                            help="No reconstruye los layouts que ya existen.")
        parser.add_argument("--category", action="append", dest="categories",
                            help="Limitar a una categoría (repetible).")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")

        categorias = Category.objects.filter(
            club=club, is_senior=False).exclude(name__icontains="Femenino")
        if opts.get("categories"):
            categorias = categorias.filter(name__in=opts["categories"])
        if not categorias.exists():
            raise CommandError("Ninguna categoría formativa para ese filtro.")

        rep = Reporte()
        with transaction.atomic():
            self._correr(club, categorias, opts, rep)
            if not opts["commit"]:
                transaction.set_rollback(True)
        self._imprimir(rep, opts)

    def _correr(self, club, categorias, opts, rep):
        deps = {d.slug: d for d in Department.objects.filter(club=club)}
        for category in categorias.order_by("-cohort_year", "name"):
            for slug in DEPARTAMENTOS:
                department = deps.get(slug)
                if department is None:
                    continue
                templates = list(
                    ExamTemplate.objects.filter(
                        department=department, applicable_categories=category,
                        is_active_version=True).distinct())
                secciones = secciones_para(category, templates)
                # Y las del jugador que cambió de categoría: plantillas que
                # esta categoría NO corre pero de las que sus jugadores traen
                # historial. `chart_spec` ya las resuelve por club, así que el
                # widget funciona; lo que faltaba era que alguien lo creara.
                secciones += secciones_para(
                    category, _plantillas_de_historial(category, department,
                                                       templates),
                    historial=True)
                if not secciones:
                    # "Sin datos" y "hay datos pero la plantilla no aplica a
                    # esta categoría" son cosas distintas, y la segunda es un
                    # hueco de configuración que no se puede reportar como
                    # ausencia: `pentacompartimental` aplica sólo a Primer
                    # Equipo y tiene 1165 resultados de jugadores del
                    # formativo, invisibles por eso.
                    aplicables = {t.family_id for t in templates}
                    sueltos = (ExamResult.objects
                               .filter(player__category=category,
                                       template__department=department)
                               .exclude(template__family_id__in=aplicables)
                               .count())
                    if sueltos:
                        rep.huerfanos.append(
                            f"{category.name} · {slug}: {sueltos} resultados en "
                            f"plantillas que NO aplican a esta categoría")
                    else:
                        rep.sin_datos.append(f"{category.name} · {slug}")
                    continue
                accion, n = construir(department, category, secciones,
                                      skip_existing=opts["skip_existing"])
                if accion == "saltado":
                    rep.saltados += 1
                    continue
                rep.layouts += accion == "creado"
                rep.reconstruidos += accion == "reconstruido"
                rep.widgets += n
                # La ficha del jugador arma sus pestañas con
                # `Category.departments` (perfil/[id]/page.tsx:130), no con los
                # layouts. Sin el vínculo, el layout existe y es inalcanzable:
                # ninguna categoría formativa lo tenía poblado, así que los 20
                # dashboards no aparecían en ninguna ficha. Se vincula acá, que
                # es donde ya se sabe que hay algo que mostrar — y sólo se
                # AGREGA, para no sacar un departamento que el club puso a mano.
                if not category.departments.filter(pk=department.pk).exists():
                    category.departments.add(department)
                    rep.vinculados.append(f"{category.name} · {slug}")

                sec_eq = secciones_equipo(category, templates)
                n_eq = 0
                if sec_eq:
                    accion_eq, n_eq = construir_equipo(
                        department, category, sec_eq,
                        skip_existing=opts["skip_existing"])
                    rep.layouts_equipo += accion_eq == "creado"
                    rep.widgets_equipo += n_eq
                rep.detalle.append(
                    f"{category.name:<14} {slug:<12} jugador: {len(secciones)} secc/"
                    f"{n} wid · equipo: {len(sec_eq)} secc/{n_eq} wid")

    def _imprimir(self, rep, opts):
        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{modo}\n"))
        self.stdout.write(self.style.SUCCESS(f"  layouts creados     : {rep.layouts}"))
        if rep.reconstruidos:
            self.stdout.write(f"  reconstruidos       : {rep.reconstruidos}")
        if rep.saltados:
            self.stdout.write(f"  saltados (ya había) : {rep.saltados}")
        self.stdout.write(f"  widgets de jugador  : {rep.widgets}")
        self.stdout.write(self.style.SUCCESS(
            f"  layouts de equipo   : {rep.layouts_equipo}"))
        self.stdout.write(f"  widgets de equipo   : {rep.widgets_equipo}")
        if rep.detalle:
            self.stdout.write("")
            for linea in rep.detalle:
                self.stdout.write(f"    {linea}")
        if rep.vinculados:
            self.stdout.write(self.style.SUCCESS(
                f"\n  Departamentos vinculados a la categoría "
                f"(para que aparezca la pestaña): {len(rep.vinculados)}"))
            for item in rep.vinculados[:14]:
                self.stdout.write(f"    {item}")
            if len(rep.vinculados) > 14:
                self.stdout.write(f"    … y {len(rep.vinculados) - 14} más")
        if rep.huerfanos:
            self.stdout.write(self.style.ERROR(
                f"\n  ⚠️ Datos que no se pueden graficar — la plantilla no aplica "
                f"a esa categoría: {len(rep.huerfanos)}"))
            for item in rep.huerfanos:
                self.stdout.write(f"    {item}")
            self.stdout.write(
                "    → o se amplía applicable_categories, o esos resultados "
                "quedan fuera de todo dashboard.")
        if rep.sin_datos:
            self.stdout.write(self.style.WARNING(
                f"\n  Sin datos, no se creó layout: {len(rep.sin_datos)}"))
            for item in rep.sin_datos[:10]:
                self.stdout.write(f"    {item}")
            if len(rep.sin_datos) > 10:
                self.stdout.write(f"    … y {len(rep.sin_datos) - 10} más")
