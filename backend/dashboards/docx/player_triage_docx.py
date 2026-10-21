"""Resumen (player triage) report as an editable Word document.

Same data + narrative as the PDF version (`dashboards/pdf/player_triage`);
this renders it to .docx. Caching is shared with the PDF path through the
content-addressed `PlayerReportSnapshot` (the narrative is stored once per
signature and reused, so producing the Word file costs no LLM call when a
report for the same data already exists)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from core.models import Player

from . import _docx
from dashboards.pdf.charts._mpl import capture_docx_figures
from dashboards.pdf.player_triage import (
    _ANALYSIS_KIND,
    _STATUS_BADGE,
    _delta_str,
    _evolution_chart,
    _format_date,
    _value_str,
    report_inputs,
)

_DISPLAY_TZ = ZoneInfo("America/Santiago")
_SEVERITY = {"critical": "Crítica", "warning": "Advertencia", "info": "Info"}


def render_or_get_triage_docx(player: Player, periodo=None, formato: str = "completo") -> bytes:
    """Download entry point. Returns the saved Word file for the player's
    current data signature if one exists; otherwise renders once (reusing a
    cached analysis narrative when present), persists, and returns it. Shares
    the PDF's content-addressed cache (kind `resumen`).

    `periodo` (`dashboards.report_period.Periodo`): every section covers it —
    the season cards, the match load, the training weeks, the metric
    evolution, the alerts — instead of the screen's mix of windows (all-time,
    30 days, 8 weeks, active now). `formato="ejecutivo"`: one or two pages."""
    from dashboards.pdf.narrative import generate_player_analysis_narrative
    from dashboards.pdf.report_cache import (
        get_saved_file, get_saved_narrative, save_file,
    )

    agent, model, signature, triage, analysis, payload = report_inputs(player, periodo)

    if formato != "ejecutivo":
        saved = get_saved_file(player, _ANALYSIS_KIND, signature, fmt="docx")
        if saved is not None:
            return saved

    narrative = get_saved_narrative(player, _ANALYSIS_KIND, signature)
    if narrative is None:
        narrative = generate_player_analysis_narrative(payload, agent=agent)

    if formato == "ejecutivo":
        if narrative:
            try:
                from dashboards.models import PlayerReportSnapshot

                PlayerReportSnapshot.objects.get_or_create(
                    player=player, kind=_ANALYSIS_KIND, data_hash=signature,
                    defaults={"model": model, "narrative": narrative})
            except Exception:  # noqa: BLE001 — best-effort
                pass
        return _render_ejecutivo(triage, player, narrative, periodo)

    docx_bytes = _render(triage, analysis, player, narrative, periodo)
    try:
        save_file(player, _ANALYSIS_KIND, signature, docx_bytes,
                  fmt="docx", model=model, narrative=narrative)
    except Exception:  # noqa: BLE001 — persistence is best-effort
        import logging
        logging.getLogger(__name__).exception("Failed to persist Resumen .docx snapshot.")
    return docx_bytes


def _render_ejecutivo(triage: dict, player: Player, narrative: dict | None, periodo) -> bytes:
    """One or two pages: what the agent concluded, the indicators against the
    previous period, the period's match tally, injuries, alerts, next steps."""
    from api.player_summary import player_squad_number
    from dashboards.pdf.scaffold import logo_image_for_club
    from exams.models import ExamTemplate

    from . import executive as ex

    doc = _docx.new_document()
    width = _docx.PORTRAIT_CONTENT_CM
    category = player.category
    club = category.club if category else None
    number = player_squad_number(player)
    meta = [("Equipo", category.season_label() if category else "")]
    if number:
        meta.append(("Dorsal", f"#{number}"))
    meta += [("Estado hoy", _STATUS_BADGE.get(player.status, (str(player.status).upper(), None))[0]),
             ("Período", periodo.etiqueta()),
             ("Comparado con", periodo.anterior().etiqueta()),
             ("Generado", triage["generated_at"].astimezone(_DISPLAY_TZ).strftime("%d/%m/%Y")
              if not periodo else _now_label())]
    _docx.report_header(
        doc, club_name=club.name if club else "",
        club_logo=_safe_logo(logo_image_for_club, club),
        title=f"{player.first_name} {player.last_name}".strip(),
        subtitle="Resumen ejecutivo", meta=meta,
    )
    ex.lo_esencial(doc, narrative)
    _docx.section_heading(doc, "Indicadores del período")
    plantillas = (ExamTemplate.objects.filter(applicable_categories=category,
                                              is_active_version=True).distinct()
                  if category else [])
    ex.tabla_indicadores(doc, ex.indicadores(plantillas, category, [player.id], periodo),
                         width_cm=width, titulo_periodo="Período")
    _partidos_del_periodo(doc, player, periodo, width)
    ex.disponibilidad(doc, [player], periodo, width_cm=width)
    ex.alertas(doc, [player], periodo, width_cm=width)
    ex.proximos_pasos(doc, narrative)
    ex.nota_final(doc)
    return _docx.to_bytes(doc)


def _now_label() -> str:
    from django.utils import timezone

    return timezone.now().astimezone(_DISPLAY_TZ).strftime("%d/%m/%Y · %H:%M")


def _partidos_del_periodo(doc, player, periodo, width) -> None:
    """The season cards, as one line each, for the period."""
    from api.player_summary import build_player_season_summary

    data = build_player_season_summary(player, periodo.desde, periodo.hasta)
    est, gps = data["estadisticas"], data["rendimiento_fisico"]
    _docx.section_heading(doc, "Partidos del período")
    if not est.get("partidos_jugados") and not gps.get("partidos_con_gps"):
        _docx.body(doc, "Sin partidos jugados en el período.")
        return
    filas = [["Partidos jugados", est.get("partidos_jugados", 0)],
             ["Minutos", f"{est.get('minutos_totales', 0)} min"],
             ["Goles · asistencias",
              f"{est.get('goles', 0)} · {est['asistencias'] if est.get('asistencias') is not None else '—'}"]]
    if gps.get("partidos_con_gps"):
        d = gps.get("distancia_promedio")
        v = gps.get("v_max_promedio")
        filas += [["Distancia por partido (GPS)",
                   "—" if d is None else f"{round(d):,} m".replace(",", ".")],
                  ["Velocidad máxima promedio", "—" if v is None else f"{v:.1f} km/h"]]
    _docx.add_table(doc, ["", "Período"], filas, width_cm=width, numeric_from=1)


def _render(triage: dict, analysis: dict, player: Player, narrative: dict | None,
            periodo=None) -> bytes:
    """Analytical Resumen report (Word): Resumen → Análisis → Conclusiones."""
    from dashboards.pdf.scaffold import logo_image_for_club
    from api.player_summary import player_squad_number

    narrative = narrative or {}
    doc = _docx.new_document()
    width = _docx.PORTRAIT_CONTENT_CM
    club = player.category.club if player.category else None

    status_label = _STATUS_BADGE.get(
        player.status, (str(player.status).upper(), None)
    )[0]
    gen = triage["generated_at"].astimezone(_DISPLAY_TZ)
    number = player_squad_number(player)
    meta = [("Equipo", player.category.season_label() if player.category else "")]
    if number:
        meta.append(("Dorsal", f"#{number}"))
    meta += [("Estado hoy" if periodo else "Estado", status_label)]
    if periodo is not None:
        meta.append(("Período", periodo.etiqueta()))
    meta.append(("Generado", (_now_label() if periodo else gen.strftime("%d/%m/%Y · %H:%M"))))
    _docx.report_header(
        doc,
        club_name=club.name if club else "",
        club_logo=_safe_logo(logo_image_for_club, club),
        title=f"{player.first_name} {player.last_name}".strip(),
        subtitle="Resumen",
        meta=meta,
    )

    # ── RESUMEN ──
    _docx.section_heading(doc, "Resumen")
    if narrative.get("resumen"):
        _docx.body(doc, narrative["resumen"])
    acwr = (analysis.get("training") or {}).get("acwr")
    if acwr:
        _docx.body(doc, f"ACWR {acwr['value']} — {acwr['label']}.")
    _render_season_summary(doc, player, width, periodo)

    # ── ANÁLISIS ──
    _docx.section_heading(doc, "Análisis")
    for b in narrative.get("analisis") or []:
        _docx.body(doc, f"• {b}")

    _render_match_load(doc, analysis.get("match_load") or {}, width)
    _render_training(doc, analysis.get("training") or {}, width)
    _render_position(doc, analysis.get("position") or {}, width)

    # Evolución de métricas — per-metric line chart over the period.
    _docx.widget_title(doc, "Evolución de métricas del período" if periodo
                       else "Evolución de métricas (30 días)")
    others = triage.get("other_metrics") or []
    if others:
        for m in others:
            p = doc.add_paragraph()
            run = p.add_run(f"{m['field_label']}  ·  {m['template_label']}")
            run.bold = True
            run.font.size = _docx.Pt(9.5)
            run.font.color.rgb = _docx.NAVY
            with capture_docx_figures() as figs:
                _evolution_chart(m)
            if figs:
                _docx.add_chart_images(doc, list(figs), max_width_cm=width)
            else:
                _docx.body(doc, _metric_inline(m))
    else:
        _docx.body(doc, "Sin métricas registradas.", muted=True)

    # Alertas (del período, o activas sin período)
    _docx.widget_title(doc, "Alertas del período" if periodo else "Alertas activas")
    alerts = triage.get("alerts") or []
    if alerts:
        _docx.add_table(
            doc, ["Severidad", "Mensaje", "Detectada"],
            [[_SEVERITY.get(a["severity"], a["severity"].title()),
              a["message"], _format_date(a["last_fired_at"])] for a in alerts],
            width_cm=width, numeric_from=99,
        )
    else:
        _docx.body(doc, "Sin alertas — todo en orden.", muted=True)

    # Último / próximo partido
    match = triage.get("last_match")
    mtitle = "Último partido" if (match and match.get("is_past")) else "Próximo partido"
    _docx.widget_title(doc, mtitle)
    _render_match(doc, match)

    # ── CONCLUSIONES ──
    _docx.section_heading(doc, "Conclusiones")
    conclusiones = narrative.get("conclusiones") or []
    if conclusiones:
        for c in conclusiones:
            _docx.body(doc, f"• {c}")
    else:
        _docx.body(doc, "Sin conclusiones automáticas (IA no disponible).", muted=True)

    return _docx.to_bytes(doc)


def _render_match_load(doc, match_load: dict, width: float) -> None:
    n = match_load.get("n_matches") or 0
    _docx.widget_title(doc, "Carga de partido — tendencia y correlaciones")
    if n < 2:
        _docx.body(doc, "Sin suficientes partidos con GPS para analizar la tendencia.", muted=True)
        return
    primary = match_load.get("primary")
    if primary and primary.get("trend"):
        tr = primary["trend"]
        arrow = {"up": "↑", "down": "↓", "flat": "→"}.get(tr["direction"], "")
        pct = f" ({tr['pct_change']:+.1f}%)" if tr.get("pct_change") is not None else ""
        comov = ", ".join(f"{c['label']} (r={c['r']})" for c in (primary.get("comovers") or []))
        line = f"{primary['label']}: tendencia {arrow}{pct} sobre {n} partidos."
        if comov:
            line += f" Acompañan: {comov}."
        _docx.body(doc, line)
    corrs = match_load.get("correlations") or []
    if corrs:
        _docx.add_table(
            doc, ["Variable A", "Variable B", "r", "n"],
            [[c["a_label"], c["b_label"], c["r"], c["n"]] for c in corrs],
            width_cm=width, numeric_from=2,
        )


def _render_training(doc, training: dict, width: float) -> None:
    _docx.widget_title(doc, "Carga de entrenamiento — ACWR y microciclos")
    acwr = training.get("acwr")
    if acwr:
        _docx.body(doc, f"ACWR {acwr['value']} — {acwr['label']} (agudo 7d ÷ crónico 28d-semanal).")
    micro = training.get("microcycle")
    if micro:
        pct = f" ({micro['pct_change']:+.1f}%)" if micro.get("pct_change") is not None else ""
        _docx.body(
            doc,
            f"Microciclo actual ({micro['current_week']}): {micro['current_load']} u.a. "
            f"vs. promedio previo {micro['prior_avg_load']} u.a.{pct}.",
        )
    weekly = training.get("weekly") or []
    if weekly:
        _docx.add_table(
            doc, ["Semana", "Distancia (m)", "Player Load", "Sesiones"],
            [[w["week"], w["dist"], w["load"], w["sessions"]] for w in weekly],
            width_cm=width, numeric_from=1,
        )
    if not (acwr or micro or weekly):
        _docx.body(doc, "Sin datos de entrenamiento suficientes.", muted=True)


def _render_position(doc, position: dict, width: float) -> None:
    label = position.get("position_label")
    metrics = position.get("metrics") or []
    _docx.widget_title(doc, f"Contexto por posición — {label}" if label else "Contexto por posición")
    if not metrics:
        _docx.body(doc, "Sin pares de la misma posición suficientes para comparar.", muted=True)
        return
    _docx.add_table(
        doc, ["Métrica", "Jugador", "Prom. posición", "Percentil", "n"],
        [[m["label"], m["value"], m["position_avg"], m["percentile"], m["n"]] for m in metrics],
        width_cm=width, numeric_from=1,
    )


def _render_season_summary(doc, player, width: float, periodo=None) -> None:
    """3-card season block (estadísticas de juego · rendimiento físico ·
    reporte médico) under a 'Resumen de temporada' heading. Reuses the same
    `build_player_season_summary` aggregation as the web + the PDF ficha."""
    from api.player_summary import build_player_season_summary

    data = (build_player_season_summary(player, periodo.desde, periodo.hasta) if periodo
            else build_player_season_summary(player))
    est = data["estadisticas"]
    gps = data["rendimiento_fisico"]
    med = data["reporte_medico"]

    def _m(v):
        return "—" if v is None else f"{round(v):,} m".replace(",", ".")

    def _i(v):
        return "—" if v is None else f"{round(v):,}".replace(",", ".")

    def _d1(v):
        return "—" if v is None else f"{v:.1f}"

    _docx.section_heading(doc, "Resumen del período" if periodo else "Resumen de temporada")

    _docx.widget_title(doc, "Estadísticas de juego")
    _docx.add_table(
        doc, ["Campo", "Valor"],
        [
            ["Partidos jugados", est["partidos_jugados"]],
            ["Minutos totales", f"{est['minutos_totales']} min"],
            ["Goles", est["goles"]],
            ["Asistencias", est["asistencias"] if est["asistencias"] is not None else "—"],
            ["Amarillas", est["amarillas"]],
            ["Rojas", est["rojas"]],
        ],
        width_cm=width, numeric_from=1,
    )

    _docx.widget_title(doc, "Rendimiento físico")
    _docx.add_table(
        doc, ["Campo", "Valor"],
        [
            ["Partidos con GPS", gps.get("partidos_con_gps", 0)],
            ["Distancia / partido", _m(gps.get("distancia_promedio"))],
            ["V max promedio", _d1(gps.get("v_max_promedio"))],
            ["HIAA promedio", _i(gps.get("hiaa_promedio"))],
            ["HMLD promedio", _m(gps.get("hmld_promedio"))],
            ["Aceleraciones promedio", _i(gps.get("aceleraciones_promedio"))],
        ],
        width_cm=width, numeric_from=1,
    )

    _docx.widget_title(doc, "Reporte médico")
    med_rows = [["Estado", med["player_status_label"]]]
    episodes = med.get("episodes") or []
    if episodes:
        for e in episodes[:3]:
            stage = e["stage"] or ("Cerrado" if e["status"] == "closed" else "Abierto")
            med_rows.append([e["title"], stage])
    else:
        med_rows.append(["Episodios", "Sin episodios"])
    _docx.add_table(doc, ["Campo", "Valor"], med_rows, width_cm=width, numeric_from=1)


def _render_match(doc, match: dict | None) -> None:
    if match is None:
        _docx.body(doc, "No hay partidos en el calendario.", muted=True)
        return
    date_str = _format_date(match.get("event_starts_at"), with_year=True)
    _docx.body(doc, f"{match.get('event_title', '')}  ·  {date_str}")
    _docx.body(doc, f"Estado: {match.get('match_role_label') or '—'}")

    played = {"titular", "suplente_ingresa", "suplente_no_ingresa"}
    if match.get("match_role") in played:
        bits = []
        if match.get("minutes_played") is not None:
            bits.append(f"Min: {match['minutes_played']}")
        if match.get("goals"):
            bits.append(f"Goles: {match['goals']}")
        if bits:
            _docx.body(doc, "  ·  ".join(bits))


def _metric_inline(m: dict) -> str:
    parts = [f"actual: {_value_str(m['current_value'], m['unit'])}"]
    if m.get("previous_value") is not None:
        parts.append(f"previo: {_value_str(m['previous_value'], m['unit'])}")
    d = _delta_str(m.get("delta"), m["unit"], m.get("direction_of_good"))
    if d != "—":
        parts.append(f"Δ {d}")
    return "  ·  ".join(parts)


def _safe_logo(fn, club):
    if club is None:
        return None
    try:
        return fn(club)
    except Exception:  # noqa: BLE001
        return None
