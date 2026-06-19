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
    RENDER_VERSION,
    _REPORT_KIND,
    _STATUS_BADGE,
    _evolution_chart,
    _delta_str,
    _format_date,
    _value_str,
    build_triage_payload,
)

_DISPLAY_TZ = ZoneInfo("America/Santiago")
_SEVERITY = {"critical": "Crítica", "warning": "Advertencia", "info": "Info"}


def render_or_get_triage_docx(player: Player) -> bytes:
    """Download entry point. Returns the saved Word file for the player's
    current data signature if one exists; otherwise renders once (reusing a
    cached narrative when present), persists, and returns it."""
    from django.conf import settings

    from dashboards.pdf.narrative import generate_player_narrative, resolve_insight_agent
    from dashboards.pdf.report_cache import (
        get_saved_file, get_saved_narrative, report_signature, save_file,
    )

    agent = resolve_insight_agent(_REPORT_KIND)
    model = ((agent.model or "").strip() if agent else "") or getattr(
        settings, "ANTHROPIC_MODEL", "claude-opus-4-7"
    )
    fingerprint = agent.config_fingerprint() if agent else "builtin"

    payload = build_triage_payload(player)
    signature = report_signature(
        payload, model=model, kind=_REPORT_KIND,
        render_version=RENDER_VERSION, agent_fingerprint=fingerprint,
    )

    saved = get_saved_file(player, _REPORT_KIND, signature, fmt="docx")
    if saved is not None:
        return saved

    narrative = get_saved_narrative(player, _REPORT_KIND, signature)
    if narrative is None:
        narrative = generate_player_narrative(payload, agent=agent)

    docx_bytes = _render(payload, player, narrative)
    try:
        save_file(player, _REPORT_KIND, signature, docx_bytes,
                  fmt="docx", model=model, narrative=narrative)
    except Exception:  # noqa: BLE001 — persistence is best-effort
        import logging
        logging.getLogger(__name__).exception("Failed to persist Resumen .docx snapshot.")
    return docx_bytes


def _render(payload: dict, player: Player, narrative: dict | None) -> bytes:
    from dashboards.pdf.scaffold import logo_image_for_club

    doc = _docx.new_document()
    width = _docx.PORTRAIT_CONTENT_CM
    club = player.category.club if player.category else None

    status_label = _STATUS_BADGE.get(
        player.status, (str(player.status).upper(), None)
    )[0]
    gen = payload["generated_at"].astimezone(_DISPLAY_TZ)
    _docx.report_header(
        doc,
        club_name=club.name if club else "",
        club_logo=_safe_logo(logo_image_for_club, club),
        title=f"{player.first_name} {player.last_name}".strip(),
        subtitle="Resumen",
        meta=[
            ("Categoría", player.category.name if player.category else ""),
            ("Estado", status_label),
            ("Generado", gen.strftime("%d/%m/%Y · %H:%M")),
        ],
    )

    _docx.add_narrative(doc, narrative)

    # Alertas activas
    _docx.section_heading(doc, "Alertas activas")
    alerts = payload.get("alerts") or []
    if alerts:
        _docx.add_table(
            doc, ["Severidad", "Mensaje", "Detectada"],
            [[_SEVERITY.get(a["severity"], a["severity"].title()),
              a["message"], _format_date(a["last_fired_at"])] for a in alerts],
            width_cm=width, numeric_from=99,
        )
    else:
        _docx.body(doc, "Sin alertas — todo en orden.", muted=True)

    # Métricas alertadas
    _docx.section_heading(doc, "Métricas alertadas")
    alerted = payload.get("alerted_metrics") or []
    if alerted:
        _docx.add_table(
            doc, ["Métrica", "Actual", "Previo", "Δ"],
            [[m["field_label"],
              _value_str(m["current_value"], m["unit"]),
              _value_str(m["previous_value"], m["unit"]),
              _delta_str(m["delta"], m["unit"], m["direction_of_good"])]
             for m in alerted],
            width_cm=width, numeric_from=1,
        )
    else:
        _docx.body(doc, "Sin métricas alertadas.", muted=True)

    # Evolución de métricas (30 días) — reuse the PDF line chart per metric.
    _docx.section_heading(doc, "Evolución de métricas (30 días)")
    others = payload.get("other_metrics") or []
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

    # Último / próximo partido
    match = payload.get("last_match")
    title = "Último partido" if (match and match.get("is_past")) else "Próximo partido"
    _docx.section_heading(doc, title)
    _render_match(doc, match)

    return _docx.to_bytes(doc)


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
