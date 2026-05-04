"""Comprehensive layout seeder for the U. de Chile / Primer Equipo demo.

Creates BOTH per-player `DepartmentLayout`s (one per department) AND
team-wide `TeamReportLayout`s (one per department) in a single command.
Idempotent: re-running wipes and rebuilds the targeted layouts.

Departments covered: Médico, Físico, Táctico, Nutricional. Psicosocial
is not included by design — the demo focuses on the four data-rich
departments.

Each department gets:

  PLAYER VIEW (DepartmentLayout)
    - Médico:      injury body map, recent CK + hidratación, current medication
    - Físico:      GPS partido trends + entrenamiento trends + recent matches
    - Táctico:     rendimiento history, rating line, comparison table
    - Nutricional: comparison table, line selector, multi-line, grouped bar

  TEAM VIEW (TeamReportLayout)
    - Médico:      squad availability, active medications, recent injuries by region
    - Físico:      distance roster matrix, max-vel distribution, distance trend
    - Táctico:     rating + goals + assists matrix, rating distribution, rating trend
    - Nutricional: roster matrix (peso/IMC/grasa/muscular), IMC distribution, weight trend

Run:

    docker compose exec backend python manage.py seed_demo_layouts \\
        --club "Universidad de Chile" --category "Primer Equipo"

Pass `--skip-existing` to leave previously-created layouts untouched.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
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
from exams.models import ExamTemplate


# =============================================================================
# Helpers — build layouts from spec dicts to keep handle() readable.
# =============================================================================


def _resolve_template(department: Department, slug: str) -> ExamTemplate | None:
    """Find a template by slug in the given department. Returns None on miss
    so the caller can degrade gracefully (skip a section instead of crashing
    the whole seed) when a template hasn't been seeded yet."""
    return ExamTemplate.objects.filter(department=department, slug=slug).first()


def _filter_keys(template: ExamTemplate, keys: list[str]) -> list[str]:
    """Drop keys that aren't in the template's schema. Lets specs reference
    optional fields without breaking when a template skips them."""
    schema = {
        f.get("key") for f in (template.config_schema or {}).get("fields", [])
        if isinstance(f, dict)
    }
    return [k for k in keys if k in schema]


def _build_player_layout(
    department: Department, category: Category, name: str, sections: list[dict],
) -> tuple[str, int]:
    """Wipe + rebuild a DepartmentLayout from a section spec list.
    Returns (action, widget_count)."""
    existing = DepartmentLayout.objects.filter(
        department=department, category=category,
    ).first()
    if existing:
        existing.sections.all().delete()
        layout = existing
        action = "rebuilt"
    else:
        layout = DepartmentLayout.objects.create(
            department=department, category=category, name=name, is_active=True,
        )
        action = "created"

    widget_count = 0
    for section_index, section_spec in enumerate(sections):
        section = LayoutSection.objects.create(
            layout=layout,
            title=section_spec.get("title", ""),
            is_collapsible=section_spec.get("is_collapsible", True),
            default_collapsed=section_spec.get("default_collapsed", False),
            sort_order=section_index,
        )
        for widget_index, widget_spec in enumerate(section_spec["widgets"]):
            widget = Widget.objects.create(
                section=section,
                chart_type=widget_spec["chart_type"],
                title=widget_spec["title"],
                description=widget_spec.get("description", ""),
                column_span=widget_spec.get("column_span", 12),
                chart_height=widget_spec.get("chart_height"),
                display_config=widget_spec.get("display_config", {}),
                sort_order=widget_index,
            )
            for src_index, src_spec in enumerate(widget_spec["sources"]):
                WidgetDataSource.objects.create(
                    widget=widget,
                    template=src_spec["template"],
                    field_keys=src_spec["field_keys"],
                    aggregation=src_spec.get("aggregation", Aggregation.LAST_N),
                    aggregation_param=src_spec.get("aggregation_param", 3),
                    label=src_spec.get("label", ""),
                    color=src_spec.get("color", ""),
                    sort_order=src_index,
                )
            widget_count += 1
    return action, widget_count


def _build_team_layout(
    department: Department, category: Category, name: str, sections: list[dict],
) -> tuple[str, int]:
    """Same pattern as `_build_player_layout` but for TeamReportLayout."""
    existing = TeamReportLayout.objects.filter(
        department=department, category=category,
    ).first()
    if existing:
        existing.sections.all().delete()
        layout = existing
        action = "rebuilt"
    else:
        layout = TeamReportLayout.objects.create(
            department=department, category=category, name=name, is_active=True,
        )
        action = "created"

    widget_count = 0
    for section_index, section_spec in enumerate(sections):
        section = TeamReportSection.objects.create(
            layout=layout,
            title=section_spec.get("title", ""),
            is_collapsible=section_spec.get("is_collapsible", True),
            default_collapsed=section_spec.get("default_collapsed", False),
            sort_order=section_index,
        )
        for widget_index, widget_spec in enumerate(section_spec["widgets"]):
            widget = TeamReportWidget.objects.create(
                section=section,
                chart_type=widget_spec["chart_type"],
                title=widget_spec["title"],
                description=widget_spec.get("description", ""),
                column_span=widget_spec.get("column_span", 12),
                chart_height=widget_spec.get("chart_height"),
                display_config=widget_spec.get("display_config", {}),
                sort_order=widget_index,
            )
            for src_index, src_spec in enumerate(widget_spec["sources"]):
                TeamReportWidgetDataSource.objects.create(
                    widget=widget,
                    template=src_spec["template"],
                    field_keys=src_spec["field_keys"],
                    aggregation=src_spec.get("aggregation", Aggregation.LATEST),
                    aggregation_param=src_spec.get("aggregation_param", 3),
                    label=src_spec.get("label", ""),
                    color=src_spec.get("color", ""),
                    sort_order=src_index,
                )
            widget_count += 1
    return action, widget_count


# =============================================================================
# Layout specs per department. Each spec function returns:
#   { "player": [sections], "team": [sections] }
# Returns None for either side when required templates aren't seeded yet.
# =============================================================================


def _spec_medico(department: Department) -> dict:
    """Médico: injuries (Lesiones — episodic), CK trend, hidratación, medication."""
    lesiones = _resolve_template(department, "lesiones")
    ck = _resolve_template(department, "ck")
    hidra = _resolve_template(department, "hidratacion")
    medicacion = _resolve_template(department, "medicacion")

    player: list[dict] = []
    if lesiones is not None:
        player.append({
            "title": "Mapa de lesiones",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.BODY_MAP_HEATMAP,
                    "title": "Lesiones por región",
                    "column_span": 12,
                    "chart_height": 460,
                    "sources": [{
                        "template": lesiones,
                        "field_keys": ["body_part"],
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })

    measures_widgets: list[dict] = []
    if ck is not None:
        measures_widgets.append({
            "chart_type": ChartType.LINE_WITH_SELECTOR,
            "title": "CK — evolución",
            "column_span": 6,
            "sources": [{
                "template": ck,
                "field_keys": _filter_keys(ck, ["valor"]),
                "aggregation": Aggregation.ALL,
            }],
        })
    if hidra is not None:
        measures_widgets.append({
            "chart_type": ChartType.LINE_WITH_SELECTOR,
            "title": "Hidratación — evolución",
            "column_span": 6,
            "sources": [{
                "template": hidra,
                "field_keys": _filter_keys(hidra, ["densidad"]),
                "aggregation": Aggregation.ALL,
            }],
        })
    if measures_widgets:
        player.append({
            "title": "Indicadores clínicos",
            "widgets": measures_widgets,
        })

    if medicacion is not None:
        player.append({
            "title": "Medicación reciente",
            "widgets": [
                {
                    "chart_type": ChartType.COMPARISON_TABLE,
                    "title": "Últimas prescripciones",
                    "column_span": 12,
                    "sources": [{
                        "template": medicacion,
                        "field_keys": _filter_keys(medicacion, [
                            "medicamento", "dosis", "fecha_inicio", "fecha_fin", "motivo",
                        ]),
                        "aggregation": Aggregation.LAST_N,
                        "aggregation_param": 5,
                    }],
                },
            ],
        })

    team: list[dict] = []
    if lesiones is not None:
        team.append({
            "title": "Disponibilidad",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_STATUS_COUNTS,
                    "title": "Plantel disponible para entrenar / jugar",
                    "column_span": 12,
                    "display_config": {
                        "stage_colors": {
                            "available": "#16a34a",
                            "injured": "#dc2626",
                            "recovery": "#ea580c",
                            "reintegration": "#eab308",
                        },
                    },
                    "sources": [{
                        "template": lesiones,
                        "field_keys": ["stage"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
            ],
        })
    if medicacion is not None:
        team.append({
            "title": "Tratamiento activo",
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_ACTIVE_RECORDS,
                    "title": "Medicación activa",
                    "column_span": 12,
                    "display_config": {
                        "start_field": "fecha_inicio",
                        "end_field": "fecha_fin",
                    },
                    "sources": [{
                        "template": medicacion,
                        "field_keys": _filter_keys(medicacion, [
                            "medicamento", "dosis", "via_admin",
                        ]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
            ],
        })

    return {"player": player, "team": team}


def _spec_fisico(department: Department) -> dict:
    """Físico: GPS partido + GPS entrenamiento."""
    gps_match = _resolve_template(department, "gps_rendimiento_fisico_de_partido")
    gps_train = _resolve_template(department, "gps_entrenamiento")

    player: list[dict] = []
    if gps_match is not None:
        player.append({
            "title": "GPS — rendimiento de partido",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.LINE_WITH_SELECTOR,
                    "title": "Métricas físicas — evolución por partido",
                    "column_span": 12,
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [
                            "tot_dist_total", "max_vel_total", "hsr_total",
                            "sprint_total", "acc_dec_total", "hmld_total",
                            "player_load_total", "mpm_total",
                        ]),
                        "aggregation": Aggregation.ALL,
                    }],
                },
                {
                    "chart_type": ChartType.GROUPED_BAR,
                    "title": "Distancia + HSR — últimos 5 partidos",
                    "column_span": 6,
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, ["tot_dist_total", "hsr_total"]),
                        "aggregation": Aggregation.LAST_N,
                        "aggregation_param": 5,
                    }],
                },
                {
                    "chart_type": ChartType.COMPARISON_TABLE,
                    "title": "Últimos 3 partidos — totales",
                    "column_span": 6,
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [
                            "tot_dist_total", "tot_dur_total", "max_vel_total",
                            "hmld_total", "player_load_total",
                        ]),
                        "aggregation": Aggregation.LAST_N,
                        "aggregation_param": 3,
                    }],
                },
            ],
        })

    if gps_train is not None:
        player.append({
            "title": "GPS — entrenamientos",
            "widgets": [
                {
                    "chart_type": ChartType.LINE_WITH_SELECTOR,
                    "title": "Carga de entrenamiento — evolución",
                    "column_span": 12,
                    "sources": [{
                        "template": gps_train,
                        "field_keys": _filter_keys(gps_train, [
                            "tot_dist", "tot_dur", "player_load", "max_vel",
                            "hsr", "sprint", "acc", "rpe", "mpm",
                        ]),
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })

    team: list[dict] = []
    if gps_match is not None:
        team.append({
            "title": "Estado físico del plantel",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_ROSTER_MATRIX,
                    "title": "Promedios por jugador (último partido)",
                    "column_span": 12,
                    "display_config": {"coloring": "vs_team_range", "variation": "absolute"},
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [
                            "tot_dist_total", "max_vel_total", "hsr_total",
                            "sprint_total", "player_load_total",
                        ]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución — distancia por partido",
                    "column_span": 6,
                    "display_config": {"bin_count": 8},
                    "sources": [{
                        "template": gps_match,
                        "field_keys": ["tot_dist_total"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_TREND_LINE,
                    "title": "Promedio del plantel en el tiempo",
                    "column_span": 6,
                    "display_config": {"bucket_size": "month"},
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [
                            "tot_dist_total", "max_vel_total", "player_load_total",
                        ]),
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })

    return {"player": player, "team": team}


def _spec_tactico(department: Department) -> dict:
    """Táctico: per-player match performance — objective + subjective."""
    rendimiento = _resolve_template(department, "rendimiento_de_partido")

    player: list[dict] = []
    if rendimiento is not None:
        player.append({
            "title": "Rendimiento de partido",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.LINE_WITH_SELECTOR,
                    "title": "Métricas — evolución por partido",
                    "column_span": 8,
                    "sources": [{
                        "template": rendimiento,
                        "field_keys": _filter_keys(rendimiento, [
                            "rating", "minutes_played", "goals", "assists",
                            "shots", "shots_on_target", "yellow_cards",
                            "fouls_committed", "fouls_received",
                        ]),
                        "aggregation": Aggregation.ALL,
                    }],
                },
                {
                    "chart_type": ChartType.COMPARISON_TABLE,
                    "title": "Últimos 5 partidos",
                    "column_span": 4,
                    "sources": [{
                        "template": rendimiento,
                        "field_keys": _filter_keys(rendimiento, [
                            "minutes_played", "rating", "goals", "assists",
                        ]),
                        "aggregation": Aggregation.LAST_N,
                        "aggregation_param": 5,
                    }],
                },
            ],
        })

    team: list[dict] = []
    if rendimiento is not None:
        team.append({
            "title": "Rendimiento del plantel",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_ROSTER_MATRIX,
                    "title": "Estadísticas por jugador (último partido)",
                    "column_span": 12,
                    "display_config": {"coloring": "vs_team_range"},
                    "sources": [{
                        "template": rendimiento,
                        "field_keys": _filter_keys(rendimiento, [
                            "minutes_played", "rating", "goals", "assists",
                            "yellow_cards",
                        ]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución de ratings (último partido)",
                    "column_span": 6,
                    "display_config": {"bin_count": 6},
                    "sources": [{
                        "template": rendimiento,
                        "field_keys": ["rating"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_TREND_LINE,
                    "title": "Rating promedio del plantel",
                    "column_span": 6,
                    "display_config": {"bucket_size": "week"},
                    "sources": [{
                        "template": rendimiento,
                        "field_keys": ["rating"],
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })

    return {"player": player, "team": team}


def _spec_nutricional(department: Department) -> dict:
    """Nutricional: 5-component composition + roster matrix."""
    penta = _resolve_template(department, "pentacompartimental")

    # Default mass colors aligned with the existing seed_nutricional_layout.
    mass_colors = ["#3b82f6", "#f97316", "#10b981", "#f59e0b", "#a855f7"]

    player: list[dict] = []
    if penta is not None:
        comparison_keys = _filter_keys(penta, [
            "peso", "talla", "imc", "masa_adiposa", "masa_muscular",
            "masa_osea", "masa_piel", "masa_residual", "suma_pliegues",
        ])
        line_keys = _filter_keys(penta, [
            "peso", "imc", "grasa_faulkner", "masa_adiposa", "masa_muscular",
            "masa_osea", "masa_residual", "masa_piel", "suma_pliegues",
        ])
        mass_keys = _filter_keys(penta, [
            "masa_muscular", "masa_adiposa", "masa_osea",
            "masa_residual", "masa_piel",
        ])
        bar_keys = _filter_keys(penta, ["masa_adiposa", "masa_muscular"])

        player.append({
            "title": "",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.COMPARISON_TABLE,
                    "title": "Evolución antropométrica — últimas 3 tomas",
                    "column_span": 6,
                    "sources": [{
                        "template": penta,
                        "field_keys": comparison_keys,
                        "aggregation": Aggregation.LAST_N,
                        "aggregation_param": 3,
                    }],
                },
                {
                    "chart_type": ChartType.LINE_WITH_SELECTOR,
                    "title": "Evolución en el tiempo",
                    "column_span": 6,
                    "sources": [{
                        "template": penta,
                        "field_keys": line_keys,
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })
        if mass_keys:
            player.append({
                "title": "Fraccionamiento 5 masas",
                "widgets": [
                    {
                        "chart_type": ChartType.MULTI_LINE,
                        "title": "Evolución de las 5 masas",
                        "column_span": 12,
                        "display_config": {"colors": mass_colors[:len(mass_keys)]},
                        "sources": [{
                            "template": penta,
                            "field_keys": mass_keys,
                            "aggregation": Aggregation.ALL,
                        }],
                    },
                ],
            })
        if bar_keys:
            player.append({
                "title": "Análisis M. adiposa y M. muscular",
                "widgets": [
                    {
                        "chart_type": ChartType.GROUPED_BAR,
                        "title": "En kilogramos",
                        "column_span": 12,
                        "display_config": {"colors": mass_colors[:len(bar_keys)]},
                        "sources": [{
                            "template": penta,
                            "field_keys": bar_keys,
                            "aggregation": Aggregation.LAST_N,
                            "aggregation_param": 3,
                        }],
                    },
                ],
            })

    team: list[dict] = []
    if penta is not None:
        team.append({
            "title": "Composición corporal del plantel",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_ROSTER_MATRIX,
                    "title": "Antropometría por jugador (última toma)",
                    "column_span": 12,
                    "display_config": {"coloring": "vs_team_range", "variation": "absolute"},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, [
                            "peso", "imc", "grasa_faulkner",
                            "masa_muscular", "masa_adiposa",
                        ]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución de IMC",
                    "column_span": 6,
                    "display_config": {"bin_count": 8},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, ["imc"]) or ["peso"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_TREND_LINE,
                    "title": "Promedio del plantel — peso, IMC, % grasa",
                    "column_span": 6,
                    "display_config": {"bucket_size": "month"},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, [
                            "peso", "imc", "grasa_faulkner",
                        ]),
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })

    return {"player": player, "team": team}


_SPEC_BUILDERS: dict[str, Any] = {
    "medico": _spec_medico,
    "fisico": _spec_fisico,
    "tactico": _spec_tactico,
    "nutricional": _spec_nutricional,
}


# =============================================================================
# Command
# =============================================================================


class Command(BaseCommand):
    help = (
        "Seed per-player + team-report layouts for the four demo departments "
        "(Médico, Físico, Táctico, Nutricional) on a single (club, category)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", default="Primer Equipo")
        parser.add_argument(
            "--skip-existing", action="store_true",
            help="Leave existing layouts alone (default rebuilds them).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        club_name: str = options["club"]
        category_name: str = options["category"]
        skip_existing: bool = options["skip_existing"]

        club = Club.objects.filter(name=club_name).first()
        if club is None:
            raise CommandError(f"Club '{club_name}' not found.")
        category = Category.objects.filter(club=club, name=category_name).first()
        if category is None:
            raise CommandError(
                f"Category '{category_name}' not found in club '{club.name}'."
            )

        for slug in ("medico", "fisico", "tactico", "nutricional"):
            dept = Department.objects.filter(club=club, slug=slug).first()
            if dept is None:
                self.stdout.write(self.style.WARNING(
                    f"Skipping {slug}: department not found in club '{club.name}'."
                ))
                continue
            if not category.departments.filter(pk=dept.pk).exists():
                self.stdout.write(self.style.WARNING(
                    f"Skipping {slug}: category '{category.name}' is not opted into "
                    f"department '{dept.name}'."
                ))
                continue

            spec = _SPEC_BUILDERS[slug](dept)
            label = dept.name

            # ---- Player view ----
            existing_player = DepartmentLayout.objects.filter(
                department=dept, category=category,
            ).exists()
            if not spec["player"]:
                self.stdout.write(self.style.NOTICE(
                    f"  · {label} player view: no templates seeded yet, skipped."
                ))
            elif existing_player and skip_existing:
                self.stdout.write(self.style.NOTICE(
                    f"  · {label} player view: existing layout left alone (--skip-existing)."
                ))
            else:
                action, n = _build_player_layout(
                    dept, category, f"{label} default", spec["player"],
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  · {label} player view: {action} with {n} widget(s) "
                    f"in {len(spec['player'])} section(s)."
                ))

            # ---- Team view ----
            existing_team = TeamReportLayout.objects.filter(
                department=dept, category=category,
            ).exists()
            if not spec["team"]:
                self.stdout.write(self.style.NOTICE(
                    f"  · {label} team report: no templates seeded yet, skipped."
                ))
            elif existing_team and skip_existing:
                self.stdout.write(self.style.NOTICE(
                    f"  · {label} team report: existing layout left alone (--skip-existing)."
                ))
            else:
                action, n = _build_team_layout(
                    dept, category, f"{label} report", spec["team"],
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  · {label} team report: {action} with {n} widget(s) "
                    f"in {len(spec['team'])} section(s)."
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Layouts seeded for {category.name} / {club.name}."
        ))
