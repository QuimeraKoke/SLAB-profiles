"""Agregar al layout las secciones de historial del jugador que cambió de categoría.

    # ensayo
    docker compose exec backend python manage.py add_history_sections \\
        --club "Universidad de Chile" --category "Primer Equipo"

    # aplicar
    docker compose exec backend python manage.py add_history_sections \\
        --club "Universidad de Chile" --category "Primer Equipo" --commit

Por qué es un comando aparte de `generate_formativo_layouts`
------------------------------------------------------------
Ese **reconstruye** el layout, que es lo correcto para las categorías del
formativo porque son suyos y los genera él. Los de Primer Equipo están hechos a
mano desde mayo — "Alertas activas", "Mapa de lesiones", "Medicación reciente" —
y reconstruirlos los borraría. Este sólo **agrega al final** y no toca nada de lo
que ya está.

Qué agrega
----------
Una sección por plantilla que la categoría NO corre pero de la que sus jugadores
traen resultados. En Primer Equipo son 11 de 35 los que vienen del formativo, y
para ellos ese historial es la mayor parte de lo que SLAB sabe: uno tenía 689
lecturas y ni un gráfico.

Las secciones nacen **colapsadas**: para los otros 24 serían paneles vacíos
ocupando la pantalla. Y el título lleva "· historial" para que nadie las lea
como algo que este plantel mide hoy.

Depende del fallback de lectura de `dashboards/chart_spec.py`, que resuelve la
plantilla dentro del club cuando la categoría no la aplica. Sin eso el widget
existiría y fallaría al pedir datos.

Idempotente: si la sección ya está, la saltea.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from core.models import Category, Club, Department
from dashboards.management.commands.generate_formativo_layouts import (
    _plantillas_de_historial, secciones_para)
from dashboards.models import (Aggregation, DepartmentLayout, LayoutSection,
                               Widget, WidgetDataSource)
from exams.models import ExamTemplate


class Command(BaseCommand):
    help = ("Agrega secciones de historial (plantillas de otra categoría con "
            "datos de estos jugadores) sin tocar el layout existente.")

    def add_arguments(self, parser):
        parser.add_argument("--club", required=True)
        parser.add_argument("--category", action="append", dest="categories",
                            required=True, help="Nombre exacto (repetible).")
        parser.add_argument("--department", action="append", dest="departments",
                            help="Slug de departamento (repetible). Por "
                                 "defecto, todos los que la categoría tenga.")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        cats = list(Category.objects.filter(club=club,
                                            name__in=opts["categories"]))
        if not cats:
            raise CommandError(f"Ninguna categoría coincide con "
                               f"{opts['categories']}.")
        if not opts["commit"]:
            self.stdout.write(self.style.WARNING("ENSAYO — no escribe nada.\n"))

        creadas = saltadas = widgets_n = 0
        with transaction.atomic():
            for category in cats:
                deps = category.departments.all()
                if opts["departments"]:
                    deps = deps.filter(slug__in=opts["departments"])
                for department in deps.order_by("name"):
                    layout = DepartmentLayout.objects.filter(
                        department=department, category=category,
                        is_active=True).first()
                    if layout is None:
                        self.stdout.write(self.style.WARNING(
                            f"  {category.name} · {department.name}: sin layout "
                            f"activo — omitido"))
                        continue
                    aplicables = list(ExamTemplate.objects.filter(
                        department=department, applicable_categories=category,
                        is_active_version=True).distinct())
                    historial = _plantillas_de_historial(category, department,
                                                         aplicables)
                    if not historial:
                        continue
                    secciones = secciones_para(category, historial,
                                               historial=True)
                    if not secciones:
                        continue
                    existentes = set(
                        layout.sections.values_list("title", flat=True))
                    orden = (layout.sections.aggregate(
                        m=Max("sort_order"))["m"] or 0) + 1
                    for sec in secciones:
                        if sec["title"] in existentes:
                            saltadas += 1
                            continue
                        section = LayoutSection.objects.create(
                            layout=layout, title=sec["title"],
                            is_collapsible=True, default_collapsed=True,
                            sort_order=orden)
                        orden += 1
                        creadas += 1
                        for j, w in enumerate(sec["widgets"]):
                            widget = Widget.objects.create(
                                section=section, chart_type=w["chart_type"],
                                title=w["title"],
                                description=w.get("description", ""),
                                column_span=w.get("column_span", 12),
                                sort_order=j)
                            widgets_n += 1
                            for src in w.get("sources", []):
                                WidgetDataSource.objects.create(
                                    widget=widget, template=src["template"],
                                    field_keys=src["field_keys"],
                                    aggregation=src.get("aggregation",
                                                        Aggregation.LAST_N))
                        self.stdout.write(self.style.SUCCESS(
                            f"  {category.name} · {department.name}: "
                            f"+ «{sec['title']}» ({len(sec['widgets'])} widgets)"))
            if not opts["commit"]:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"  {creadas} sección(es) · {widgets_n} widgets · "
            f"{saltadas} ya existían"))
        if not opts["commit"]:
            self.stdout.write(self.style.WARNING(
                "\n  ENSAYO — volvé a correr con --commit."))
