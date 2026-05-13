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
            for src_index, src_spec in enumerate(widget_spec.get("sources", [])):
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
            for src_index, src_spec in enumerate(widget_spec.get("sources", [])):
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


def _player_alerts_section() -> dict:
    """Per-player alerts panel — auto-filtered to the layout's department.
    Returns the same section spec for every department so the widget shows
    up consistently across Médico / Físico / Nutricional / Táctico."""
    return {
        "title": "Alertas activas",
        "is_collapsible": True,
        "widgets": [{
            "chart_type": ChartType.PLAYER_ALERTS,
            "title": "Alertas del departamento",
            "description": (
                "Alertas activas del jugador originadas en este "
                "departamento (bandas clínicas, umbrales, objetivos)."
            ),
            "column_span": 12,
        }],
    }


def _team_alerts_section() -> dict:
    """Team-side alerts ranking — same shape per department."""
    return {
        "title": "Jugadores con alertas",
        "is_collapsible": True,
        "widgets": [{
            "chart_type": ChartType.TEAM_ALERTS,
            "title": "Plantel · alertas activas",
            "description": (
                "Ranking de jugadores con alertas activas en este "
                "departamento, ordenado por severidad."
            ),
            "column_span": 12,
        }],
    }


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

    # Alerts always lead — they're the "needs attention now" surface,
    # so they should be the first thing the doctor / coach sees when
    # opening a profile or a department report.
    player.insert(0, _player_alerts_section())
    team.insert(0, _team_alerts_section())
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

    # Alerts always lead — they're the "needs attention now" surface,
    # so they should be the first thing the doctor / coach sees when
    # opening a profile or a department report.
    player.insert(0, _player_alerts_section())
    team.insert(0, _team_alerts_section())
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

    # Alerts always lead — they're the "needs attention now" surface,
    # so they should be the first thing the doctor / coach sees when
    # opening a profile or a department report.
    player.insert(0, _player_alerts_section())
    team.insert(0, _team_alerts_section())
    return {"player": player, "team": team}


def _spec_nutricional(department: Department) -> dict:
    """Nutricional: aligned with the post-demo feedback (May 2026).

    Player view — mirrors what the nutritionist drew up:
      Row 1:  Composición de masas (donut)  ·  % Masas (multi-line)  ·  kg Masas (multi-line)
      Row 2:  Peso corporal  ·  Σ 6 pliegues  ·  IMO
      Row 3:  Tabla resumen — última toma + variación de las 4 métricas clave,
              con bordes semáforo desde `reference_ranges`.

    Team view — roster matrix expandido + distribuciones por métrica clave.
    """
    penta = _resolve_template(department, "pentacompartimental")

    # Donut: las 5 masas. Color stops alineados con la imagen de referencia.
    mass_colors = ["#1e3a8a", "#3b82f6", "#f59e0b", "#a855f7", "#ec4899"]

    player: list[dict] = []
    if penta is not None:
        donut_keys = _filter_keys(penta, [
            "masa_adiposa", "masa_muscular", "masa_osea",
            "masa_piel", "masa_residual",
        ])
        pct_keys = _filter_keys(penta, ["masa_muscular_pct", "masa_adiposa_pct"])
        kg_keys = _filter_keys(penta, ["masa_muscular", "masa_adiposa"])
        # IMC se suma como métrica de soporte (sin bandas — IMC con cortes
        # OMS engaña en deportistas musculados, así que aparece como dato
        # informativo nada más, junto a las 4 métricas que sí llevan
        # semáforo desde `reference_ranges`).
        summary_keys = _filter_keys(penta, [
            "masa_muscular_pct", "masa_adiposa_pct",
            "suma_pliegues", "imo", "imc",
        ])

        # Row 1 — composición + evoluciones por % y por kg (Image 2 top row).
        row1_widgets: list[dict] = []
        if donut_keys:
            row1_widgets.append({
                "chart_type": ChartType.DONUT_PER_RESULT,
                "title": "Composición de masas",
                "column_span": 4,
                "display_config": {"colors": mass_colors[:len(donut_keys)]},
                "sources": [{
                    "template": penta,
                    "field_keys": donut_keys,
                    "aggregation": Aggregation.LATEST,
                }],
            })
        if pct_keys:
            row1_widgets.append({
                "chart_type": ChartType.MULTI_LINE,
                "title": "Evolución porcentaje de masas",
                "column_span": 4,
                "display_config": {"colors": ["#3b82f6", "#f59e0b"]},
                "sources": [{
                    "template": penta,
                    "field_keys": pct_keys,
                    "aggregation": Aggregation.ALL,
                }],
            })
        if kg_keys:
            row1_widgets.append({
                "chart_type": ChartType.MULTI_LINE,
                "title": "Evolución kg de masas",
                "column_span": 4,
                "display_config": {"colors": ["#3b82f6", "#f59e0b"]},
                "sources": [{
                    "template": penta,
                    "field_keys": kg_keys,
                    "aggregation": Aggregation.ALL,
                }],
            })
        if row1_widgets:
            player.append({
                "title": "",
                "is_collapsible": False,
                "widgets": row1_widgets,
            })

        # Row 2 — peso / Σ 6 pliegues / IMO (Image 2 middle row).
        row2_widgets: list[dict] = []
        for key, title in [
            ("peso", "Evolución peso corporal"),
            ("suma_pliegues", "Evolución sumatoria 6 pliegues"),
            ("imo", "Evolución IMO"),
        ]:
            if _filter_keys(penta, [key]):
                row2_widgets.append({
                    "chart_type": ChartType.LINE_WITH_SELECTOR,
                    "title": title,
                    "column_span": 4,
                    "sources": [{
                        "template": penta,
                        "field_keys": [key],
                        "aggregation": Aggregation.ALL,
                    }],
                })
        if row2_widgets:
            player.append({
                "title": "Indicadores en el tiempo",
                "is_collapsible": False,
                "widgets": row2_widgets,
            })

        # Row 3 — tabla resumen con la última toma + variación. El border
        # semáforo lo aporta `reference_ranges` en cada field (ver
        # seed_pentacompartimental.py). aggregation_param=2 → última +
        # anterior, que es lo que el delta del comparison_table necesita.
        if summary_keys:
            player.append({
                "title": "Resumen métricas clave",
                "is_collapsible": False,
                "widgets": [{
                    "chart_type": ChartType.COMPARISON_TABLE,
                    "title": "Última toma · variación · semáforo",
                    "column_span": 12,
                    "sources": [{
                        "template": penta,
                        "field_keys": summary_keys,
                        "aggregation": Aggregation.LAST_N,
                        "aggregation_param": 2,
                    }],
                }],
            })

    team: list[dict] = []
    if penta is not None:
        team.append({
            "title": "Composición corporal del plantel",
            "is_collapsible": False,
            "widgets": [
                {
                    # Matrix expandido — incluye las 4 métricas-semáforo
                    # (con bordes coloreados desde reference_ranges) y los
                    # absolutos (peso, IMC, masas en kg) para contexto.
                    "chart_type": ChartType.TEAM_ROSTER_MATRIX,
                    "title": "Antropometría por jugador (última toma)",
                    "column_span": 12,
                    "display_config": {"coloring": "vs_team_range", "variation": "absolute"},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, [
                            "peso", "imc",
                            "masa_muscular", "masa_muscular_pct",
                            "masa_adiposa", "masa_adiposa_pct",
                            "suma_pliegues", "imo",
                        ]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución de % Masa Adiposa",
                    "column_span": 6,
                    "display_config": {"bin_count": 8},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, ["masa_adiposa_pct"]) or ["peso"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución de % Masa Muscular",
                    "column_span": 6,
                    "display_config": {"bin_count": 8},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, ["masa_muscular_pct"]) or ["peso"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución de Σ 6 pliegues",
                    "column_span": 6,
                    "display_config": {"bin_count": 8},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, ["suma_pliegues"]) or ["peso"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_DISTRIBUTION,
                    "title": "Distribución de IMO",
                    "column_span": 6,
                    "display_config": {"bin_count": 8},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, ["imo"]) or ["peso"],
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_TREND_LINE,
                    "title": "Promedio del plantel — peso, IMC, % masa adiposa",
                    "column_span": 12,
                    "display_config": {"bucket_size": "month"},
                    "sources": [{
                        "template": penta,
                        "field_keys": _filter_keys(penta, [
                            "peso", "imc", "masa_adiposa_pct",
                        ]),
                        "aggregation": Aggregation.ALL,
                    }],
                },
            ],
        })

    # Alerts always lead — they're the "needs attention now" surface,
    # so they should be the first thing the doctor / coach sees when
    # opening a profile or a department report.
    player.insert(0, _player_alerts_section())
    team.insert(0, _team_alerts_section())
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
