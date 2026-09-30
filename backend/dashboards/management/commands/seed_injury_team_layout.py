"""Add the "Lesiones" section to the Médico TEAM layout of each category.

It reproduces the club's injury sheet — "Lesionados actuales", "Lesionados en
el año", days lost per player, and the breakdowns by region, type, muscle,
position, cause, context and recurrence — with the three injury widgets of
`dashboards/team_injuries.py`.

Add-only: a category's Médico team layout is created if it has none, and the
section is skipped when one with the same title already exists. Nothing else
in an existing layout is touched (Primer Equipo's is hand-built).

"Lesionados en el período" follows the report page's date selector — pick
"este año" there to get the sheet's "Lesionados en el año".

    docker compose exec backend python manage.py seed_injury_team_layout            # plan
    docker compose exec backend python manage.py seed_injury_team_layout --commit
    docker compose exec backend python manage.py seed_injury_team_layout --category SUB-20 --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from core.models import Category, Department
from dashboards.models import TeamReportLayout, TeamReportSection, TeamReportWidget
from exams.models import Episode

TITULO = "Lesiones"


def _b(title, dimension, render, span, measure="count", **extra):
    cfg = {"dimension": dimension, "measure": measure, "render": render, **extra}
    return {"chart_type": "team_injury_breakdown", "title": title, "column_span": span,
            "display_config": cfg}


WIDGETS = [
    {"chart_type": "team_injury_kpis", "title": "Resumen de lesiones", "column_span": 12},
    {"chart_type": "team_injury_list", "title": "Lesionados actuales", "column_span": 12,
     "display_config": {"status": "open"}},
    {"chart_type": "team_injury_list", "title": "Lesionados en el período", "column_span": 12,
     "display_config": {"status": "period",
                        "columns": ["player", "started", "diagnosis", "lado", "days",
                                    "tratamiento", "recurrencia", "modo"]}},
    _b("Días perdidos por jugador", "player", "bar", 12, measure="days", limit=25),
    _b("Parte del cuerpo lesionada", "body_part", "bar", 6),
    _b("Tipo de lesión", "type", "bar", 6),
    _b("Músculos lesionados", "musculo", "donut", 4, hide_unknown=True),
    _b("Posición de juego", "position", "donut", 4),
    _b("Causa", "modo", "donut", 4),
    _b("Exposición", "exposicion", "donut", 4),
    _b("Recurrencia", "recurrencia", "donut", 4),
    _b("Lateralidad", "lado", "donut", 4),
]


class Command(BaseCommand):
    help = "Agrega la sección 'Lesiones' al layout de equipo Médico de cada categoría."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", action="append", dest="categories",
                            help="Limitar a una categoría (repetible). Por defecto: las que "
                                 "tienen lesiones registradas.")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        medico = Department.objects.filter(club__name=opts["club"], slug="medico").first()
        if medico is None:
            raise CommandError("El club no tiene departamento Médico.")
        cats = Category.objects.filter(club__name=opts["club"])
        if opts.get("categories"):
            cats = cats.filter(name__in=opts["categories"])
        else:
            con = (Episode.objects.filter(template__slug="lesiones",
                                          player__category__club__name=opts["club"])
                   .values_list("player__category_id", flat=True).distinct())
            cats = cats.filter(pk__in=con)
        if not cats.exists():
            raise CommandError("Ninguna categoría para ese filtro.")

        with transaction.atomic():
            for cat in cats.order_by("name"):
                self.stdout.write(f"  {cat.name:<22} {self._seccion(medico, cat)}")
            if not opts["commit"]:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            "APLICADO" if opts["commit"] else "PLAN — nada escrito, repetir con --commit"))

    def _seccion(self, medico, cat) -> str:
        layout = TeamReportLayout.objects.filter(department=medico, category=cat,
                                                 scope="period").first()
        creado = layout is None
        if creado:
            layout = TeamReportLayout.objects.create(department=medico, category=cat,
                                                     name=medico.name, scope="period",
                                                     is_active=True)
        elif layout.sections.filter(title=TITULO).exists():
            return "ya estaba"
        # First, pushing the rest down: it is what this report is opened for.
        layout.sections.update(sort_order=F("sort_order") + 1)
        sec = TeamReportSection.objects.create(layout=layout, title=TITULO, is_collapsible=True,
                                               default_collapsed=False, sort_order=0)
        for i, w in enumerate(WIDGETS):
            TeamReportWidget.objects.create(
                section=sec, chart_type=w["chart_type"], title=w["title"],
                column_span=w["column_span"], display_config=w.get("display_config", {}),
                sort_order=i)
        return f"{'layout creado + ' if creado else ''}sección agregada ({len(WIDGETS)} widgets)"
