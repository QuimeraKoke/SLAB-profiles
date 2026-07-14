"""Per-player department report as an editable Word document.

Same data + narrative as `dashboards/pdf/player_report`, rendered to .docx:
the agent's "Análisis del período", médico injury history, físico weekly-load
evolution, the reference/percentile block, and the department's configured
widget layout (charts reused from the PDF renderers, data as Word tables)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.models import Department, Player

from . import _docx
from dashboards.aggregation import resolve_widget
from dashboards.models import DepartmentLayout
from dashboards.pdf.charts._mpl import capture_docx_figures
from dashboards.pdf.player_report import (
    _DEPT_RENDER_VERSION,
    _format_period,
    _weekly_load_chart,
    build_department_payload,
)

_DISPLAY_TZ = ZoneInfo("America/Santiago")
_RECENT_CLOSED_LIMIT = 5


def render_or_get_player_docx(
    *,
    player: Player,
    department: Department,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> bytes:
    """Download entry point for the per-department report (.docx). Reuses
    the cached narrative for this data+agent signature when present."""
    from django.conf import settings

    from dashboards.pdf.narrative import generate_player_narrative, resolve_insight_agent
    from dashboards.pdf.report_cache import (
        get_saved_file, get_saved_narrative, report_signature, save_file,
    )

    agent = resolve_insight_agent(department.slug)
    model = ((agent.model or "").strip() if agent else "") or getattr(
        settings, "ANTHROPIC_MODEL", "claude-opus-4-8"
    )
    fingerprint = agent.config_fingerprint() if agent else "builtin"

    payload = build_department_payload(player, department, date_from, date_to)
    kind = f"dept:{department.slug}"
    signature = report_signature(
        payload, model=model, kind=kind,
        render_version=_DEPT_RENDER_VERSION, agent_fingerprint=fingerprint,
    )

    saved = get_saved_file(player, kind, signature, fmt="docx")
    if saved is not None:
        return saved

    narrative = get_saved_narrative(player, kind, signature)
    if narrative is None:
        narrative = generate_player_narrative(payload, agent=agent)

    docx_bytes = _render(player, department, payload, narrative, date_from, date_to)
    try:
        save_file(player, kind, signature, docx_bytes,
                  fmt="docx", model=model, narrative=narrative)
    except Exception:  # noqa: BLE001 — persistence is best-effort
        import logging
        logging.getLogger(__name__).exception("Failed to persist department .docx snapshot.")
    return docx_bytes


def _render(player, department, payload, narrative, date_from, date_to) -> bytes:
    from dashboards.pdf.scaffold import logo_image_for_club

    doc = _docx.new_document()
    width = _docx.PORTRAIT_CONTENT_CM
    category = player.category
    club = category.club if category else None

    _docx.report_header(
        doc,
        club_name=club.name if club else "",
        club_logo=_safe_logo(logo_image_for_club, club),
        title=f"{player.first_name} {player.last_name}".strip(),
        subtitle=f"Reporte de {department.name}",
        meta=[
            ("Categoría", category.name if category else ""),
            ("Período", _format_period(date_from, date_to)),
            ("Generado", timezone.now().astimezone(_DISPLAY_TZ).strftime("%d/%m/%Y · %H:%M")),
        ],
    )

    # Análisis del período (agent narrative).
    if narrative:
        _docx.section_heading(doc, "Análisis del período")
        _docx.add_narrative(doc, narrative)

    # Médico: injury history first — the doctor's primary question.
    if department.slug == "medico":
        _injury_block(doc, player, width)

    # Físico: weekly chronic-load evolution (reuse the PDF chart).
    evolution = payload.get("weekly_load_evolution") or []
    if evolution:
        _docx.section_heading(doc, "Evolución de carga semanal")
        any_chart = False
        for concept in evolution:
            with capture_docx_figures() as figs:
                _weekly_load_chart(concept)
            if figs:
                any_chart = True
                unit = concept.get("unit") or ""
                _docx.body(
                    doc,
                    f"{concept.get('label') or concept.get('key')} "
                    f"(objetivo {concept.get('min')}–{concept.get('max')} {unit})",
                )
                _docx.add_chart_images(doc, list(figs), max_width_cm=width)
        if not any_chart:
            _docx.body(doc, "Sin histórico suficiente.", muted=True)

    # Reference / percentile block.
    _references_block(doc, payload.get("references") or [], width)

    # Configured widget layout.
    layout = (
        DepartmentLayout.objects
        .filter(department=department, category=category, is_active=True)
        .prefetch_related("sections__widgets__data_sources")
        .first()
    )
    if layout is not None:
        for section in layout.sections.all():
            widgets = list(section.widgets.all())
            if not widgets:
                continue
            if section.title:
                _docx.section_heading(doc, section.title)
            for w in widgets:
                payload_w = resolve_widget(w, player.id, date_from=date_from, date_to=date_to)
                _docx.render_widget(doc, w, payload_w, width_cm=width)

    return _docx.to_bytes(doc)


def _references_block(doc, references: list, width: float) -> None:
    if not references:
        return
    _docx.section_heading(doc, "Referencias y percentiles")
    rows = []
    for r in references:
        refs = r.get("references") or {}
        band = refs.get("current_band") or "—"
        sq = refs.get("squad_percentile") or {}
        squad = f"{sq['percentile']}%" if sq.get("percentile") is not None else "—"
        ext = refs.get("external") or []
        ext_label = "—"
        if ext:
            e = ext[0]
            comp = e.get("comparison") or {}
            pct = comp.get("percentile")
            ext_label = e.get("source") or "—"
            if pct is not None:
                ext_label = f"{ext_label} · p{pct}"
        rows.append([
            _docx._with_unit(r.get("field"), r.get("unit")),
            _docx._num(r.get("value")),
            band, squad, ext_label,
        ])
    _docx.add_table(
        doc, ["Métrica", "Valor", "Banda interna", "Percentil plantel", "Norma externa"],
        rows, width_cm=width, numeric_from=1,
    )


def _injury_block(doc, player: Player, width: float) -> None:
    from exams.models import Episode

    episodes = list(
        Episode.objects
        .filter(player=player, template__slug="lesiones")
        .order_by("-status", "-started_at")
    )
    if not episodes:
        return
    _docx.section_heading(doc, "Lesiones")
    open_eps = [e for e in episodes if e.status == Episode.STATUS_OPEN]
    closed_eps = [e for e in episodes if e.status == Episode.STATUS_CLOSED]

    if open_eps:
        _docx.body(doc, f"{len(open_eps)} episodio(s) abierto(s) en seguimiento.", muted=True)
        _docx.add_table(
            doc, ["Lesión", "Etapa", "Inicio", "Días activos"],
            [[e.title or "(sin título)", (e.stage or "—").capitalize(),
              _d(e.started_at), str(_days(e.started_at, _now()))] for e in open_eps],
            width_cm=width, numeric_from=3,
        )
    else:
        last_closed = closed_eps[0] if closed_eps else None
        if last_closed and last_closed.ended_at:
            _docx.body(doc, f"Disponible. Última lesión cerrada hace "
                            f"{_days(last_closed.ended_at, _now())} día(s).")
        else:
            _docx.body(doc, "Disponible. Sin lesiones activas registradas.")

    recent = closed_eps[:_RECENT_CLOSED_LIMIT]
    if recent:
        _docx.body(doc, f"Historial reciente ({len(recent)} de {len(closed_eps)} cerradas)", muted=True)
        _docx.add_table(
            doc, ["Lesión", "Inicio", "Cierre", "Duración"],
            [[e.title or "(sin título)", _d(e.started_at), _d(e.ended_at),
              (f"{_days(e.started_at, e.ended_at)} días" if e.started_at and e.ended_at else "—")]
             for e in recent],
            width_cm=width, numeric_from=1,
        )


def _now():
    return timezone.now()


def _days(start, end) -> int:
    if not start or not end:
        return 0
    return max(0, (end - start).days)


def _d(value) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def _safe_logo(fn, club):
    if club is None:
        return None
    try:
        return fn(club)
    except Exception:  # noqa: BLE001
        return None
