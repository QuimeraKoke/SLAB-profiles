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
    department: Department, category: Category, name: str,
    sections: list[dict],
    *,
    match_selector_config: dict | None = None,
) -> tuple[str, int]:
    """Same pattern as `_build_player_layout` but for TeamReportLayout.

    `match_selector_config` is an optional JSON blob set on the
    TeamReportLayout to enable the per-match hero selector at the top
    of the report page (see TeamReportLayout.match_selector_config in
    `dashboards/models.py` for the expected shape).
    """
    existing = TeamReportLayout.objects.filter(
        department=department, category=category,
    ).first()
    if existing:
        existing.sections.all().delete()
        layout = existing
        layout.name = name
        layout.match_selector_config = match_selector_config or {}
        layout.save(update_fields=["name", "match_selector_config", "updated_at"])
        action = "rebuilt"
    else:
        layout = TeamReportLayout.objects.create(
            department=department, category=category, name=name, is_active=True,
            match_selector_config=match_selector_config or {},
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
    """Médico: injuries (Lesiones — episodic), CK trend, hidratación,
    medication, daily molestias log, daily Check-IN wellness."""
    lesiones = _resolve_template(department, "lesiones")
    ck = _resolve_template(department, "ck")
    hidra = _resolve_template(department, "hidratacion")
    medicacion = _resolve_template(department, "medicacion")
    molestias = _resolve_template(department, "molestias")
    check_in = _resolve_template(department, "check_in")

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

    if molestias is not None:
        player.append({
            "title": "Molestias recientes",
            "widgets": [{
                "chart_type": ChartType.ACTIVITY_LOG,
                "title": "Últimas molestias registradas",
                "column_span": 12,
                "display_config": {"limit": 15},
                "sources": [{
                    "template": molestias,
                    "field_keys": _filter_keys(molestias, [
                        "tipo", "zona", "comentarios",
                    ]),
                    "aggregation": Aggregation.LAST_N,
                    "aggregation_param": 15,
                }],
            }],
        })

    if check_in is not None:
        player.append({
            "title": "Check-IN diario",
            "widgets": [{
                "chart_type": ChartType.LINE_WITH_SELECTOR,
                "title": "Evolución de las 5 dimensiones",
                "column_span": 12,
                "sources": [{
                    "template": check_in,
                    "field_keys": _filter_keys(check_in, [
                        "doms", "animo", "estres", "fatiga", "sueno",
                        "total_bienestar",
                    ]),
                    "aggregation": Aggregation.ALL,
                }],
            }],
        })

    team: list[dict] = []
    # NOTE: the "Disponibilidad / Plantel disponible" team_status_counts
    # widget used to live here. Removed once the executive-summary block
    # (KPI strip + 4-column-by-status table with player names) covered
    # the same information directly on the cover — the chart became
    # redundant. Re-add by uncommenting from git history if needed.
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

    if ck is not None:
        team.append({
            "title": "CK del plantel",
            "widgets": [{
                "chart_type": ChartType.TEAM_LEADERBOARD,
                "title": "CK por jugador",
                "description": (
                    "Última medición de CK por jugador. Líneas: límite "
                    "inferior, superior y promedio del plantel."
                ),
                "column_span": 12,
                "chart_height": 320,
                "display_config": {
                    "style": "vertical_bars",
                    "aggregator": "latest",
                    "order": "desc",
                    "limit": 30,
                    "show_team_avg_line": True,
                    "reference_lines": [
                        {"value": 200, "label": "Límite inferior", "color": "#16a34a"},
                        {"value": 500, "label": "Límite superior", "color": "#dc2626"},
                    ],
                },
                "sources": [{
                    "template": ck,
                    "field_keys": _filter_keys(ck, ["valor"]),
                    "aggregation": Aggregation.LATEST,
                }],
            }],
        })

    if hidra is not None:
        team.append({
            "title": "Densidad urinaria",
            "widgets": [{
                "chart_type": ChartType.TEAM_LEADERBOARD,
                "title": "Densidad urinaria por jugador",
                "description": (
                    "Última lectura por jugador. Zona amarilla = "
                    "hidratación límite (1.020–1.030). Verde por debajo."
                ),
                "column_span": 12,
                "chart_height": 320,
                "display_config": {
                    "style": "vertical_bars",
                    "aggregator": "latest",
                    "order": "desc",
                    "limit": 30,
                    # Zoom: values span 1.000–1.040 — the differences live
                    # in the 3rd decimal, so a 0→1.040 chart crushes them
                    # into identical-looking bars. y_min/y_max + decimals=3
                    # make the variation actually readable.
                    "y_min": 1.000,
                    "y_max": 1.040,
                    "decimals": 3,
                    "reference_bands": [
                        {
                            "min": 1.000,
                            "max": 1.020,
                            "label": "Hidratado",
                            "color": "#bbf7d0",
                        },
                        {
                            "min": 1.020,
                            "max": 1.030,
                            "label": "Amarillo",
                            "color": "#fef08a",
                        },
                        {
                            "min": 1.030,
                            "max": 1.040,
                            "label": "Deshidratado",
                            "color": "#fecaca",
                        },
                    ],
                },
                "sources": [{
                    "template": hidra,
                    "field_keys": _filter_keys(hidra, ["densidad"]),
                    "aggregation": Aggregation.LATEST,
                }],
            }],
        })

    if molestias is not None:
        team.append({
            "title": "Molestias del plantel",
            "widgets": [{
                "chart_type": ChartType.TEAM_ACTIVITY_LOG,
                "title": "Últimas molestias reportadas",
                "description": "Hoja diaria de tratamientos médicos.",
                "column_span": 12,
                "display_config": {"limit": 25},
                "sources": [{
                    "template": molestias,
                    "field_keys": _filter_keys(molestias, [
                        "tipo", "zona", "comentarios",
                    ]),
                    "aggregation": Aggregation.LAST_N,
                    "aggregation_param": 25,
                }],
            }],
        })

    if check_in is not None:
        team.append({
            "title": "Check-IN del plantel",
            "widgets": [{
                "chart_type": ChartType.TEAM_DAILY_GROUPED_BARS,
                "title": "Promedio diario por dimensión",
                "description": (
                    "Cada barra es el promedio del plantel para una "
                    "dimensión, por día (escala 1-5). La línea muestra "
                    "el Total Bienestar (suma de las 5 dimensiones, "
                    "rango 5-25)."
                ),
                "column_span": 12,
                "chart_height": 360,
                "display_config": {
                    "show_total_line": True,
                    "total_label": "Total Bienestar",
                    "total_color": "#111827",
                    "day_limit": 7,
                    # Fixed axis ranges: bars stay on the Likert 1-5 scale,
                    # the total-line axis on its native 5-25 sum range.
                    # Without these recharts auto-scales each axis to
                    # the data's local min/max and the chart looks
                    # different every day depending on the team's mood.
                    "y_min": 1,
                    "y_max": 5,
                    "total_y_min": 5,
                    "total_y_max": 25,
                    "decimals": 1,
                    "field_colors": {
                        "doms":   "#dc2626",
                        "animo":  "#16a34a",
                        "estres": "#f59e0b",
                        "fatiga": "#8b5cf6",
                        "sueno":  "#0ea5e9",
                    },
                },
                "sources": [{
                    "template": check_in,
                    "field_keys": _filter_keys(check_in, [
                        "doms", "animo", "estres", "fatiga", "sueno",
                    ]),
                    "aggregation": Aggregation.ALL,
                }],
            }],
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
    team_match_selector_config: dict | None = None
    if gps_match is not None:
        # Físico team report = per-match GPS dashboard. The selector hero
        # at the top scopes EVERY widget below to the chosen match.
        team_match_selector_config = {
            "enabled": True,
            "event_type": "match",
            "required": True,
            "label": "Partido",
            "show_recent": 12,
        }
        team.extend(_gps_team_sections(gps_match))

    # Alerts always lead — they're the "needs attention now" surface,
    # so they should be the first thing the doctor / coach sees when
    # opening a profile or a department report.
    player.insert(0, _player_alerts_section())
    team.insert(0, _team_alerts_section())
    return {
        "player": player,
        "team": team,
        "team_match_selector_config": team_match_selector_config,
    }


def _gps_team_sections(gps_match) -> list[dict]:
    """Build the 3-section GPS match report: General / Primer T. / Segundo T.

    Same widget shapes in each half, just swapping `_total` → `_p1` / `_p2`
    suffixes. Keeps the seed compact and the page narrative consistent.
    """
    def keys_for(suffix: str) -> dict:
        # Helpers so the section block stays readable.
        return {
            "tot_dist": f"tot_dist_{suffix}",
            "mpm": f"mpm_{suffix}",
            "tot_dur": f"tot_dur_{suffix}",
            "hsr": f"hsr_{suffix}",
            "sprint": f"sprint_{suffix}",
            "dist70": f"dist_70_85_{suffix}",
            "dist85": f"dist_85_95_{suffix}",
            "acc_dec": f"acc_dec_{suffix}",
            "acc": f"acc_{suffix}",
            "dec": f"dec_{suffix}",
            "max_vel": f"max_vel_{suffix}",
            "hiaa": f"hiaa_{suffix}",
            "hmld": f"hmld_{suffix}",
            "player_load": f"player_load_{suffix}",
        }

    def per_half_sections(label: str, suffix: str) -> dict:
        k = keys_for(suffix)
        return {
            "title": label,
            "is_collapsible": True,
            "default_collapsed": False,
            "widgets": [
                {
                    "chart_type": ChartType.TEAM_MATCH_SUMMARY,
                    "title": f"Resumen agregado — {label.lower()}",
                    "column_span": 12,
                    "display_config": {"per_player_aggregator": "latest"},
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [
                            k["tot_dist"], k["mpm"], k["hsr"], k["sprint"],
                            k["acc_dec"], k["max_vel"], k["hiaa"], k["hmld"],
                        ]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_HORIZONTAL_COMPARISON,
                    "title": "Distancia + Metros por minuto",
                    "column_span": 12,
                    "chart_height": 520,
                    "display_config": {"mode": "multi_field"},
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [k["tot_dist"], k["mpm"]]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_LEADERBOARD,
                    "title": "Sprints (>25 km/h)",
                    "column_span": 6,
                    "chart_height": 300,
                    "display_config": {
                        "style": "vertical_bars",
                        "aggregator": "sum",
                        "order": "desc",
                        "limit": 20,
                    },
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [k["sprint"]]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
                {
                    "chart_type": ChartType.TEAM_LEADERBOARD,
                    "title": "Velocidad máxima",
                    "column_span": 6,
                    "chart_height": 300,
                    "display_config": {
                        "style": "vertical_bars",
                        "aggregator": "max",
                        "order": "desc",
                        "limit": 20,
                    },
                    "sources": [{
                        "template": gps_match,
                        "field_keys": _filter_keys(gps_match, [k["max_vel"]]),
                        "aggregation": Aggregation.LATEST,
                    }],
                },
            ],
        }

    sections: list[dict] = []

    # ---- General (totals across the match) ----
    g = keys_for("total")
    sections.append({
        "title": "General",
        "is_collapsible": False,
        "widgets": [
            {
                "chart_type": ChartType.TEAM_MATCH_SUMMARY,
                "title": "Totales del partido",
                "column_span": 12,
                "display_config": {"per_player_aggregator": "latest"},
                "sources": [{
                    "template": gps_match,
                    "field_keys": _filter_keys(gps_match, [
                        g["tot_dist"], g["mpm"], g["hsr"], g["sprint"],
                        g["acc_dec"], g["max_vel"], g["hiaa"], g["hmld"],
                    ]),
                    "aggregation": Aggregation.LATEST,
                }],
            },
            {
                "chart_type": ChartType.TEAM_HORIZONTAL_COMPARISON,
                "title": "Distancia + Metros por minuto",
                "column_span": 12,
                "chart_height": 520,
                "display_config": {"mode": "multi_field"},
                "sources": [{
                    "template": gps_match,
                    "field_keys": _filter_keys(gps_match, [g["tot_dist"], g["mpm"]]),
                    "aggregation": Aggregation.LATEST,
                }],
            },
            # NOTE: "Zonas 75-85% / 85-95% V max — Por posición" widget
            # (team_horizontal_comparison with mode=multi_field +
            # group_by=position) used to live here. Removed — the
            # group_by=position branch on multi_field doesn't have a
            # matplotlib renderer yet so the PDF was falling back to a
            # raw key/value dump. Reinstate once
            # `_render_team_horizontal_comparison_by_position` lands.
            {
                "chart_type": ChartType.TEAM_STACKED_BARS,
                "title": "Aceleraciones y desaceleraciones",
                "description": "Acc ≥3 + Dec ≥3 + Acc&Dec ≥3 apilados por jugador.",
                "column_span": 12,
                "chart_height": 420,
                "display_config": {
                    "aggregator": "sum",
                    "order": "desc",
                    "field_colors": {
                        g["acc"]: "#dc2626",
                        g["dec"]: "#0ea5e9",
                        g["acc_dec"]: "#facc15",
                    },
                },
                "sources": [{
                    "template": gps_match,
                    "field_keys": _filter_keys(gps_match, [
                        g["acc"], g["dec"], g["acc_dec"],
                    ]),
                    "aggregation": Aggregation.LATEST,
                }],
            },
            {
                "chart_type": ChartType.TEAM_LEADERBOARD,
                "title": "HIAA",
                "description": "Acciones de alta intensidad. La línea marca el promedio del plantel.",
                "column_span": 12,
                "chart_height": 320,
                "display_config": {
                    "style": "vertical_bars",
                    "aggregator": "sum",
                    "order": "desc",
                    "limit": 20,
                    # The team-average reference is computed in the
                    # admin / live; for the demo we hardcode 100 as
                    # a sensible target ceiling. Adjust per club.
                    "reference_line": {
                        "value": 100,
                        "label": "Objetivo",
                        "color": "#0ea5e9",
                    },
                },
                "sources": [{
                    "template": gps_match,
                    "field_keys": _filter_keys(gps_match, [g["hiaa"]]),
                    "aggregation": Aggregation.LATEST,
                }],
            },
            {
                "chart_type": ChartType.TEAM_ROSTER_MATRIX,
                "title": "Resumen jugador × métrica",
                "column_span": 12,
                "display_config": {"coloring": "vs_team_range"},
                "sources": [{
                    "template": gps_match,
                    "field_keys": _filter_keys(gps_match, [
                        g["tot_dur"], g["tot_dist"], g["mpm"],
                        g["hsr"], g["sprint"], g["acc_dec"],
                        g["max_vel"], g["hiaa"],
                    ]),
                    "aggregation": Aggregation.LATEST,
                }],
            },
        ],
    })

    sections.append(per_half_sections("Primer tiempo", "p1"))
    sections.append(per_half_sections("Segundo tiempo", "p2"))
    return sections


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
                    match_selector_config=spec.get("team_match_selector_config"),
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  · {label} team report: {action} with {n} widget(s) "
                    f"in {len(spec['team'])} section(s)."
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Layouts seeded for {category.name} / {club.name}."
        ))
