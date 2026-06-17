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
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

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


# ─── Public entry point ───────────────────────────────────────────────


def render_triage_pdf(player: Player) -> bytes:
    payload = build_triage_payload(player)
    return _render_from_payload(payload, player)


# ─── Layout ───────────────────────────────────────────────────────────


def _render_from_payload(payload: dict, player: Player) -> bytes:
    s = styles()
    fs = _ficha_styles()

    club = player.category.club if player.category else None
    cover = {  # PDF document metadata only (flat-flowables mode skips the cover page)
        "title": f"Ficha — {player.first_name} {player.last_name}",
        "club_name": club.name if club else "",
    }

    flow: list = []

    # 1. Ficha identity band — club lockup + player name + bio + status badge.
    flow.extend(_ficha_header(player, club, payload, fs))

    # 2. The "telling a story" narrative (LLM). Rendered on top, above the
    #    supporting data tables. Skipped silently when unavailable so the
    #    PDF always degrades to the deterministic tables alone.
    narrative = generate_player_narrative(payload)
    if narrative:
        flow.extend(_narrative_block(narrative, s, fs))

    # 3. Supporting data — the existing deterministic tables, restyled with
    #    ficha section headers. These are the verifiable evidence under the
    #    narrative; the narrative is grounded in exactly this data.
    flow.extend(_ficha_section(
        "Alertas activas", _alerts_block(payload["alerts"], s), fs,
    ))
    flow.extend(_ficha_section(
        "Métricas alertadas", _alerted_metrics_block(payload["alerted_metrics"], s), fs,
    ))
    flow.extend(_ficha_section(
        "Evolución de métricas (30 días)",
        _metrics_evolution_block(payload["other_metrics"], s, fs),
        fs,
    ))
    match_title = (
        "Último partido"
        if (payload["last_match"] and payload["last_match"]["is_past"])
        else "Próximo partido"
    )
    flow.extend(_ficha_section(
        match_title, _last_match_block(payload["last_match"], s), fs,
    ))

    return build_pdf(orientation="portrait", cover=cover, flowables=flow)


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
    bio_bits: list[str] = []
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
    }


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
        rows.append([
            Paragraph(
                f"<b>{_esc(m['field_label'])}</b><br/>"
                f"<font size='7' color='#6b7280'>{_esc(m['template_label'])}</font>",
                s["body"],
            ),
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


def _other_metrics_block(metrics: list[dict], s: dict) -> list:
    if not metrics:
        return [Paragraph("<i>Sin métricas registradas.</i>", s["body_muted"])]

    # PDF rendering of the 30d sparkline is intentionally a text trail —
    # last 3 datapoints with their dates. Cheap, fits any printer, and
    # tells the same story the on-screen SVG does. (Adding a real
    # sparkline renderer here would need a matplotlib PNG per row.)
    rows = [["Métrica", "Trayectoria (30d)", "Actual", "Previo", "Δ"]]
    style_rows: list = []
    for i, m in enumerate(metrics, start=1):
        rows.append([
            Paragraph(
                f"<b>{_esc(m['field_label'])}</b><br/>"
                f"<font size='7' color='#6b7280'>{_esc(m['template_label'])}</font>",
                s["body"],
            ),
            _spark_trail(m.get("history_30d", []), m["unit"], m.get("direction_of_good")),
            _value_str(m["current_value"], m["unit"]),
            _value_str(m["previous_value"], m["unit"]),
            _delta_str(m["delta"], m["unit"], m["direction_of_good"]),
        ])
        delta_color = _delta_color(m["delta"], m["direction_of_good"])
        if delta_color is not None:
            style_rows.append(("TEXTCOLOR", (4, i), (4, i), delta_color))

    tbl = Table(
        rows,
        colWidths=[
            4.5 * cm,                                            # metric
            _CONTENT_W - 4.5 * cm - 3 * 2.4 * cm,                # trail (flexible)
            2.4 * cm,                                            # current
            2.4 * cm,                                            # previous
            2.4 * cm,                                            # delta
        ],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
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
    showing its 30-day evolution. Metrics with <2 points fall back to a
    one-line current value (a single dot isn't a trend)."""
    if not metrics:
        return [Paragraph("<i>Sin métricas registradas.</i>", s["body_muted"])]

    out: list = []
    for m in metrics:
        label = (
            f"<b>{_esc(m['field_label'])}</b>"
            f"  <font size='7' color='#6b7280'>{_esc(m['template_label'])}</font>"
        )
        chart = _evolution_chart(m)
        if chart is None:
            out.append(Paragraph(
                f"{label} — actual: {_value_str(m['current_value'], m['unit'])}",
                s["body"],
            ))
            continue
        out.append(Paragraph(label, s["body"]))
        out.append(chart)
        out.append(Spacer(1, 4 * mm))
    return out


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

    # Lazy import: matplotlib is heavy and `_mpl` sets the Agg backend on
    # import. Mirrors the chart renderers under dashboards/pdf/charts/.
    import matplotlib.pyplot as plt

    from .charts._mpl import figure_to_flowable, setup_axes

    xs = list(range(len(pts)))
    ys = [v for _, v in pts]
    labels = [_format_short_date(d) for d, _ in pts]

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


def _spark_trail(points: list[dict], unit, direction_of_good=None) -> str:
    """Text-based 'sparkline' — last 3 points with their short dates,
    prefixed with a direction glyph honoring `direction_of_good` so the
    print reader sees "getting better" / "worse" without comparing
    numbers cell by cell. Keeps the PDF printer-safe (no matplotlib)."""
    if not points:
        return "—"
    tail = points[-3:]

    glyph = "→"
    if len(tail) >= 2:
        going_up = tail[-1]["value"] > tail[0]["value"]
        if direction_of_good == "up":
            glyph = "↑" if going_up else "↓"
        elif direction_of_good == "down":
            glyph = "↓" if going_up else "↑"
        else:
            glyph = "↑" if going_up else "↓"

    bits = []
    for p in tail:
        bits.append(f"{_value_str(p['value'], unit)} ({_format_short_date(p['recorded_at'])})")
    return f"{glyph}  " + " → ".join(bits)


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
