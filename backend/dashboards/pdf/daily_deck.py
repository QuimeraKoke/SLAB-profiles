"""La Daily as a projectable PDF deck — one slide per player.

Landscape A4, meeting order: portada → índice de lesionados → one slide
per lesionado (valores actuales vs. habituales pre-lesión) → jugadores
con alerta (one slide each) → anexo de disponibles (one slide each, the
"ficha resumida" so any player can be pulled up when someone asks).

Deterministic and LLM-free — renders in well under a second, so there is
no snapshot/caching layer: the deck always reflects the data of the
moment the button is pressed.
"""

from __future__ import annotations

from datetime import date as date_cls

from reportlab.graphics.shapes import Drawing, Line, Rect
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, Spacer, Table, TableStyle

from .scaffold import (
    COLOR_CRIT,
    COLOR_FICHA_NAVY,
    COLOR_FICHA_RED,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_RULE,
    COLOR_WARN,
    PAGE_MARGIN,
    build_pdf,
    logo_image_for_club,
)

# Landscape A4 content width (297mm wide).
_CONTENT_W = 297 * mm - 2 * PAGE_MARGIN

_STATUS_COLOR = {
    "injured": COLOR_CRIT,
    "recovery": COLOR_WARN,
    "reintegration": COLOR_FICHA_NAVY,
    "available": COLOR_OK,
}
_SEV_COLOR = {"critical": COLOR_CRIT, "warning": COLOR_WARN}
_TONE_COLOR = {"ok": COLOR_OK, "warn": COLOR_WARN, "crit": COLOR_CRIT}


def _s() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Helvetica", textColor=COLOR_FICHA_NAVY)
    return {
        "deck_title": ParagraphStyle("deck_title", fontName="Helvetica-Bold",
                                     fontSize=44, leading=50, alignment=1,
                                     textColor=COLOR_FICHA_NAVY),
        "deck_sub": ParagraphStyle("deck_sub", fontSize=18, leading=24, alignment=1,
                                   textColor=COLOR_MUTED, fontName="Helvetica"),
        "slide_kicker": ParagraphStyle("slide_kicker", fontName="Helvetica-Bold",
                                       fontSize=12, leading=15,
                                       textColor=COLOR_FICHA_RED),
        "player_name": ParagraphStyle("player_name", fontName="Helvetica-Bold",
                                      fontSize=27, leading=32,
                                      textColor=COLOR_FICHA_NAVY),
        "player_meta": ParagraphStyle("player_meta", fontSize=13, leading=17,
                                      textColor=COLOR_MUTED, **{"fontName": "Helvetica"}),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                             leading=16, textColor=COLOR_FICHA_NAVY, spaceAfter=3),
        "body": ParagraphStyle("body", fontSize=11.5, leading=15.5, **base),
        "muted": ParagraphStyle("muted", fontSize=10.5, leading=14,
                                textColor=COLOR_MUTED, fontName="Helvetica"),
        "big_day": ParagraphStyle("big_day", fontName="Helvetica-Bold",
                                  fontSize=22, leading=25, textColor=COLOR_FICHA_NAVY),
    }


# ─── Drawings ────────────────────────────────────────────────────────────


def _meter(pct: int | None, width: float = 52 * mm, height: float = 5 * mm) -> Drawing:
    """Fill toward the 100% tick (habitual), capped at 130% like the web."""
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#eef0f5"),
               strokeColor=None, rx=2, ry=2))
    if pct is not None:
        cap = 130
        fill_w = min(pct, cap) / cap * width
        d.add(Rect(0, 0, max(fill_w, 1), height, fillColor=COLOR_FICHA_NAVY,
                   strokeColor=None, rx=2, ry=2))
        tick_x = 100 / cap * width
        d.add(Line(tick_x, -1, tick_x, height + 1, strokeColor=COLOR_FICHA_RED,
                   strokeWidth=1.4))
    return d


def _forma_bars(forma: list[dict], width: float = 40 * mm, height: float = 9 * mm) -> Drawing:
    """The 7-day wellness sparkline as mini bars (empty days = baseline dots)."""
    d = Drawing(width, height)
    n = max(len(forma), 1)
    bar_w = width / n * 0.62
    step = width / n
    for i, bar in enumerate(forma):
        x = i * step + (step - bar_w) / 2
        v = bar.get("value")
        if v is None:
            d.add(Rect(x, 0, bar_w, 0.8, fillColor=COLOR_RULE, strokeColor=None))
            continue
        h = max(1.5, v / 100 * height)
        color = _TONE_COLOR.get(bar.get("tone") or "", COLOR_FICHA_NAVY)
        d.add(Rect(x, 0, bar_w, h, fillColor=color, strokeColor=None))
    return d


# ─── Slide pieces ────────────────────────────────────────────────────────


def _fmt_day(iso: str | None) -> str:
    if not iso:
        return "—"
    d = date_cls.fromisoformat(iso[:10])
    return d.strftime("%d-%m-%Y")


def _num(v: float | None) -> str:
    """Chilean number format: thousands '.', decimal ',' (2.067,5)."""
    if v is None:
        return "—"
    txt = f"{v:,.1f}"
    if txt.endswith(".0"):
        txt = txt[:-2]
    return txt.replace(",", "␟").replace(".", ",").replace("␟", ".")


def _slide_header(kicker: str, name: str, meta: str, badge: str,
                  badge_color, s: dict) -> list:
    badge_style = ParagraphStyle(
        "badge", fontName="Helvetica-Bold", fontSize=13, leading=16,
        textColor=colors.white, alignment=1,
    )
    header = Table(
        [
            [Paragraph(kicker, s["slide_kicker"]), ""],
            [Paragraph(name, s["player_name"]),
             Table([[Paragraph(badge, badge_style)]],
                   colWidths=[52 * mm],
                   style=TableStyle([
                       ("BACKGROUND", (0, 0), (-1, -1), badge_color),
                       ("TOPPADDING", (0, 0), (-1, -1), 5),
                       ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                       ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                   ]))],
            [Paragraph(meta, s["player_meta"]), ""],
        ],
        colWidths=[_CONTENT_W - 56 * mm, 56 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
        ]),
    )
    rule = Table([[""]], colWidths=[_CONTENT_W], rowHeights=[2.2],
                 style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), COLOR_FICHA_RED)]))
    return [header, Spacer(1, 2 * mm), rule, Spacer(1, 5 * mm)]


def _value_chips(chips: list[tuple[str, str]], s: dict) -> Table:
    """Row of label-over-value stat chips."""
    label_style = ParagraphStyle("chip_l", fontName="Helvetica-Bold", fontSize=8.5,
                                 leading=11, textColor=COLOR_MUTED)
    value_style = ParagraphStyle("chip_v", fontName="Helvetica-Bold", fontSize=16,
                                 leading=20, textColor=COLOR_FICHA_NAVY)
    cells = []
    for label, value in chips:
        cells.append(Table(
            [[Paragraph(label.upper(), label_style)], [Paragraph(value, value_style)]],
            colWidths=[(_CONTENT_W / len(chips)) - 6 * mm],
            style=TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (0, 0), 6),
                ("BOTTOMPADDING", (0, 1), (0, 1), 6),
                ("BOX", (0, 0), (-1, -1), 0.75, COLOR_RULE),
            ]),
        ))
    return Table([cells], colWidths=[_CONTENT_W / len(chips)] * len(chips),
                 style=TableStyle([
                     ("LEFTPADDING", (0, 0), (-1, -1), 0),
                     ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                     ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ]))


def _gps_block(gc: dict | None, s: dict) -> list:
    out: list = [Paragraph("GPS · actual vs. habitual pre-lesión", s["h2"])]
    if not gc:
        out.append(Paragraph("Sin datos GPS para comparar.", s["muted"]))
        return out
    metrics = gc.get("metrics") or []
    with_current = any(m["current"] is not None for m in metrics)
    window = (
        f"Semana al {_fmt_day(gc.get('current_to'))} vs. "
        f"{(gc.get('baseline_days') or 56) // 7} semanas previas a la lesión "
        f"({_fmt_day(gc.get('injured_at'))})."
        if with_current else "Sin trabajo de cancha registrado desde la lesión."
    )
    out.append(Paragraph(window, s["muted"]))
    out.append(Spacer(1, 2 * mm))
    if not with_current:
        return out

    rows = []
    for m in metrics:
        cur = _num(m["current"])
        base = _num(m["baseline"])
        rows.append([
            Paragraph(m["label"], s["body"]),
            Paragraph(f"<b>{cur}</b> / {base} {m['unit']}", s["body"]),
            _meter(m["pct"]),
            Paragraph(f"<b>{m['pct']}%</b>" if m["pct"] is not None else "—", s["body"]),
        ])
    out.append(Table(
        rows,
        colWidths=[38 * mm, 52 * mm, 56 * mm, 16 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
        ]),
        hAlign="LEFT",
    ))
    return out


def _alerts_block(alerts: list[dict], s: dict) -> list:
    if not alerts:
        return [Paragraph("Sin alertas activas.", s["muted"])]
    out = []
    for a in alerts:
        color = "#b42318" if a["severity"] == "critical" else "#b76e00"
        out.append(Paragraph(
            f'<font color="{color}">▲</font>&nbsp;&nbsp;{a["message"]}',
            s["body"],
        ))
    return out


def _notes_block(notes: list[dict], s: dict) -> list:
    if not notes:
        return [Paragraph("Sin notas para esta fecha.", s["muted"])]
    out = []
    for n in notes:
        dept = (n.get("department") or {}).get("name") or "General"
        out.append(Paragraph(
            f'<font color="#4438ca"><b>[{dept}]</b></font> {n["text"]}'
            f'<font color="#98a2b3"> — {n.get("author") or ""}</font>',
            s["body"],
        ))
    return out


def _plan_block(plans: list[dict], s: dict) -> list:
    """The player's standing 'plan de trabajo' (KIND_PLAN), newest first."""
    out = [Paragraph("Plan de trabajo", s["h2"])]
    if not plans:
        out.append(Paragraph("Sin plan de trabajo vigente.", s["muted"]))
        return out
    for p in plans:
        dept = (p.get("department") or {}).get("name") or "General"
        out.append(Paragraph(
            f'<font color="#0d9488"><b>[{dept}]</b></font> {p["text"]}'
            f'<font color="#98a2b3"> — {_fmt_day(p.get("date"))}</font>',
            s["body"],
        ))
    return out


# ─── Slides ──────────────────────────────────────────────────────────────


_SPANISH_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_SPANISH_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                   "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _long_date(d: date_cls) -> str:
    return f"{_SPANISH_DAYS[d.weekday()].capitalize()} {d.day} de {_SPANISH_MONTHS[d.month - 1]} de {d.year}"


def _cover_slide(data: dict, category, target_date: date_cls, s: dict) -> list:
    out: list = [Spacer(1, 18 * mm)]
    logo = logo_image_for_club(category.club)
    if logo is not None:
        try:
            img = Image(logo, width=42 * mm, height=42 * mm, kind="proportional")
            img.hAlign = "CENTER"
            out.append(img)
            out.append(Spacer(1, 6 * mm))
        except Exception:  # noqa: BLE001 — a bad logo shouldn't kill the deck
            pass
    out.append(Paragraph("DAILY", s["deck_title"]))
    out.append(Spacer(1, 2 * mm))
    out.append(Paragraph(
        f"{category.club.name} · {category.name}<br/>{_long_date(target_date)}",
        s["deck_sub"],
    ))
    out.append(Spacer(1, 12 * mm))

    k = data["kpis"]
    chips = [
        ("Disponibles", f"{k['disponibles']['n']}/{k['disponibles']['total']}"),
        ("No disponibles", str(k["no_disponibles"]["n"])),
        ("Alertas activas", f"{k['alertas']['critical'] + k['alertas']['warning']}"
                            f"  ({k['alertas']['critical']} crít.)"),
        ("Wellness de hoy", f"{k['wellness_hoy']['n']}/{k['wellness_hoy']['expected']}"),
    ]
    out.append(_value_chips(chips, s))
    out.append(PageBreak())
    return out


def _index_slide(data: dict, s: dict) -> list:
    out: list = list(_slide_header(
        "1 · LESIONADOS Y EN PROCESO", "Lesionados",
        "Diagnóstico, días de baja y etapa — el detalle viene un jugador por lámina.",
        f"{len(data['lesionados'])} JUGADORES", COLOR_FICHA_NAVY, s,
    ))
    if not data["lesionados"]:
        out.append(Paragraph("Sin jugadores fuera del grupo.", s["muted"]))
        out.append(PageBreak())
        return out

    head_style = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=10.5,
                                textColor=colors.white)
    rows = [[Paragraph(h, head_style) for h in
             ["Jugador", "Diagnóstico", "Etapa", "Día", "Retorno estimado"]]]
    for l in data["lesionados"]:
        ep = l.get("episode") or {}
        rows.append([
            Paragraph(f"<b>{l['name']}</b>", s["body"]),
            Paragraph(ep.get("title") or "—", s["body"]),
            Paragraph(ep.get("stage_label") or l["status_label"], s["body"]),
            Paragraph(str(ep.get("days_out", "—")), s["body"]),
            Paragraph(_fmt_day(ep.get("expected_return")) if ep.get("expected_return")
                      else "Sin estimar", s["body"]),
        ])
    out.append(Table(
        rows,
        colWidths=[62 * mm, _CONTENT_W - 62 * mm - 34 * mm - 16 * mm - 40 * mm,
                   34 * mm, 16 * mm, 40 * mm],
        repeatRows=1,
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_FICHA_NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, COLOR_RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    ))
    out.append(PageBreak())
    return out


def _kine_slide(data: dict, s: dict) -> list:
    """The kinesiology daily table ('Plan kinésico') — injured players first
    (always shown), then any optionally-added player with a record."""
    kine_by_player = {e["player_id"]: e for e in data.get("kine", [])}
    injured_ids = {l["player_id"] for l in data["lesionados"]}
    merged: list[tuple[str, dict]] = [
        (l["name"], kine_by_player.get(l["player_id"]) or {}) for l in data["lesionados"]
    ]
    merged += [
        (e["player_name"], e)
        for e in data.get("kine", [])
        if e["player_id"] not in injured_ids
    ]

    out: list = list(_slide_header(
        "PLAN KINÉSICO", "Plan kinésico",
        "Registro diario de kinesiología — clínica, gimnasio, cancha y objetivo.",
        f"{len(merged)} JUGADOR{'ES' if len(merged) != 1 else ''}", COLOR_FICHA_NAVY, s,
    ))
    if not merged:
        out.append(Paragraph("Sin registros kinésicos para esta fecha.", s["muted"]))
        out.append(PageBreak())
        return out

    head_style = ParagraphStyle("th_kine", fontName="Helvetica-Bold", fontSize=10.5,
                                textColor=colors.white)
    headers = ["Jugador", "Clínica", "Gimnasio", "Cancha",
               "Objetivo Diario Kinésico", "Kinesiólogo"]
    rows = [[Paragraph(h, head_style) for h in headers]]
    for name, e in merged:
        rows.append([
            Paragraph(f"<b>{name}</b>", s["body"]),
            Paragraph(e.get("clinica") or "—", s["body"]),
            Paragraph(e.get("gimnasio") or "—", s["body"]),
            Paragraph(e.get("cancha") or "—", s["body"]),
            Paragraph(e.get("objetivo") or "—", s["body"]),
            Paragraph(e.get("kinesiologo") or "—", s["body"]),
        ])
    frac = [0.17, 0.17, 0.14, 0.16, 0.24, 0.12]
    out.append(Table(
        rows,
        colWidths=[f * _CONTENT_W for f in frac],
        repeatRows=1,
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_FICHA_NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, COLOR_RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    ))
    out.append(PageBreak())
    return out


def _lesionado_slide(l: dict, plans: list[dict], s: dict) -> list:
    ep = l.get("episode") or {}
    meta_bits = [l["position"]]
    if ep.get("severity"):
        meta_bits.append(f"Severidad: {ep['severity']}")
    out: list = list(_slide_header(
        "LESIONADO · DETALLE",
        l["name"],
        " · ".join(meta_bits),
        (ep.get("stage_label") or l["status_label"]).upper(),
        _STATUS_COLOR.get(ep.get("stage") or l["status"], COLOR_MUTED), s,
    ))

    chips = [
        ("Día de baja", str(ep.get("days_out", "—"))),
        ("Desde", _fmt_day(ep.get("diagnosed_at"))),
        ("Retorno estimado",
         _fmt_day(ep.get("expected_return")) if ep.get("expected_return") else "Sin estimar"),
        ("Wellness",
         f"{l['wellness']['score']} ({_fmt_day(l['wellness']['date'])[:5]})"
         if l.get("wellness") else "—"),
    ]
    out.append(_value_chips(chips, s))
    out.append(Spacer(1, 4 * mm))

    if ep.get("title"):
        out.append(Paragraph(f"Diagnóstico: {ep['title']}", s["h2"]))
    if ep.get("plan"):
        out.append(Paragraph(ep["plan"], s["body"]))
    out.append(Spacer(1, 4 * mm))

    out.extend(_gps_block(l.get("gps_compare"), s))
    out.append(Spacer(1, 4 * mm))

    if l.get("alerts"):
        out.append(Paragraph("Alertas", s["h2"]))
        out.extend(_alerts_block(l["alerts"], s))
        out.append(Spacer(1, 3 * mm))

    out.append(Paragraph("Pauta del día", s["h2"]))
    out.extend(_notes_block(l.get("notes") or [], s))
    out.append(Spacer(1, 3 * mm))
    out.extend(_plan_block(plans, s))
    out.append(PageBreak())
    return out


def _alert_slide(row: dict, roster_row: dict | None, notes: list[dict],
                 plans: list[dict], s: dict) -> list:
    worst = row.get("worst") or "warning"
    out: list = list(_slide_header(
        "2 · ALERTAS",
        row["name"],
        (roster_row or {}).get("position") or "",
        "ALERTA CRÍTICA" if worst == "critical" else "ALERTA",
        _SEV_COLOR.get(worst, COLOR_WARN), s,
    ))
    out.append(_resume_chips(roster_row, s))
    out.append(Spacer(1, 5 * mm))
    out.append(Paragraph("Alertas activas", s["h2"]))
    out.extend(_alerts_block(row.get("alerts") or [], s))
    out.append(Spacer(1, 4 * mm))
    out.append(Paragraph("Pauta del día", s["h2"]))
    out.extend(_notes_block(notes, s))
    out.append(Spacer(1, 3 * mm))
    out.extend(_plan_block(plans, s))
    out.append(PageBreak())
    return out


def _resume_chips(r: dict | None, s: dict) -> Table:
    r = r or {}
    acwr = r.get("acwr_meta") or {}
    chips = [
        ("Readiness", str(r["readiness"]) if r.get("readiness") is not None else "—"),
        ("Wellness", str(r["wellness"]) if r.get("wellness") is not None else "—"),
        ("ACWR", f"{acwr['ratio']}" if acwr else "—"),
        ("Carga 7d / semana típica",
         f"{acwr['acute_km']} / {acwr['chronic_week_km']} km" if acwr else "—"),
        ("Último GPS", _fmt_day(acwr.get("last")) if acwr.get("last") else "—"),
    ]
    return _value_chips(chips, s)


def _disponible_slide(r: dict, notes: list[dict], plans: list[dict], s: dict) -> list:
    out: list = list(_slide_header(
        "3 · DISPONIBLES · ANEXO",
        r["name"],
        r.get("position") or "",
        "DISPONIBLE", COLOR_OK, s,
    ))
    out.append(_resume_chips(r, s))
    out.append(Spacer(1, 6 * mm))
    out.append(Paragraph("Tendencia wellness (7 días)", s["h2"]))
    forma = r.get("forma") or []
    if any(b.get("value") is not None for b in forma):
        out.append(_forma_bars(forma, width=70 * mm, height=14 * mm))
    else:
        out.append(Paragraph("Sin check-ins esta semana.", s["muted"]))
    out.append(Spacer(1, 5 * mm))
    out.append(Paragraph("Pauta del día", s["h2"]))
    out.extend(_notes_block(notes, s))
    out.append(Spacer(1, 3 * mm))
    out.extend(_plan_block(plans, s))
    out.append(PageBreak())
    return out


def _divider_slide(kicker: str, title: str, subtitle: str, count: int, s: dict) -> list:
    out: list = [Spacer(1, 40 * mm)]
    out.append(Paragraph(kicker, ParagraphStyle(
        "div_k", parent=s["slide_kicker"], alignment=1, fontSize=15)))
    out.append(Spacer(1, 3 * mm))
    out.append(Paragraph(title, ParagraphStyle(
        "div_t", parent=s["deck_title"], fontSize=34, leading=40)))
    out.append(Spacer(1, 3 * mm))
    out.append(Paragraph(f"{subtitle} · {count} jugador{'es' if count != 1 else ''}",
                         s["deck_sub"]))
    out.append(PageBreak())
    return out


# ─── Public API ──────────────────────────────────────────────────────────


def render_daily_deck(category, target_date: date_cls, user=None) -> bytes:
    from api.daily_report import build_daily_report, plans_by_player
    from api.roster import build_roster

    data = build_daily_report(category, target_date, user)
    roster = {r["id"]: r for r in build_roster(category)["players"]}
    notes_by_player: dict[str, list] = {}
    for n in data["notes"]:
        notes_by_player.setdefault(n["player_id"], []).append(n)
    plans_map = plans_by_player(category, target_date)

    s = _s()
    story: list = []
    story.extend(_cover_slide(data, category, target_date, s))
    story.extend(_index_slide(data, s))
    for l in data["lesionados"]:
        story.extend(_lesionado_slide(l, plans_map.get(l["player_id"], []), s))

    # Kinesiology daily table — the physios' plan for the injured (+ optional).
    story.extend(_kine_slide(data, s))

    alert_rows = data["alertas"]
    story.extend(_divider_slide("SEGUNDA PARTE", "Alertas",
                                "Disponibles con alguna alerta activa", len(alert_rows), s))
    for row in alert_rows:
        story.extend(_alert_slide(row, roster.get(row["player_id"]),
                                  notes_by_player.get(row["player_id"], []),
                                  plans_map.get(row["player_id"], []), s))

    alerted = {r["player_id"] for r in alert_rows}
    lesionados = {l["player_id"] for l in data["lesionados"]}
    disponibles = [
        r for pid, r in roster.items()
        if r["status"] == "available" and pid not in alerted and pid not in lesionados
    ]
    disponibles.sort(key=lambda r: r["name"])
    story.extend(_divider_slide("ANEXO", "Disponibles",
                                "Sin alertas — ficha resumida por jugador", len(disponibles), s))
    for r in disponibles:
        story.extend(_disponible_slide(r, notes_by_player.get(r["id"], []),
                                       plans_map.get(r["id"], []), s))

    # Drop the trailing PageBreak so the PDF doesn't end on a blank page.
    if story and isinstance(story[-1], PageBreak):
        story.pop()

    return build_pdf(
        orientation="landscape",
        cover={"title": f"Daily — {category.name}",
               "club_name": category.club.name},
        flowables=story,
    )
