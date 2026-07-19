"""Seed the Psicosocial TEAM report layout (Dashboard) focused on Fatiga Central.

Team-scoped counterpart to the per-player `seed_psicosocial_layout`. Builds a
`TeamReportLayout` (scope=period) for the Psicosocial department that answers
"how is the squad's central fatigue?" using the `fatiga_central` template:

  · Roster matrix (jugador × indicador, latest) — clinical band borders show
    who is in the red on Δ% / var% / PR / EA at a glance.
  · Weekly team-average trends for Δ% (objective, CFF vs basal) and PR
    (subjective recovery).
  · Distribution of PR + a leaderboard of the lowest PR (worst recovery).
  · Active fatiga alerts for the department.

Idempotent: rebuilds the (department, category, period) layout in place.

    docker compose exec backend python manage.py seed_psicosocial_team_layout \\
        --club "Universidad de Chile" --category "Primer Equipo"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from dashboards.models import (
    Aggregation,
    ChartType,
    LayoutScope,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
)
from exams.models import ExamTemplate


def _sections(fatiga: ExamTemplate) -> list[dict]:
    """The Fatiga Central team dashboard. `fatiga` is the fatiga_central
    template; only field keys that actually exist on it are used."""
    have = {
        f.get("key")
        for f in (fatiga.config_schema or {}).get("fields", [])
        if isinstance(f, dict) and f.get("key")
    }

    def keys(*ks: str) -> list[str]:
        return [k for k in ks if k in have]

    src_latest = lambda field_keys: {  # noqa: E731
        "template": fatiga, "field_keys": field_keys, "aggregation": Aggregation.LATEST,
    }
    src_all = lambda field_keys: {  # noqa: E731
        "template": fatiga, "field_keys": field_keys, "aggregation": Aggregation.ALL,
    }

    return [
        {
            "title": "Estado actual del plantel",
            "is_collapsible": False,
            "widgets": [{
                "chart_type": ChartType.TEAM_ROSTER_MATRIX,
                "title": "Jugador × indicador (última medición)",
                "description": (
                    "Última medición de fatiga central por jugador. El borde de "
                    "cada celda usa la banda clínica: rojo = alerta, amarillo = "
                    "vigilar, verde = normal."
                ),
                "column_span": 12,
                "display_config": {"coloring": "none"},
                "sources": [src_latest(keys(
                    "cff_mean", "cff_basal", "delta_basal_pct",
                    "var_intra_pct", "pr", "ea",
                ))],
            }],
        },
        {
            "title": "Evolución — promedio del plantel",
            "is_collapsible": True,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_TREND_LINE,
                    "title": "Δ% CFF vs basal (semanal)",
                    "description": "Promedio del plantel de la desviación respecto al basal.",
                    "column_span": 6,
                    "display_config": {"bucket_size": "week", "week_label": "date"},
                    "sources": [src_all(keys("delta_basal_pct"))],
                },
                {
                    "chart_type": ChartType.TEAM_TREND_LINE,
                    "title": "Percepción de recuperación · PR (semanal)",
                    "description": "Promedio del plantel de la PR (1–10).",
                    "column_span": 6,
                    "display_config": {"bucket_size": "week", "week_label": "date"},
                    "sources": [src_all(keys("pr"))],
                },
            ],
        },
        {
            "title": "Distribución (última medición)",
            "is_collapsible": True,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Percepción de recuperación · PR",
                    "description": "Cómo se reparte la PR (1–10) del plantel en la última medición.",
                    "column_span": 6,
                    "display_config": {"bin_count": 5},
                    "sources": [src_latest(keys("pr"))],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Estado de ánimo · EA",
                    "description": "Cómo se reparte el EA (1–10) del plantel en la última medición.",
                    "column_span": 6,
                    "display_config": {"bin_count": 5},
                    "sources": [src_latest(keys("ea"))],
                },
            ],
        },
        {
            "title": "Alertas de fatiga",
            "is_collapsible": True,
            "widgets": [{
                "chart_type": ChartType.TEAM_ALERTS,
                "title": "Plantel · alertas activas de fatiga",
                "description": "Jugadores con alertas activas de fatiga central, por severidad.",
                "column_span": 12,
            }],
        },
    ]


def _build(department: Department, category: Category, name: str, sections: list[dict]) -> str:
    existing = TeamReportLayout.objects.filter(
        department=department, category=category, scope=LayoutScope.PERIOD,
    ).first()
    if existing:
        existing.sections.all().delete()
        layout = existing
        layout.name = name
        layout.is_active = True
        layout.save(update_fields=["name", "is_active", "updated_at"])
        action = "rebuilt"
    else:
        layout = TeamReportLayout.objects.create(
            department=department, category=category, name=name,
            is_active=True, scope=LayoutScope.PERIOD,
        )
        action = "created"

    for s_idx, sec in enumerate(sections):
        section = TeamReportSection.objects.create(
            layout=layout,
            title=sec.get("title", ""),
            is_collapsible=sec.get("is_collapsible", True),
            default_collapsed=sec.get("default_collapsed", False),
            sort_order=s_idx,
        )
        for w_idx, w in enumerate(sec["widgets"]):
            widget = TeamReportWidget.objects.create(
                section=section,
                chart_type=w["chart_type"],
                title=w["title"],
                description=w.get("description", ""),
                column_span=w.get("column_span", 12),
                chart_height=w.get("chart_height"),
                display_config=w.get("display_config", {}),
                sort_order=w_idx,
            )
            for src_idx, src in enumerate(w.get("sources", [])):
                TeamReportWidgetDataSource.objects.create(
                    widget=widget,
                    template=src["template"],
                    field_keys=src["field_keys"],
                    aggregation=src.get("aggregation", Aggregation.LATEST),
                    aggregation_param=src.get("aggregation_param", 3),
                    label=src.get("label", ""),
                    color=src.get("color", ""),
                    sort_order=src_idx,
                )
    return action


class Command(BaseCommand):
    help = "Seed the Psicosocial team report layout (Fatiga Central dashboard)."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", default="Primer Equipo")
        parser.add_argument("--department-slug", default="psicosocial")
        parser.add_argument("--template-slug", default="fatiga_central")
        parser.add_argument("--name", default="Fatiga central (equipo)")

    @transaction.atomic
    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"Club '{opts['club']}' not found.")
        dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
        if dept is None:
            raise CommandError(
                f"Department '{opts['department_slug']}' not found in {club.name}."
            )
        category = Category.objects.filter(club=club, name=opts["category"]).first()
        if category is None:
            raise CommandError(f"Category '{opts['category']}' not found in {club.name}.")
        if not category.departments.filter(pk=dept.pk).exists():
            raise CommandError(
                f"Category '{category.name}' has not opted into '{dept.name}'. "
                f"Add the department to the category first."
            )
        fatiga = ExamTemplate.objects.filter(
            department=dept, slug=opts["template_slug"],
        ).first()
        if fatiga is None:
            raise CommandError(
                f"Template '{opts['template_slug']}' not found in {dept}."
            )

        action = _build(dept, category, opts["name"], _sections(fatiga))
        self.stdout.write(self.style.SUCCESS(
            f"[{club.name}] {action} team layout '{opts['name']}' "
            f"for {dept.name} / {category.name}."
        ))
