"""Player triage PDF — the printable form of the Resumen tab.

Same data source as the `/players/{id}/triage` JSON endpoint
(`api.triage.build_triage_payload`); this module just renders it for
print. Portrait A4, designed to fit a one-player summary on a single
page in the typical case (few alerts, ≤ 8 tracked metrics).

Sections mirror the UI exactly so a coach handed the print and a coach
looking at the screen are reading the same artifact. See
`docs/UX_AUDIT.md` for the design rationale.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from api.player_analysis import build_player_analysis
from api.triage import build_triage_payload
from core.models import Player

from .narrative import generate_player_narrative
from .scaffold import (
    COLOR_CRIT,
    COLOR_FICHA_NAVY,
    COLOR_FICHA_RED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_RULE,
    COLOR_WARN,
    build_pdf,
    logo_image_for_club,
    styles,
)


_DISPLAY_TZ = ZoneInfo("America/Santiago")

# Content width inside the A4 portrait page margins.
_CONTENT_W = 18.2 * cm

# Report kind + render-format version for the content-addressed cache.
# Bump RENDER_VERSION whenever the rendered layout changes, so previously
# saved snapshots are superseded without needing a data change.
_REPORT_KIND = "triage"
# v2: added the "Resumen de temporada" 3-card block + jersey number, mirroring
# the on-screen Resumen S-LAB summary. `_REPORT_KIND`/`RENDER_VERSION` now back
# the WEB Resumen's light narrative cache (get_or_build_triage_narrative) only.
RENDER_VERSION = 2

# The downloadable per-player Resumen REPORT is the analytical
# Resumen/Análisis/Conclusiones document — cached under its own kind so it
# never collides with the web's light narrative. Bump the render version when
# the report layout changes.
_ANALYSIS_KIND = "resumen"
_ANALYSIS_RENDER_VERSION = 2


# ─── Public entry points ──────────────────────────────────────────────


def report_inputs(player: Player):
    """Shared inputs for the analytical Resumen report (PDF + Word): the agent,
    model, content signature, and the triage + analysis payloads. Both
    renderers use this so they hit the SAME content-addressed cache (kind
    `resumen`) and share the analysis narrative."""
    from django.conf import settings

    from .narrative import resolve_insight_agent
    from .report_cache import report_signature

    agent = resolve_insight_agent(_ANALYSIS_KIND) or resolve_insight_agent(_REPORT_KIND)
    model = (
        (agent.model or "").strip() if agent else ""
    ) or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-7")
    fingerprint = agent.config_fingerprint() if agent else "builtin"

    triage = build_triage_payload(player)
    analysis = build_player_analysis(player)
    payload = {"triage": triage, "analysis": analysis}
    signature = report_signature(
        payload, model=model, kind=_ANALYSIS_KIND,
        render_version=_ANALYSIS_RENDER_VERSION, agent_fingerprint=fingerprint,
    )
    return agent, model, signature, triage, analysis, payload


def render_or_get_triage_pdf(player: Player) -> bytes:
    """Download entry point. Returns the saved PDF for the player's current
    data signature if one exists (no LLM, no re-render); otherwise renders
    once, persists it, and returns it. Generation never fails the download —
    a storage error just falls back to a fresh render."""
    from .narrative import generate_player_analysis_narrative
    from .report_cache import get_saved_file, get_saved_narrative, save_file

    agent, model, signature, triage, analysis, payload = report_inputs(player)

    saved = get_saved_file(player, _ANALYSIS_KIND, signature, fmt="pdf")
    if saved is not None:
        return saved

    narrative = get_saved_narrative(player, _ANALYSIS_KIND, signature)
    if narrative is None:
        narrative = generate_player_analysis_narrative(payload, agent=agent)
    pdf_bytes = _render_from_payload(triage, analysis, player, narrative)
    try:
        save_file(
            player, _ANALYSIS_KIND, signature, pdf_bytes,
            fmt="pdf", model=model, narrative=narrative,
        )
    except Exception:  # noqa: BLE001 — persistence is best-effort, never block the download
        import logging
        logging.getLogger(__name__).exception("Failed to persist report snapshot.")
    return pdf_bytes


def get_or_build_triage_narrative(player: Player) -> dict | None:
    """Cached agent narrative for the WEB Resumen (estado/preocupaciones/
    recomendaciones). Shares the exact content-addressed cache as the PDF —
    same `kind`/signature — so the narrative is generated at most once per
    data signature regardless of whether the web or the PDF asks first, and a
    narrative made here is reused by a later PDF download (and vice versa).

    Returns the `{resumen, hallazgos, objetivos}` dict, or None if the LLM is
    unavailable/failed (the caller renders the stat cards alone). Persistence
    is best-effort — a storage hiccup never fails the request."""
    import logging

    from django.conf import settings

    from .narrative import resolve_insight_agent
    from .report_cache import get_saved_narrative, report_signature

    agent = resolve_insight_agent(_REPORT_KIND)
    model = (
        (agent.model or "").strip() if agent else ""
    ) or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-7")
    fingerprint = agent.config_fingerprint() if agent else "builtin"

    payload = build_triage_payload(player)
    signature = report_signature(
        payload, model=model, kind=_REPORT_KIND,
        render_version=RENDER_VERSION, agent_fingerprint=fingerprint,
    )

    cached = get_saved_narrative(player, _REPORT_KIND, signature)
    if cached:
        return cached

    narrative = generate_player_narrative(payload, agent=agent)
    if narrative:
        # Persist a narrative-only snapshot (no rendered file) so the web and
        # the PDF share it. Mirrors save_file's get_or_create, sans bytes.
        try:
            from dashboards.models import PlayerReportSnapshot

            PlayerReportSnapshot.objects.get_or_create(
                player=player, kind=_REPORT_KIND, data_hash=signature,
                defaults={"model": model, "narrative": narrative},
            )
        except Exception:  # noqa: BLE001 — caching is best-effort, never block.
            logging.getLogger(__name__).exception("Failed to cache web narrative.")
    return narrative


def render_triage_pdf(player: Player) -> bytes:
    """Always render a fresh PDF (builds payloads + narrative). Bypasses the
    saved-snapshot cache — use for tests/previews; the download path uses
    `render_or_get_triage_pdf`."""
    from .narrative import generate_player_analysis_narrative

    _agent, _model, _sig, triage, analysis, payload = report_inputs(player)
    narrative = generate_player_analysis_narrative(payload, agent=_agent)
    return _render_from_payload(triage, analysis, player, narrative)


# ─── Layout ───────────────────────────────────────────────────────────


def _render_from_payload(triage: dict, analysis: dict, player: Player, narrative: dict | None) -> bytes:
    """Analytical Resumen report: Resumen → Análisis → Conclusiones. The agent
    narrative ({resumen, analisis, conclusiones}) interprets the deterministic
    `analysis` blocks (match-load trends + correlations, ACWR/microcycles,
    position context), which are rendered as tables/charts alongside it."""
    s = styles()
    fs = _ficha_styles()
    narrative = narrative or {}

    club = player.category.club if player.category else None
    cover = {
        "title": f"Resumen — {player.first_name} {player.last_name}",
        "club_name": club.name if club else "",
    }

    flow: list = []

    # Ficha identity band — club lockup + player name + bio + status badge.
    flow.extend(_ficha_header(player, club, triage, fs))

    # ── RESUMEN ──────────────────────────────────────────────────────────
    flow.extend(_ficha_section_header("Resumen", fs))
    if narrative.get("resumen"):
        flow.append(Paragraph(_esc(narrative["resumen"]), fs["narrative"]))
    flow.extend(_headline_chips(analysis, fs))
    flow.extend(_season_summary_block(player, fs))

    # ── ANÁLISIS ─────────────────────────────────────────────────────────
    flow.extend(_ficha_section_header("Análisis", fs))
    for b in narrative.get("analisis") or []:
        flow.append(Paragraph(f"•  {_esc(b)}", fs["bullet"]))
    flow.append(Spacer(1, 3 * mm))

    flow.extend(_match_load_block(analysis.get("match_load") or {}, s, fs))
    flow.extend(_training_block(analysis.get("training") or {}, s, fs))
    flow.extend(_position_block(analysis.get("position") or {}, s, fs))

    # Supporting evidence (the timeline + current flags), under Análisis.
    flow.extend(_subsection(
        "Evolución de métricas (30 días)",
        _metrics_evolution_block(triage["other_metrics"], s, fs), fs,
    ))
    flow.extend(_subsection(
        "Alertas activas", _alerts_block(triage["alerts"], s), fs,
    ))
    match_title = (
        "Último partido"
        if (triage["last_match"] and triage["last_match"]["is_past"])
        else "Próximo partido"
    )
    flow.extend(_subsection(
        match_title, _last_match_block(triage["last_match"], s), fs,
    ))

    # ── CONCLUSIONES ─────────────────────────────────────────────────────
    flow.extend(_ficha_section_header("Conclusiones", fs))
    conclusiones = narrative.get("conclusiones") or []
    if conclusiones:
        for c in conclusiones:
            flow.append(Paragraph(f"•  {_esc(c)}", fs["bullet"]))
    else:
        flow.append(Paragraph(
            "<i>Sin conclusiones automáticas (IA no disponible).</i>", s["body_muted"],
        ))

    return build_pdf(orientation="portrait", cover=cover, flowables=flow)


# ─── Analytical blocks ────────────────────────────────────────────────

_ACWR_COLORS = {
    "ok": COLOR_OK, "low": COLOR_WARN, "high": COLOR_WARN, "danger": COLOR_CRIT,
}


def _subsection(title: str, block: list, fs: dict) -> list:
    """A lighter sub-block under a main section (navy bold, no red rule)."""
    return [Spacer(1, 2 * mm), Paragraph(_esc(title), fs["subhead"]), *block, Spacer(1, 3 * mm)]


def _data_table(header: list[str], rows: list[list], col_widths: list, numeric_from: int = 1):
    data = [header, *rows]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (numeric_from, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (numeric_from - 1, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, COLOR_FICHA_NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    tbl.setStyle(TableStyle(style))
    return tbl


_TREND_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


def _headline_chips(analysis: dict, fs: dict) -> list:
    """ACWR badge line under the Resumen — the one-glance load-risk indicator."""
    acwr = ((analysis.get("training") or {}).get("acwr")) or None
    if not acwr:
        return []
    color = _ACWR_COLORS.get(acwr["band"], COLOR_MUTED)
    chip = Table(
        [[Paragraph(f"ACWR {_num(acwr['value'])}", fs["badge"]),
          Paragraph(_esc(acwr["label"]), fs["cardRow"])]],
        colWidths=[2.6 * cm, _CONTENT_W - 2.6 * cm], hAlign="LEFT",
    )
    chip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 8), ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [Spacer(1, 2 * mm), chip, Spacer(1, 2 * mm)]


def _match_load_block(match_load: dict, s: dict, fs: dict) -> list:
    n = match_load.get("n_matches") or 0
    if n < 2:
        return _subsection(
            "Carga de partido",
            [Paragraph("<i>Sin suficientes partidos con GPS para analizar la tendencia.</i>", s["body_muted"])],
            fs,
        )
    out: list = [Spacer(1, 2 * mm), Paragraph("Carga de partido — tendencia y correlaciones", fs["subhead"])]

    primary = match_load.get("primary")
    if primary and primary.get("trend"):
        tr = primary["trend"]
        arrow = _TREND_ARROW.get(tr["direction"], "")
        pct = f" ({tr['pct_change']:+.1f}%)" if tr.get("pct_change") is not None else ""
        comov = ", ".join(
            f"{_esc(c['label'])} (r={_num(c['r'])})" for c in (primary.get("comovers") or [])
        )
        line = f"<b>{_esc(primary['label'])}</b>: tendencia {arrow}{pct} sobre {n} partidos."
        if comov:
            line += f" Acompañan: {comov}."
        out.append(Paragraph(line, fs["cardRow"]))

    corrs = match_load.get("correlations") or []
    if corrs:
        out.append(Spacer(1, 1.5 * mm))
        out.append(Paragraph("Variables que co-mueven (Pearson r):", fs["cardTitle"]))
        # Plain Table cells render literally (no mini-XML), so pass raw labels.
        rows = [[c["a_label"], c["b_label"], _num(c["r"]), str(c["n"])] for c in corrs]
        out.append(_data_table(
            ["Variable A", "Variable B", "r", "n"], rows,
            [6.0 * cm, 6.0 * cm, _CONTENT_W - 12 * cm - 1.6 * cm, 1.6 * cm], numeric_from=2,
        ))
    out.append(Spacer(1, 3 * mm))
    return out


def _training_block(training: dict, s: dict, fs: dict) -> list:
    out: list = [Spacer(1, 2 * mm), Paragraph("Carga de entrenamiento — ACWR y microciclos", fs["subhead"])]
    has = False

    acwr = training.get("acwr")
    if acwr:
        has = True
        out.append(Paragraph(
            f"<b>ACWR {_num(acwr['value'])}</b> — {_esc(acwr['label'])} "
            "<font color='#6b7280'>(agudo 7d ÷ crónico 28d-semanal)</font>.",
            fs["cardRow"],
        ))

    micro = training.get("microcycle")
    if micro:
        has = True
        pct = f" ({micro['pct_change']:+.1f}%)" if micro.get("pct_change") is not None else ""
        out.append(Paragraph(
            f"<b>Microciclo actual</b> ({_esc(micro['current_week'])}): "
            f"{_num(micro['current_load'])} u.a. vs. promedio previo "
            f"{_num(micro['prior_avg_load'])} u.a.{pct}.",
            fs["cardRow"],
        ))

    weekly = training.get("weekly") or []
    if weekly:
        has = True
        out.append(Spacer(1, 1.5 * mm))
        rows = [[_esc(w["week"]), f"{_num(w['dist'])}", f"{_num(w['load'])}", str(w["sessions"])] for w in weekly]
        out.append(_data_table(
            ["Semana", "Distancia (m)", "Player Load", "Sesiones"], rows,
            [4.5 * cm, 5.0 * cm, 5.0 * cm, _CONTENT_W - 14.5 * cm], numeric_from=1,
        ))

    if not has:
        out.append(Paragraph("<i>Sin datos de entrenamiento suficientes.</i>", s["body_muted"]))
    out.append(Spacer(1, 3 * mm))
    return out


def _position_block(position: dict, s: dict, fs: dict) -> list:
    label = position.get("position_label")
    metrics = position.get("metrics") or []
    title = f"Contexto por posición — {_esc(label)}" if label else "Contexto por posición"
    out: list = [Spacer(1, 2 * mm), Paragraph(title, fs["subhead"])]
    if not metrics:
        out.append(Paragraph(
            "<i>Sin pares de la misma posición suficientes para comparar.</i>", s["body_muted"],
        ))
        out.append(Spacer(1, 3 * mm))
        return out
    rows = [
        [m["label"], _num(m["value"]), _num(m["position_avg"]), f"{m['percentile']}", str(m["n"])]
        for m in metrics
    ]
    out.append(_data_table(
        ["Métrica", "Jugador", "Prom. posición", "Percentil", "n"], rows,
        [6.0 * cm, 3.2 * cm, 3.8 * cm, _CONTENT_W - 13 * cm - 1.6 * cm, 1.6 * cm], numeric_from=1,
    ))
    out.append(Spacer(1, 3 * mm))
    return out


# ─── Ficha identity + narrative ───────────────────────────────────────


# Player.status → (badge label, badge color). Mirrors the ficha's status
# chip ("REINTEGRO / SEGUIMIENTO", etc.).
_STATUS_BADGE = {
    Player.STATUS_INJURED: ("LESIONADO", COLOR_CRIT),
    Player.STATUS_RECOVERY: ("EN RECUPERACIÓN", COLOR_WARN),
    Player.STATUS_REINTEGRATION: ("REINTEGRO / SEGUIMIENTO", COLOR_FICHA_NAVY),
    Player.STATUS_AVAILABLE: ("DISPONIBLE", COLOR_OK),
}


def _ficha_header(player: Player, club, payload: dict, fs: dict) -> list:
    out: list = []

    # Club lockup: small logo (left) above a navy rule, à la the ficha header.
    logo = logo_image_for_club(club) if club else None
    if logo is not None:
        try:
            img = Image(logo, width=2.6 * cm, height=1.3 * cm, kind="proportional")
            img.hAlign = "LEFT"
            out.append(img)
        except Exception:  # noqa: BLE001 — a bad logo must not kill the PDF
            pass
    out.append(HRFlowable(
        width="100%", thickness=2, color=COLOR_FICHA_NAVY,
        spaceBefore=4, spaceAfter=8,
    ))

    # Player name.
    out.append(Paragraph(
        _esc(f"{player.first_name} {player.last_name}".strip()), fs["name"],
    ))

    # Bio line — only the facts we actually have.
    from api.player_summary import player_squad_number

    bio_bits: list[str] = []
    number = player_squad_number(player)
    if number:
        bio_bits.append(f"#{_esc(number)}")
    if player.age is not None:
        bio_bits.append(f"{player.age} años")
    if player.current_height_cm:
        bio_bits.append(f"{_num(player.current_height_cm)} cm")
    if player.current_weight_kg:
        bio_bits.append(f"{_num(player.current_weight_kg)} kg")
    if player.position:
        bio_bits.append(_esc(player.position.name))
    if player.category:
        bio_bits.append(_esc(player.category.name))
    if bio_bits:
        out.append(Paragraph("  ·  ".join(bio_bits), fs["bio"]))

    # Status badge (chip with a solid fill).
    label, color = _STATUS_BADGE.get(player.status, (player.status.upper(), COLOR_MUTED))
    badge = Table([[Paragraph(label, fs["badge"])]], hAlign="LEFT")
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    out.append(Spacer(1, 3 * mm))
    out.append(badge)

    # Generated-at caption.
    gen = payload["generated_at"].astimezone(_DISPLAY_TZ)
    out.append(Spacer(1, 2 * mm))
    out.append(Paragraph(
        f"Generado el {gen.strftime('%d/%m/%Y · %H:%M')}", fs["caption"],
    ))
    out.append(Spacer(1, 4 * mm))
    return out


def _narrative_block(narrative: dict, s: dict, fs: dict) -> list:
    out: list = []

    resumen = narrative.get("resumen") or ""
    if resumen:
        out.extend(_ficha_section_header("Resumen", fs))
        out.append(Paragraph(_esc(resumen), fs["narrative"]))

    hallazgos = narrative.get("hallazgos") or []
    if hallazgos:
        out.extend(_ficha_section_header("Hallazgos destacados", fs))
        for h in hallazgos:
            # Plain "• " prefix — not an &nbsp; entity (reportlab's mini-XML
            # parser doesn't define it). Hanging indent comes from leftIndent.
            out.append(Paragraph(f"•  {_esc(h)}", fs["bullet"]))

    objetivos = narrative.get("objetivos") or []
    if objetivos:
        out.extend(_ficha_section_header("Objetivos de trabajo", fs))
        for o in objetivos:
            foco = _esc(o.get("foco") or "")
            estado = _esc(o.get("estado_actual") or "")
            estrategia = _esc(o.get("estrategia") or "")
            line = f"<b>{foco}</b>" if foco else ""
            if estado:
                line += f": <font color='#6b7280'>{estado}</font>"
            if estrategia:
                line += f" → <b>{estrategia}</b>"
            if line:
                out.append(Paragraph(line, fs["objetivo"]))

    out.append(Spacer(1, 2 * mm))
    return out


def _ficha_section(title: str, block: list, fs: dict) -> list:
    return [*_ficha_section_header(title, fs), *block, Spacer(1, 5 * mm)]


def _ficha_section_header(title: str, fs: dict) -> list:
    return [
        Spacer(1, 2 * mm),
        Paragraph(_esc(title).upper(), fs["section"]),
        HRFlowable(
            width="100%", thickness=1.2, color=COLOR_FICHA_RED,
            spaceBefore=1, spaceAfter=5,
        ),
    ]


def _ficha_styles() -> dict:
    return {
        "name": ParagraphStyle(
            "ficha_name", fontName="Helvetica-Bold", fontSize=19,
            textColor=COLOR_FICHA_NAVY, leading=22, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "bio": ParagraphStyle(
            "ficha_bio", fontName="Helvetica", fontSize=9.5,
            textColor=colors.HexColor("#374151"), leading=13, alignment=TA_LEFT,
        ),
        "badge": ParagraphStyle(
            "ficha_badge", fontName="Helvetica-Bold", fontSize=8,
            textColor=colors.white, leading=10, alignment=TA_LEFT,
        ),
        "caption": ParagraphStyle(
            "ficha_caption", fontName="Helvetica", fontSize=7.5,
            textColor=COLOR_MUTED, leading=10, alignment=TA_LEFT,
        ),
        "section": ParagraphStyle(
            "ficha_section", fontName="Helvetica-Bold", fontSize=11,
            textColor=COLOR_FICHA_NAVY, leading=13, alignment=TA_LEFT,
            spaceAfter=1,
        ),
        "narrative": ParagraphStyle(
            "ficha_narrative", fontName="Helvetica", fontSize=10,
            textColor=colors.HexColor("#1f2937"), leading=15, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "ficha_bullet", fontName="Helvetica", fontSize=9.5,
            textColor=colors.HexColor("#1f2937"), leading=14, alignment=TA_LEFT,
            leftIndent=4, spaceAfter=1,
        ),
        "objetivo": ParagraphStyle(
            "ficha_objetivo", fontName="Helvetica", fontSize=9.5,
            textColor=colors.HexColor("#1f2937"), leading=14, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "cardTitle": ParagraphStyle(
            "ficha_card_title", fontName="Helvetica-Bold", fontSize=8,
            textColor=COLOR_MUTED, leading=11, alignment=TA_LEFT, spaceAfter=4,
        ),
        "cardRow": ParagraphStyle(
            "ficha_card_row", fontName="Helvetica", fontSize=9,
            textColor=colors.HexColor("#1f2937"), leading=13, alignment=TA_LEFT,
            spaceAfter=1,
        ),
        "subhead": ParagraphStyle(
            "ficha_subhead", fontName="Helvetica-Bold", fontSize=9.5,
            textColor=COLOR_FICHA_NAVY, leading=12, alignment=TA_LEFT,
            spaceBefore=2, spaceAfter=3,
        ),
    }


def _season_summary_block(player: Player, fs: dict) -> list:
    """The 3-card season block (estadísticas de juego · rendimiento físico ·
    reporte médico), mirroring the on-screen Resumen S-LAB summary. Rendered as
    a single 3-column table so the cards sit side by side. Reuses the same
    `build_player_season_summary` aggregation as the web."""
    from api.player_summary import build_player_season_summary

    data = build_player_season_summary(player)
    est = data["estadisticas"]
    gps = data["rendimiento_fisico"]
    med = data["reporte_medico"]

    def _m(v):  # meters
        return "—" if v is None else f"{round(v):,} m".replace(",", ".")

    def _i(v):  # integer
        return "—" if v is None else f"{round(v):,}".replace(",", ".")

    def _d1(v):  # one decimal
        return "—" if v is None else f"{v:.1f}"

    def card(title: str, rows: list[tuple[str, object]]) -> list:
        cell: list = [Paragraph(_esc(title).upper(), fs["cardTitle"])]
        for label, val in rows:
            cell.append(Paragraph(f"{_esc(label)}: <b>{_esc(str(val))}</b>", fs["cardRow"]))
        return cell

    est_rows = [
        ("Partidos jugados", est["partidos_jugados"]),
        ("Minutos totales", f"{est['minutos_totales']} min"),
        ("Goles", est["goles"]),
        ("Asistencias", est["asistencias"] if est["asistencias"] is not None else "—"),
        ("Amarillas", est["amarillas"]),
        ("Rojas", est["rojas"]),
    ]
    gps_rows = [
        ("Partidos con GPS", gps.get("partidos_con_gps", 0)),
        ("Distancia/partido", _m(gps.get("distancia_promedio"))),
        ("V max prom", _d1(gps.get("v_max_promedio"))),
        ("HIAA prom", _i(gps.get("hiaa_promedio"))),
        ("HMLD prom", _m(gps.get("hmld_promedio"))),
        ("Acc prom", _i(gps.get("aceleraciones_promedio"))),
    ]
    med_rows: list[tuple[str, object]] = [("Estado", med["player_status_label"])]
    episodes = med.get("episodes") or []
    if episodes:
        for e in episodes[:3]:
            med_rows.append((e["title"], e["stage"] or ("Cerrado" if e["status"] == "closed" else "Abierto")))
    else:
        med_rows.append(("Episodios", "Sin episodios"))

    parent = Table(
        [[
            card("Estadísticas de juego", est_rows),
            card("Rendimiento físico", gps_rows),
            card("Reporte médico", med_rows),
        ]],
        colWidths=[_CONTENT_W / 3] * 3,
    )
    parent.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (0, 0), 0.5, COLOR_RULE),
        ("BOX", (1, 0), (1, 0), 0.5, COLOR_RULE),
        ("BOX", (2, 0), (2, 0), 0.5, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [*_ficha_section_header("Resumen de temporada", fs), parent, Spacer(1, 5 * mm)]


def _num(value) -> str:
    """Trim a Decimal/float to a clean string (170.0 → '170', 70.50 → '70.5')."""
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


# ─── Block builders ──────────────────────────────────────────────────


def _alerts_block(alerts: list[dict], s: dict) -> list:
    if not alerts:
        return [Paragraph("<i>Sin alertas — todo en orden.</i>", s["body_muted"])]

    rows = [["Severidad", "Mensaje", "Detectada"]]
    for a in alerts:
        rows.append([
            _severity_label(a["severity"]),
            _shorten(a["message"], 90),
            _format_date(a["last_fired_at"]),
        ])

    tbl = Table(
        rows,
        colWidths=[3 * cm, _CONTENT_W - 3 * cm - 3.5 * cm, 3.5 * cm],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (-1, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    # Per-row left-bar color by severity (rows are 1..N; 0 is header).
    for i, a in enumerate(alerts, start=1):
        color = _severity_color(a["severity"])
        style.append(("LINEBEFORE", (0, i), (0, i), 3, color))
    tbl.setStyle(TableStyle(style))
    return [tbl]


def _alerted_metrics_block(metrics: list[dict], s: dict) -> list:
    if not metrics:
        return [Paragraph("<i>Sin métricas alertadas.</i>", s["body_muted"])]

    rows = [["Métrica", "Actual", "Previo", "Δ"]]
    style_rows: list = []
    for i, m in enumerate(metrics, start=1):
        metric_cell = (
            f"<b>{_esc(m['field_label'])}</b><br/>"
            f"<font size='7' color='#6b7280'>{_esc(m['template_label'])}</font>"
        )
        peer_line = _peer_caption(m)
        if peer_line:
            metric_cell += f"<br/><font size='6.5' color='#6b7280'>{_esc(peer_line)}</font>"
        rows.append([
            Paragraph(metric_cell, s["body"]),
            _value_str(m["current_value"], m["unit"]),
            _value_str(m["previous_value"], m["unit"]),
            _delta_str(m["delta"], m["unit"], m["direction_of_good"]),
        ])
        # Color the Δ cell per delta direction.
        delta_color = _delta_color(m["delta"], m["direction_of_good"])
        if delta_color is not None:
            style_rows.append(("TEXTCOLOR", (3, i), (3, i), delta_color))

    tbl = Table(
        rows,
        colWidths=[
            _CONTENT_W - 3 * 2.4 * cm,
            2.4 * cm, 2.4 * cm, 2.4 * cm,
        ],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ] + style_rows
    tbl.setStyle(TableStyle(style))
    return [tbl]


def _metrics_evolution_block(metrics: list[dict], s: dict, fs: dict) -> list:
    """Chart form of "otras métricas": a compact line chart per metric
    showing its 30-day evolution, replacing the old text-trail table.
    Metrics with <2 datapoints (no line to draw) fall back to a compact
    one-liner that keeps actual / previo / Δ so no information is lost."""
    if not metrics:
        return [Paragraph("<i>Sin métricas registradas.</i>", s["body_muted"])]

    out: list = []
    for m in metrics:
        label = (
            f"<b>{_esc(m['field_label'])}</b>"
            f"  <font size='7' color='#6b7280'>{_esc(m['template_label'])}</font>"
        )
        caption = _peer_caption(m)
        cap_para = (
            Paragraph(f"<font size='7' color='#6b7280'>{_esc(caption)}</font>", s["body"])
            if caption else None
        )
        chart = _evolution_chart(m)
        if chart is None:
            line = f"{label} — {_metric_inline_values(m)}"
            if caption:
                line += f"  <font size='7' color='#6b7280'>· {_esc(caption)}</font>"
            out.append(Paragraph(line, s["body"]))
            continue
        # Keep the label glued to its chart so a page break can't orphan
        # the title from the plot it describes.
        block = [Paragraph(label, s["body"]), chart]
        if cap_para is not None:
            block.append(cap_para)
        out.append(KeepTogether(block))
        out.append(Spacer(1, 4 * mm))
    return out


def _metric_inline_values(m: dict) -> str:
    """`actual · previo · Δ` one-liner for metrics without enough history
    to chart. Δ is colored green/red per direction_of_good, mirroring the
    old table's delta cell."""
    parts = [f"actual: {_value_str(m['current_value'], m['unit'])}"]
    if m.get("previous_value") is not None:
        parts.append(f"previo: {_value_str(m['previous_value'], m['unit'])}")
    dstr = _delta_str(m.get("delta"), m["unit"], m.get("direction_of_good"))
    if dstr != "—":
        dcolor = _delta_color(m.get("delta"), m.get("direction_of_good"))
        if dcolor is not None:
            dstr = f"<font color='{_color_hex(dcolor)}'>{dstr}</font>"
        parts.append(f"Δ {dstr}")
    return "  ·  ".join(parts)


def _peer_caption(m: dict) -> str:
    """Compact 'vs equipo / vs posición' line from `references.peer`:
    team & same-position averages plus the player's team percentile."""
    peer = (m.get("references") or {}).get("peer") or {}
    unit = m.get("unit") or ""
    parts: list[str] = []
    t = peer.get("team")
    if t:
        parts.append(f"equipo {_value_str(t['avg'], unit)} · P{t['percentile']}")
    pos = peer.get("position")
    if pos:
        parts.append(f"{pos.get('label', 'posición')} {_value_str(pos['avg'], unit)}")
    return "  ·  ".join(parts)


def _evolution_chart(metric: dict, width_cm: float = 17.5):
    """Render one metric's history_30d as a navy line chart (latest point
    highlighted red), returned as a reportlab flowable. None if there
    aren't at least 2 datapoints to draw a line between."""
    history = metric.get("history_30d") or []
    pts = [
        (p.get("recorded_at"), float(p["value"]))
        for p in history
        if p.get("value") is not None
    ]
    if len(pts) < 2:
        return None

    # Defensive: the builder yields chronological points, but never trust
    # ordering for something the eye reads as a trend.
    try:
        pts.sort(key=lambda t: t[0])
    except TypeError:
        pass

    # Lazy import: matplotlib is heavy and `_mpl` sets the Agg backend on
    # import. Mirrors the chart renderers under dashboards/pdf/charts/.
    import matplotlib.pyplot as plt

    from .charts._mpl import figure_to_flowable, setup_axes

    xs = list(range(len(pts)))
    ys = [v for _, v in pts]
    labels = [_format_short_date(d) for d, _ in pts]
    # Thin crowded x labels so a dense series stays legible (keep ~8, plus
    # always the last). Ticks stay on every point; only labels are blanked.
    if len(labels) > 8:
        step = max(1, (len(labels) + 7) // 8)
        labels = [
            lab if (i % step == 0 or i == len(labels) - 1) else ""
            for i, lab in enumerate(labels)
        ]

    fig, ax = plt.subplots(figsize=(7.0, 1.9))
    setup_axes(ax)
    ax.plot(
        xs, ys,
        color="#0a2240", linewidth=1.8,
        marker="o", markersize=4,
        markerfacecolor="#0a2240", markeredgecolor="#0a2240",
        zorder=3,
    )
    # Latest reading stands out in the ficha red, with its value labelled.
    ax.plot([xs[-1]], [ys[-1]], marker="o", markersize=7, color="#c8102e", zorder=4)
    unit = metric.get("unit") or ""
    latest_label = f"{_num(ys[-1])} {unit}".strip()
    ax.annotate(
        latest_label, (xs[-1], ys[-1]),
        textcoords="offset points", xytext=(0, 8),
        ha="center", fontsize=8, color="#c8102e", fontweight="bold",
    )
    # Shade the external target band (e.g. ISAK range) when available, so the
    # reader sees in-range vs out-of-range at a glance.
    refs = metric.get("references") or {}
    target = next(
        (
            e["range"] for e in refs.get("external", [])
            if e.get("range")
            and e["range"].get("min") is not None
            and e["range"].get("max") is not None
        ),
        None,
    )
    if target:
        lo, hi = target["min"], target["max"]
        ax.axhspan(lo, hi, color="#16a34a", alpha=0.10, zorder=0)
        ymin, ymax = ax.get_ylim()
        pad = (hi - lo) * 0.35 or 1.0
        ax.set_ylim(min(ymin, lo - pad), max(ymax, hi + pad))
        ax.annotate(
            "objetivo", xy=(0, hi), xytext=(2, 1), textcoords="offset points",
            fontsize=6.5, color="#15803d", va="bottom",
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7)
    ax.margins(x=0.06, y=0.30)
    return figure_to_flowable(fig, width_cm=width_cm)


def _last_match_block(match: dict | None, s: dict) -> list:
    if match is None:
        return [Paragraph("<i>No hay partidos en el calendario.</i>", s["body_muted"])]

    date_str = _format_date(match["event_starts_at"], with_year=True)
    role = match.get("match_role_label") or "—"
    title = _esc(match["event_title"])

    parts = [
        Paragraph(
            f"<b>{title}</b>  ·  <font color='#6b7280'>{date_str}</font>",
            s["body"],
        ),
        Paragraph(
            f"Estado: <b>{_esc(role)}</b>",
            s["body"],
        ),
    ]

    # If the player actually took the field, surface minutes + goals +
    # headline performance numbers. citado_no_vestir is cited-but-not-on-
    # the-field and has no performance to show.
    played_roles = {"titular", "suplente_ingresa", "suplente_no_ingresa"}
    if match.get("match_role") in played_roles:
        stat_bits = []
        if match.get("minutes_played") is not None:
            stat_bits.append(f"Min: <b>{match['minutes_played']}</b>")
        if match.get("goals"):
            stat_bits.append(f"Goles: <b>{match['goals']}</b>")
        if stat_bits:
            parts.append(Paragraph("  ·  ".join(stat_bits), s["body"]))

        for block in match.get("performance", []):
            headline = _headline_stats(block["result_data"])
            if not headline:
                continue
            bits = " · ".join(f"{k}: <b>{v}</b>" for k, v in headline)
            parts.append(
                Paragraph(
                    f"<font color='#6b7280'>{_esc(block['template_label'])}</font>: {bits}",
                    s["body"],
                ),
            )

    return parts


# ─── Helpers ────────────────────────────────────────────────────────


_SEVERITY_LABEL = {"critical": "Crítica", "warning": "Advertencia", "info": "Info"}


def _severity_label(sev: str) -> str:
    return _SEVERITY_LABEL.get(sev, sev.title())


def _severity_color(sev: str):
    if sev == "critical":
        return COLOR_CRIT
    if sev == "warning":
        return COLOR_WARN
    return colors.HexColor("#6366f1")


def _delta_color(delta, direction_of_good):
    if delta is None or abs(delta) < 1e-9:
        return None
    going_up = delta > 0
    if direction_of_good == "up":
        return COLOR_OK if going_up else COLOR_CRIT
    if direction_of_good == "down":
        return COLOR_OK if not going_up else COLOR_CRIT
    return None  # neutral


def _color_hex(c) -> str:
    """reportlab Color → '#rrggbb' for inline <font color='…'> markup.
    Built from the channels so it's robust across reportlab versions."""
    return "#%02x%02x%02x" % (
        round(c.red * 255), round(c.green * 255), round(c.blue * 255),
    )


def _value_str(v, unit) -> str:
    if v is None:
        return "—"
    rounded = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{rounded} {unit}" if unit else rounded


def _delta_str(delta, unit, direction_of_good) -> str:
    """Format a delta with arrow + magnitude + unit. Unit makes the badge
    unambiguous on a printed page where context is easy to lose."""
    if delta is None or abs(delta) < 1e-9:
        return "—"
    arrow = "↑" if delta > 0 else "↓"
    rounded = f"{abs(delta):.2f}".rstrip("0").rstrip(".")
    return f"{arrow} {rounded} {unit}" if unit else f"{arrow} {rounded}"


def _format_date(value, *, with_year: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_DISPLAY_TZ)
    dt = dt.astimezone(_DISPLAY_TZ)
    fmt = "%d %b %Y" if with_year else "%d %b"
    return dt.strftime(fmt)


def _format_short_date(value) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_DISPLAY_TZ)
    dt = dt.astimezone(_DISPLAY_TZ)
    return dt.strftime("%d/%m")


def _headline_stats(result_data: dict[str, Any]) -> list[tuple[str, Any]]:
    """Pick up to 4 numeric headline stats from a match-performance block.
    The result_data shape varies per template — we surface whatever's
    there without per-template knowledge."""
    out = []
    for k, v in result_data.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append((_prettify_key(k), v))
        if len(out) >= 4:
            break
    return out


def _prettify_key(key: str) -> str:
    return key.replace("_", " ").title()


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _esc(text: str) -> str:
    """Escape XML for reportlab Paragraph."""
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
