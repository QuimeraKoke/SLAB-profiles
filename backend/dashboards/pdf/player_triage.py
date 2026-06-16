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
from reportlab.lib.units import cm, mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from api.triage import build_triage_payload
from core.models import Player

from .scaffold import (
    COLOR_CRIT,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_RULE,
    COLOR_WARN,
    build_pdf,
    logo_image_for_club,
    section_header,
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

    club = player.category.club if player.category else None
    cover = {
        "title": "Resumen del jugador",
        "subtitle": f"{player.first_name} {player.last_name}",
        "club_name": club.name if club else "",
        "club_logo": logo_image_for_club(club) if club else None,
        "category_name": player.category.name if player.category else "",
        "period_label": "",
        "generated_at": payload["generated_at"].astimezone(_DISPLAY_TZ),
    }

    sections: list[dict[str, Any]] = []

    sections.append({
        "title": "Alertas activas",
        "flowables": _alerts_block(payload["alerts"], s),
    })
    sections.append({
        "title": "Métricas alertadas",
        "flowables": _alerted_metrics_block(payload["alerted_metrics"], s),
    })
    sections.append({
        "title": "Otras métricas recientes",
        "flowables": _other_metrics_block(payload["other_metrics"], s),
    })
    sections.append({
        "title": "Último partido" if (payload["last_match"] and payload["last_match"]["is_past"]) else "Próximo partido",
        "flowables": _last_match_block(payload["last_match"], s),
    })

    return build_pdf(
        orientation="portrait",
        cover=cover,
        sections=sections,
    )


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
