"""Team report as an editable Word document.

Mirrors `dashboards/pdf/team_report` (landscape) but, like the player
reports, leads with an LLM **narrative analysis** (squad-level resumen /
hallazgos / objetivos) on top of the executive summary and the configured
TeamReportLayout — each widget's chart reused from the PDF renderers and
its data rendered as a native Word table.

The narrative (the expensive, non-deterministic part) is content-addressed
via `TeamReportSnapshot`: same resolved data + filters + agent ⇒ same
report, generated once."""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.models import Category, Department, Player

from . import _docx
from dashboards.models import TeamReportLayout
from dashboards.team_aggregation import resolve_team_widget
from dashboards.pdf.team_report import _format_period

_DISPLAY_TZ = ZoneInfo("America/Santiago")
_TEAM_RENDER_VERSION = 1

_STATUS_LABELS = {
    "available": "Disponible",
    "injured": "Lesionado",
    "recovery": "Recuperación",
    "reintegration": "Return to Train",
}


def render_team_docx(
    *,
    department: Department,
    category: Category,
    position_id: UUID | None = None,
    player_ids: list[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    event_id: UUID | None = None,
) -> bytes:
    """Download entry point for the team report (.docx). Resolves the
    department's InsightAgent, builds the squad data payload, reuses the
    cached narrative + Word file for that data+filter signature when present,
    otherwise generates the narrative once, renders, persists, and returns."""
    from django.conf import settings

    from dashboards.pdf.narrative import generate_player_narrative, resolve_insight_agent
    from dashboards.pdf.report_cache import (
        get_saved_team_file, get_saved_team_narrative, report_signature, save_team_file,
    )

    layout = (
        TeamReportLayout.objects
        .filter(department=department, category=category, scope="period", is_active=True)
        .prefetch_related("sections__widgets__data_sources")
        .first()
    )

    # Resolve every widget ONCE; reused for the narrative payload + rendering.
    resolved: list[tuple[object, str | None, dict]] = []
    if layout is not None:
        for section in layout.sections.all():
            for w in section.widgets.all():
                payload = resolve_team_widget(
                    w, category,
                    position_id=position_id, player_ids=player_ids,
                    date_from=date_from, date_to=date_to, event_id=event_id,
                )
                resolved.append((w, section.title, payload))

    exec_stats, by_status = _exec_data(department, category, position_id, player_ids)

    # Full payload → signature (accurate dedup); trimmed copy → LLM prompt.
    full_payload = _team_payload(
        department, category, exec_stats, resolved,
        filters={"position_id": str(position_id) if position_id else None,
                 "player_ids": sorted(str(p) for p in (player_ids or [])),
                 "date_from": str(date_from) if date_from else None,
                 "date_to": str(date_to) if date_to else None,
                 "event_id": str(event_id) if event_id else None},
    )

    agent = resolve_insight_agent(department.slug)
    model = ((agent.model or "").strip() if agent else "") or getattr(
        settings, "ANTHROPIC_MODEL", "claude-opus-4-8"
    )
    fingerprint = agent.config_fingerprint() if agent else "builtin"
    signature = report_signature(
        full_payload, model=model, kind=f"team:{department.slug}",
        render_version=_TEAM_RENDER_VERSION, agent_fingerprint=fingerprint,
    )

    saved = get_saved_team_file(department, category, signature)
    if saved is not None:
        return saved

    narrative = get_saved_team_narrative(department, category, signature)
    if narrative is None:
        narrative = generate_player_narrative(_trim(full_payload), agent=agent)

    docx_bytes = _render(
        department, category, exec_stats, by_status, resolved, narrative,
        layout_present=layout is not None,
        period_label=_format_period(date_from, date_to, event_id, layout),
    )
    try:
        save_team_file(department, category, signature, docx_bytes,
                       model=model, narrative=narrative)
    except Exception:  # noqa: BLE001 — persistence is best-effort
        import logging
        logging.getLogger(__name__).exception("Failed to persist team .docx snapshot.")
    return docx_bytes


def _render(department, category, exec_stats, by_status, resolved, narrative,
            *, layout_present, period_label) -> bytes:
    from dashboards.pdf.scaffold import logo_image_for_club

    doc = _docx.new_document(landscape=True)
    width = _docx.LANDSCAPE_CONTENT_CM

    _docx.report_header(
        doc,
        club_name=category.club.name if category else "",
        club_logo=_safe_logo(logo_image_for_club, category.club if category else None),
        title=f"Reporte de {department.name}",
        subtitle="Vista de equipo",
        meta=[
            ("Categoría", category.name if category else ""),
            ("Período", period_label),
            ("Generado", timezone.now().astimezone(_DISPLAY_TZ).strftime("%d/%m/%Y · %H:%M")),
        ],
    )

    # Squad-level narrative analysis FIRST (text + analysis, not just numbers).
    if narrative:
        _docx.section_heading(doc, "Análisis del equipo")
        _docx.add_narrative(doc, narrative)

    # Executive summary (availability + active-alert counts).
    _docx.section_heading(doc, "Resumen ejecutivo")
    _docx.add_table(
        doc,
        ["Plantel", "Disponibles", "No disponibles", "Críticas", "Advertencias"],
        [[exec_stats["roster"], exec_stats["available"], exec_stats["not_available"],
          exec_stats["crit"], exec_stats["warn"]]],
        width_cm=width, numeric_from=0,
    )
    rows = [
        [_STATUS_LABELS.get(st, st.title()), str(len(names)), ", ".join(sorted(names))]
        for st, names in sorted(by_status.items())
    ]
    if rows:
        _docx.add_table(doc, ["Estado", "N", "Jugadores"], rows, width_cm=width, numeric_from=1)

    if not layout_present:
        _docx.body(
            doc,
            f"No hay un TeamReportLayout activo para esta categoría en {department.name}.",
            muted=True,
        )
        return _docx.to_bytes(doc)

    # Widget sections (charts reused from PDF renderers + native data tables).
    last_section = object()
    for w, section_title, payload in resolved:
        if section_title != last_section:
            if section_title:
                _docx.section_heading(doc, section_title)
            last_section = section_title
        _docx.render_widget(doc, w, payload, width_cm=width)

    return _docx.to_bytes(doc)


def _exec_data(department, category, position_id, player_ids):
    from goals.models import Alert, AlertStatus
    from dashboards.pdf.executive_summary import _filter_alerts_by_department

    roster_qs = Player.objects.filter(category=category, is_active=True)
    if position_id is not None:
        roster_qs = roster_qs.filter(position_id=position_id)
    if player_ids:
        roster_qs = roster_qs.filter(id__in=player_ids)
    roster = list(roster_qs)

    available = sum(1 for p in roster if p.status == "available")
    alerts = list(Alert.objects.filter(player__in=roster, status=AlertStatus.ACTIVE))
    dept_alerts = _filter_alerts_by_department(alerts, department)

    by_status: dict[str, list[str]] = {}
    for p in roster:
        by_status.setdefault(p.status, []).append(f"{p.first_name} {p.last_name}".strip())

    stats = {
        "roster": len(roster),
        "available": available,
        "not_available": len(roster) - available,
        "crit": sum(1 for a in dept_alerts if a.severity == "critical"),
        "warn": sum(1 for a in dept_alerts if a.severity == "warning"),
    }
    return stats, by_status


def _team_payload(department, category, exec_stats, resolved, *, filters) -> dict:
    """Squad payload for the narrative + signature: department/category,
    the executive stats, the filter identity, and every resolved widget's
    data (the same data the report renders)."""
    return {
        "scope": "team",
        "report_type": "Reporte de equipo",
        "department": department.name,
        "category": category.name if category else None,
        "filters": filters,
        "executive": exec_stats,
        "items": [
            {"title": getattr(w, "title", ""), "chart_type": ct_payload.get("chart_type") or getattr(w, "chart_type", ""),
             "data": ct_payload}
            for (w, _section, ct_payload) in resolved
            if not ct_payload.get("empty")
        ],
    }


def _trim(obj, cap: int = 20):
    """Deep copy with every list capped at `cap` elements — keeps the LLM
    prompt bounded for large squad tables without affecting the (full-data)
    signature computed separately."""
    def _walk(v):
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v[:cap]]
        return v
    return _walk(copy.deepcopy(obj))


def _safe_logo(fn, club):
    if club is None:
        return None
    try:
        return fn(club)
    except Exception:  # noqa: BLE001
        return None
