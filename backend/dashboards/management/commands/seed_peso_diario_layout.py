"""Add a "Peso diario" section to a category's Nutricional layouts.

Primer Equipo's Nutricional layouts are hand-built (monthly body composition
from `pentacompartimental`). The daily weigh-in (`import_peso_diario` →
`peso_talla`) has nowhere to show until a section reads it, so this ADDS one
— to the player layout and to the team layout — and touches nothing else.
Unlike `generate_formativo_layouts`, it never rebuilds: an existing section
with the same title means "already done" and the command skips it.

    docker compose exec backend python manage.py seed_peso_diario_layout            # plan
    docker compose exec backend python manage.py seed_peso_diario_layout --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from core.models import Category, Department
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
from exams.models import ExamTemplate

TITULO = "Peso diario"

JUGADOR = [
    {"chart_type": "line_with_selector", "title": "Peso diario", "column_span": 12,
     "description": "Pesaje de la mañana. Elegí peso, diferencia con el ideal o IMC.",
     "fields": ["peso", "dif_ideal", "imc"], "aggregation": Aggregation.ALL},
    {"chart_type": "comparison_table", "title": "Últimos pesajes", "column_span": 12,
     "fields": ["peso", "peso_ideal", "dif_ideal"], "aggregation": Aggregation.LAST_N,
     "param": 5},
]
EQUIPO = [
    {"chart_type": "team_roster_matrix", "title": "Peso del día vs. peso ideal", "column_span": 12,
     "description": "Último pesaje de cada jugador, su ideal y la diferencia.",
     "fields": ["peso", "peso_ideal", "dif_ideal"], "aggregation": Aggregation.LATEST},
    {"chart_type": "team_trend_line", "title": "Diferencia promedio con el peso ideal",
     "column_span": 12, "fields": ["dif_ideal"], "aggregation": Aggregation.ALL},
    {"chart_type": "team_distribution", "title": "Distribución de la diferencia con el ideal",
     "column_span": 6, "fields": ["dif_ideal"], "aggregation": Aggregation.LATEST,
     "display_config": {"field_key": "dif_ideal"}},
]


class Command(BaseCommand):
    help = "Agrega la sección 'Peso diario' a los layouts Nutricional de una categoría."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", default="Primer Equipo")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        cat = Category.objects.filter(club__name=opts["club"], name=opts["category"]).first()
        dept = Department.objects.filter(club__name=opts["club"], slug="nutricional").first()
        tpl = ExamTemplate.objects.filter(slug="peso_talla", department=dept,
                                          is_active_version=True).first()
        if not (cat and dept and tpl):
            raise CommandError("Falta la categoría, el departamento Nutricional o 'peso_talla'.")

        with transaction.atomic():
            j = self._jugador(cat, dept, tpl)
            e = self._equipo(cat, dept, tpl)
            if not opts["commit"]:
                transaction.set_rollback(True)
        modo = "APLICADO" if opts["commit"] else "PLAN (sin --commit no escribe)"
        self.stdout.write(self.style.SUCCESS(f"{modo} · jugador: {j} · equipo: {e}"))

    def _jugador(self, cat, dept, tpl) -> str:
        layout = DepartmentLayout.objects.filter(category=cat, department=dept).first()
        if layout is None:
            return "sin layout"
        if layout.sections.filter(title=TITULO).exists():
            return "ya estaba"
        # Right after the first section (the composition summary), pushing the
        # rest down: the daily weight is what the staff look at most.
        layout.sections.filter(sort_order__gte=1).update(sort_order=F("sort_order") + 1)
        sec = LayoutSection.objects.create(layout=layout, title=TITULO, is_collapsible=True,
                                           default_collapsed=False, sort_order=1)
        for i, w in enumerate(JUGADOR):
            wid = Widget.objects.create(section=sec, chart_type=w["chart_type"], title=w["title"],
                                        description=w.get("description", ""),
                                        column_span=w["column_span"], sort_order=i)
            WidgetDataSource.objects.create(widget=wid, template=tpl, field_keys=w["fields"],
                                            aggregation=w["aggregation"],
                                            aggregation_param=w.get("param", 3), sort_order=0)
        return f"sección agregada ({len(JUGADOR)} widgets)"

    def _equipo(self, cat, dept, tpl) -> str:
        layout = TeamReportLayout.objects.filter(category=cat, department=dept).first()
        if layout is None:
            return "sin layout"
        if layout.sections.filter(title=TITULO).exists():
            return "ya estaba"
        layout.sections.update(sort_order=F("sort_order") + 1)
        sec = TeamReportSection.objects.create(layout=layout, title=TITULO, is_collapsible=True,
                                               default_collapsed=False, sort_order=0)
        for i, w in enumerate(EQUIPO):
            wid = TeamReportWidget.objects.create(
                section=sec, chart_type=w["chart_type"], title=w["title"],
                description=w.get("description", ""), column_span=w["column_span"],
                display_config=w.get("display_config", {}), sort_order=i)
            TeamReportWidgetDataSource.objects.create(
                widget=wid, template=tpl, field_keys=w["fields"], aggregation=w["aggregation"],
                aggregation_param=w.get("param", 3), sort_order=0)
        return f"sección agregada ({len(EQUIPO)} widgets)"
