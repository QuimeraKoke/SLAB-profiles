"""The injury report as its own "Lesiones" team layout in Médico.

It reproduces the club's injury sheet — "Lesionados actuales", "Lesionados en
el año", days lost per player, and the breakdowns by region, type, muscle,
position, cause, context and recurrence — with the three injury widgets of
`dashboards/team_injuries.py`.

A department can have several team layouts (Dashboard → Médico → General /
Lesiones), so the injury report gets its OWN layout instead of a section in
the general one. Per category, idempotent:

* a "Lesiones" layout already holding the section → nothing to do;
* the section sits in another Médico layout (where an earlier version of
  this command put it):
    - that layout has nothing else → it is renamed "Lesiones" (no empty
      "General" left behind);
    - it has other sections → the section MOVES to a new "Lesiones" layout,
      keeping any edit made to it;
* no section anywhere → a "Lesiones" layout is created with it.

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
        from django.db.models import Max

        propio = TeamReportLayout.objects.filter(department=medico, category=cat, scope="period",
                                                 slug="lesiones").first()
        if propio and propio.sections.filter(title=TITULO).exists():
            return "ya estaba"

        suelta = (TeamReportSection.objects
                  .filter(layout__department=medico, layout__category=cat,
                          layout__scope="period", title=TITULO)
                  .exclude(layout__slug="lesiones").select_related("layout").first())
        if suelta is not None:
            origen = suelta.layout
            if origen.sections.exclude(pk=suelta.pk).count() == 0 and propio is None:
                origen.name = "Lesiones"
                origen.slug = TeamReportLayout.unique_slug(medico.id, cat.id, "Lesiones", origen.pk)
                origen.save(update_fields=["name", "slug", "updated_at"])
                return "layout renombrado a «Lesiones»"
            destino = propio or self._nuevo(medico, cat)
            suelta.layout = destino
            suelta.sort_order = 0
            suelta.save(update_fields=["layout", "sort_order"])
            return f"sección movida de «{origen.name}» a «Lesiones»"

        destino = propio or self._nuevo(medico, cat)
        sec = TeamReportSection.objects.create(layout=destino, title=TITULO, is_collapsible=True,
                                               default_collapsed=False, sort_order=0)
        for i, w in enumerate(WIDGETS):
            TeamReportWidget.objects.create(
                section=sec, chart_type=w["chart_type"], title=w["title"],
                column_span=w["column_span"], display_config=w.get("display_config", {}),
                sort_order=i)
        return f"layout «Lesiones» con la sección ({len(WIDGETS)} widgets)"

    def _nuevo(self, medico, cat):
        from django.db.models import Max

        ultimo = TeamReportLayout.menu_for(medico, cat).aggregate(m=Max("sort_order"))["m"]
        return TeamReportLayout.objects.create(
            department=medico, category=cat, scope="period", name="Lesiones", slug="lesiones",
            is_active=True, sort_order=(ultimo + 1) if ultimo is not None else 0)
