"""Informe de plantel — the long per-player report the formativo's staff
prints (Datos › Exportar reportes › Informe de plantel), A4 portrait, the club's
own layout ("Informe_plantel_S20_ultimas_4_competiciones.pdf", 2026-11-03).

Per player, the sections the user picks, in this order, flowing over as many
pages as they need (each player starts on a new page):

    cargas       Cargas realizadas · últimas N competiciones: the match GPS
                 table + "Distancia total y velocidad" + "Aceleraciones y
                 desaceleraciones" charts.
    condicion    Condición física · last evaluation of each test, its level
                 (the category's bands) and the change vs the one before.
    composicion  Composición corporal · last vs previous pentacompartimental.
    kine         Atenciones kinésicas · último mes (the physios' daily notes).
    lesiones     Historial de lesiones · every injury episode, the worst one
                 and the zones that repeat.

Every number comes from the same place the screens read it: the GPS match
rows, `category_bands` for the levels, `load_control.composition` metrics,
`notas_diarias_kinesiologico`, injury `Episode`s.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from core.models import Player
from exams.models import ExamResult, ExamTemplate

SECTIONS = {
    "cargas": "Cargas realizadas",
    "condicion": "Condición física",
    "composicion": "Composición corporal",
    "kine": "Atenciones kinésicas",
    "lesiones": "Historial de lesiones",
}
DEFAULT_SECTIONS = list(SECTIONS)

PAGE_W, PAGE_H = A4
M = 12 * mm                      # side margin (the club report)
NAVY = colors.HexColor("#0b2f7a")
RED = colors.HexColor("#c8102e")
INK = colors.HexColor("#0f172a")
TITLE = colors.HexColor("#0b2f7a")
MUTED = colors.HexColor("#64748b")
CELL = colors.HexColor("#f1f4f9")
GRID = colors.HexColor("#e2e8f0")
GOOD = colors.HexColor("#15803d")
BAD = colors.HexColor("#c0392b")
GOOD_BG = colors.HexColor("#e3f4e8")
BAD_BG = colors.HexColor("#fde4e4")
# Charts (the club's report): distance bars, HSR and sprint lines, ACC / DEC.
C_DIST = colors.HexColor("#2f66d0")
C_HSR = colors.HexColor("#b8862b")
C_SPRINT = colors.HexColor("#c8102e")
C_DEC = colors.HexColor("#64748b")

# (template slug, field, label, decimals, unit suffix, formatter)
TESTS: list[tuple[str, str, str, int, str]] = [
    ("fuerza", "rm_estimado", "Fuerza · Sentadilla (back squat)", 1, " kg"),
    ("carreras", "t10_best", "Velocidad · T10 (s)", 2, " s"),
    ("carreras", "t30_best", "Velocidad · T30 (s)", 2, " s"),
    ("carreras", "cod_der_best", "Cambio de dirección · COD 505 derecha (s)", 2, " s"),
    ("carreras", "cod_izq_best", "Cambio de dirección · COD 505 izquierda (s)", 2, " s"),
    ("resistencia", "palier", "Resistencia · Yo-Yo IR1", 0, ""),
    ("resistencia_1000m", "tiempo_s", "Resistencia · 1.000 m", -1, ""),   # -1 = m:ss
    ("neuromuscular", "cmj_best", "Neuromuscular · CMJ (cm)", 1, " cm"),
    ("neuromuscular", "tiro_best", "Neuromuscular · Tiro (km/h)", 1, " km/h"),
]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# ─── granularity & statistics (an area with a period can be grouped) ────────
GRANULARITIES = ("detalle", "semana", "mes", "semestre")
STATS = {"mean": "Prom", "max": "Máx", "min": "Mín", "sum": "Total"}


def bucket(d: date, gran: str) -> tuple[tuple, str, str]:
    """(sort key, label, sub-label) of the period `d` falls in."""
    if gran == "semana":
        mon = d - timedelta(days=d.weekday())
        sun = mon + timedelta(days=6)
        return (mon.toordinal(),), f"Semana {mon.isocalendar()[1]}", f"{_short(mon)} – {_short(sun)}"
    if gran == "mes":
        return (d.year, d.month), f"{MONTHS[d.month - 1].capitalize()} {d.year}", ""
    if gran == "semestre":
        h = 1 if d.month <= 6 else 2
        return (d.year, h), f"{'1er' if h == 1 else '2do'} semestre {d.year}", ""
    return (d.toordinal(),), _short(d), ""


def stat(values: list[float], how: str) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    if how == "max":
        return max(vals)
    if how == "min":
        return min(vals)
    if how == "sum":
        return sum(vals)
    return sum(vals) / len(vals)


def group(items: list[dict], gran: str, key: str = "date") -> list[dict]:
    """Items (with a date under `key`) → [{label, sub, items}] in date order."""
    out: dict[tuple, dict] = {}
    for it in items:
        k, label, sub = bucket(it[key], gran)
        out.setdefault(k, {"label": label, "sub": sub, "items": []})["items"].append(it)
    return [out[k] for k in sorted(out)]


# ─── small helpers ──────────────────────────────────────────────────────────

def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: float | None, dec: int = 1) -> str:
    if v is None:
        return "-"
    if dec == -1:                                  # seconds → m:ss
        return f"{int(v // 60)}:{int(round(v % 60)):02d}"
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _int(v: float | None) -> str:
    return "-" if v is None else f"{round(v):,}".replace(",", ".")


def _short(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def _long(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _signed(v: float, dec: int) -> str:
    if dec == -1:
        return ("+" if v > 0 else "-") + _fmt(abs(v), -1)
    s = _fmt(abs(v), dec)
    return ("+" if v > 0 else "-" if v < 0 else "") + s


def _local(dt) -> date:
    return timezone.localtime(dt).date()


def _text(c, x, y, s, size=9, font="Helvetica", color=INK, anchor="left"):
    c.setFont(font, size)
    c.setFillColor(color)
    s = str(s)
    if anchor == "center":
        c.drawCentredString(x, y, s)
    elif anchor == "right":
        c.drawRightString(x, y, s)
    else:
        c.drawString(x, y, s)


def _fit(c, s: str, w: float, size: float, font="Helvetica") -> str:
    """Truncate with an ellipsis to fit width `w`."""
    if c.stringWidth(s, font, size) <= w:
        return s
    while s and c.stringWidth(s + "…", font, size) > w:
        s = s[:-1]
    return s + "…"


def _wrap(c, s: str, w: float, size: float, font="Helvetica") -> list[str]:
    words, lines, cur = str(s).split(), [], ""
    for wd in words:
        t = f"{cur} {wd}".strip()
        if c.stringWidth(t, font, size) <= w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines or [""]


def _tint(col: colors.Color, k: float) -> colors.Color:
    """Blend toward white: k=0 the colour, k=1 white."""
    return colors.Color(col.red + (1 - col.red) * k, col.green + (1 - col.green) * k,
                        col.blue + (1 - col.blue) * k)


def _darken(col: colors.Color, k: float) -> colors.Color:
    return colors.Color(col.red * (1 - k), col.green * (1 - k), col.blue * (1 - k))


def _image(field_file, url: str | None):
    if field_file:
        try:
            with field_file.open("rb") as fh:
                return ImageReader(io.BytesIO(fh.read()))
        except Exception:  # noqa: BLE001 — a missing file must not kill the report
            pass
    if url:
        try:
            import requests

            resp = requests.get(url, timeout=4)
            if resp.ok:
                return ImageReader(io.BytesIO(resp.content))
        except Exception:  # noqa: BLE001
            pass
    return None


def _cat_short(name: str) -> str:
    m = re.search(r"(\d{2})\b", name or "")
    return f"S{m.group(1)}" if m and ("SUB" in name.upper() or "S" in name.upper()[:2]) else (name or "-")


def birth_quartile(dob: date | None) -> str:
    return "-" if dob is None else f"Q{(dob.month - 1) // 3 + 1}"


# ─── data ───────────────────────────────────────────────────────────────────

class _Data:
    """Everything one player's report reads. Templates and the category's
    bands are resolved once per report (`ctx`)."""

    def __init__(self, player: Player, ctx: dict, n_matches: int, today: date,
                 date_from: date | None = None, date_to: date | None = None):
        self.p = player
        self.ctx = ctx
        self.n = n_matches
        self.today = today
        # The period of the section being read (each section has its own:
        # `render_informe_plantel` sets it before each one).
        self.date_from = date_from
        self.date_to = date_to
        self.matches_left_out = 0

    def _window(self, qs, field: str = "recorded_at"):
        if self.date_from:
            qs = qs.filter(**{f"{field}__date__gte": self.date_from})
        if self.date_to:
            qs = qs.filter(**{f"{field}__date__lte": self.date_to})
        return qs

    def tpl(self, slug: str) -> ExamTemplate | None:
        return self.ctx["templates"].get(slug)

    def _rows(self, slug: str, *, windowed: bool = True, **kw):
        t = self.tpl(slug)
        if t is None:
            return ExamResult.objects.none()
        qs = ExamResult.objects.filter(template__family_id=t.family_id or t.id, player=self.p, **kw)
        return self._window(qs) if windowed else qs

    # -- header
    def body(self) -> tuple[float | None, float | None]:
        for slug in ("pentacompartimental", "peso_talla"):
            qs = self._rows(slug, windowed=False)
            if self.date_to:
                qs = qs.filter(recorded_at__date__lte=self.date_to)
            row = qs.order_by("-recorded_at").values_list("result_data", flat=True).first()
            if row and (_num(row.get("talla")) or _num(row.get("peso"))):
                return _num(row.get("peso")), _num(row.get("talla"))
        return _num(self.p.current_weight_kg), _num(self.p.current_height_cm)

    # -- cargas
    def matches(self) -> list[dict]:
        """His last N match GPS rows (one per day), oldest first."""
        out: dict[date, dict] = {}
        rows = (self._window(ExamResult.objects.filter(template__slug="gps_partido", player=self.p))
                .select_related("event").order_by("-recorded_at"))
        for r in rows:
            d = r.result_data or {}
            day = _local(r.recorded_at)
            if day in out or _num(d.get("tot_dist")) is None:
                continue
            meta = (r.event.metadata or {}) if r.event_id else {}
            friendly = (d.get("match_type") == "friendly" or "AMISTOSO" in str(d.get("origen_codigo") or "").upper())
            comp = str(meta.get("competition_phase") or meta.get("competition") or "")
            comp = re.sub(r"\b(Sub\s*\d+|Nacional|Torneo|\d{4})\b", "", comp, flags=re.I).strip(" -·")
            out[day] = {
                "date": day, "friendly": friendly,
                "opponent": d.get("opponent") or meta.get("opponent"),
                "competition": comp,
                "dist": _num(d.get("tot_dist")), "hsr": _num(d.get("hsr")),
                "sprint": _num(d.get("sprint_dist")), "acc": _num(d.get("acc")),
                "dec": _num(d.get("dec")), "vmax": _num(d.get("max_vel")),
            }
            if len(out) >= self.n:
                # How many matches of the window are left out (said on the page).
                self.matches_left_out = len({_local(x.recorded_at) for x in rows
                                             if _num((x.result_data or {}).get("tot_dist")) is not None}) - len(out)
                break
        return sorted(out.values(), key=lambda m: m["date"])

    # -- condición física
    def tests(self) -> list[dict]:
        from exams.bands import band_for_value, band_rank

        bands_by_field = self.ctx["bands"]
        out = []
        for slug, key, label, dec, unit in TESTS:
            t = self.tpl(slug)
            if t is None:
                continue
            readings = []
            for when, data in self._rows(slug).order_by("-recorded_at").values_list("recorded_at", "result_data"):
                v = _num((data or {}).get(key))
                if v is None:
                    continue
                day = _local(when)
                if readings and readings[-1][0] == day:
                    continue                      # a retry the same day
                readings.append((day, v))
                if len(readings) == 2:
                    break
            if not readings:
                continue
            field = next((f for f in (t.config_schema or {}).get("fields", [])
                          if isinstance(f, dict) and f.get("key") == key), {})
            good = field.get("direction_of_good") or ("down" if unit.strip() == "s" or dec == -1 else "up")
            bands = bands_by_field.get((t.family_id or t.id, key)) or []
            band = band_for_value(readings[0][1], bands) if bands else None
            prev = readings[1][1] if len(readings) > 1 else None
            delta = None if prev is None else readings[0][1] - prev
            better = None if not delta else ((delta > 0) == (good == "up"))
            out.append({
                "label": label, "date": readings[0][0], "value": readings[0][1], "dec": dec, "unit": unit,
                "band": (band or {}).get("label"), "color": (band or {}).get("color"),
                "rank": band_rank(band, bands) if band else None, "n_bands": len(bands),
                "delta": delta, "better": better,
            })
        return out

    def test_series(self) -> list[dict]:
        """Every reading of each test inside the window (one per day), for
        the grouped view: [{label, dec, unit, bands, readings: [{date, value}]}]."""
        out = []
        for slug, key, label, dec, unit in TESTS:
            t = self.tpl(slug)
            if t is None:
                continue
            seen, readings = set(), []
            for when, data in self._rows(slug).order_by("recorded_at").values_list("recorded_at", "result_data"):
                v = _num((data or {}).get(key))
                day = _local(when)
                if v is None or day in seen:
                    continue
                seen.add(day)
                readings.append({"date": day, "value": v})
            if readings:
                out.append({"label": label, "dec": dec, "unit": unit, "readings": readings,
                            "bands": self.ctx["bands"].get((t.family_id or t.id, key)) or []})
        return out

    def measurements(self) -> list[dict]:
        from load_control.composition import _measurement

        out = []
        for w, d in self._rows("pentacompartimental").order_by("recorded_at").values_list("recorded_at", "result_data"):
            m = _measurement(w, d)
            if any(m.get(k) is not None for k in ("peso", "mm", "map", "pl")):
                out.append(m | {"day": _local(w)})
        return out

    # -- composición
    def composition(self) -> tuple[dict | None, dict | None]:
        from load_control.composition import _measurement

        ms = [m for m in (_measurement(w, d) for w, d in
                          self._rows("pentacompartimental").order_by("recorded_at")
                          .values_list("recorded_at", "result_data"))
              if any(m.get(k) is not None for k in ("peso", "mm", "map", "pl"))]
        if not ms:
            return None, None
        return ms[-1], (ms[-2] if len(ms) > 1 else None)

    # -- kine
    def kine_span(self) -> tuple[date, date]:
        """The period, or the last month when none was picked."""
        end = self.date_to or self.today
        return (self.date_from or end - timedelta(days=30)), end

    def kine(self) -> tuple[list[dict], dict | None]:
        since, until = self.kine_span()
        qs = self._rows("notas_diarias_kinesiologico", windowed=False).filter(recorded_at__date__lte=until)
        rows = [{"date": _local(w), "tipo": d.get("tipo_intervencion") or "", "who": d.get("tratante") or "",
                 "text": d.get("nota") or d.get("asunto") or ""}
                for w, d in qs.order_by("-recorded_at").values_list("recorded_at", "result_data")]
        recent = [r for r in rows if r["date"] >= since]
        return recent, (rows[0] if rows else None)

    # -- lesiones
    def injuries(self) -> list[dict]:
        from exams.models import Episode

        out = []
        for e in (self._window(Episode.objects.filter(player=self.p, template__slug="lesiones"), "started_at")
                  .order_by("-started_at")):
            first = (ExamResult.objects.filter(episode=e).order_by("recorded_at")
                     .values_list("result_data", flat=True).first()) or {}
            last = (ExamResult.objects.filter(episode=e).order_by("-recorded_at")
                    .values_list("result_data", flat=True).first()) or {}
            title = (e.title or "").split(" — ")
            what = first.get("diagnostico") or first.get("body_part_detail") or title[0] or "Lesión"
            zone = " ".join(x for x in (first.get("body_part") or (title[1] if len(title) > 1 else ""),
                                        (first.get("lado") or "").lower()) if x).strip()
            start = _local(e.started_at)
            end = _local(e.ended_at) if e.ended_at else None
            days = _num(last.get("dias_perdidos"))
            if days is None and end:
                days = (end - start).days
            out.append({"date": start, "what": what, "zone": zone, "days": days, "end": end})
        return out


def _context(category) -> dict:
    from dashboards import category_bands

    slugs = {s for s, *_ in TESTS} | {"pentacompartimental", "peso_talla", "notas_diarias_kinesiologico"}
    templates: dict[str, ExamTemplate] = {}
    for t in (ExamTemplate.objects.filter(department__club_id=category.club_id, slug__in=slugs)
              .order_by("-is_active_version")):
        templates.setdefault(t.slug, t)
    return {"templates": templates, "bands": category_bands.build(category.id)}


# ─── page frame ─────────────────────────────────────────────────────────────

class _Doc:
    """Canvas + cursor. Pages are buffered so the footer can say "de N"."""

    HEADER_H = 24 * mm
    FOOTER_H = 12 * mm

    def __init__(self, c, category, logo, generated: date):
        self.c = c
        self.category = category
        self.logo = logo
        self.generated = generated
        self.pages: list[dict] = []
        self.y = 0.0
        self.period: str = ""                 # the current section's "01/10/2026 – 31/10/2026"
        self.cargas_period: str = ""

    @property
    def top(self) -> float:
        return PAGE_H - self.HEADER_H - 6 * mm

    @property
    def bottom(self) -> float:
        return self.FOOTER_H + 6 * mm

    def new_page(self):
        if self.pages:
            self.c.showPage()
        self.pages.append({})
        c = self.c
        c.setFillColor(NAVY)
        c.rect(0, PAGE_H - self.HEADER_H, PAGE_W, self.HEADER_H, stroke=0, fill=1)
        c.setFillColor(RED)
        c.rect(0, PAGE_H - self.HEADER_H - 1.6 * mm, PAGE_W, 1.6 * mm, stroke=0, fill=1)
        x = M
        if self.logo is not None:
            c.drawImage(self.logo, M, PAGE_H - self.HEADER_H + 2 * mm, 20 * mm, 20 * mm,
                        preserveAspectRatio=True, mask="auto")
            x = M + 25 * mm
        club = self.category.club.name.upper()
        _text(c, x, PAGE_H - 10 * mm, f"CLUB {club}" if not club.startswith("CLUB") else club, 12.5, color=colors.white)
        formativo = "primer equipo" not in (self.category.name or "").lower()
        _text(c, x, PAGE_H - 15.5 * mm,
              f"{'Fútbol Formativo' if formativo else 'Primer Equipo'} · Departamento de Ciencias del Deporte",
              8.2, color=colors.white)
        _text(c, PAGE_W - M, PAGE_H - 10 * mm, "Informe club", 10, color=colors.white, anchor="right")
        self.y = self.top

    def need(self, h: float):
        """Start a new page if `h` does not fit below the cursor."""
        if self.y - h < self.bottom:
            self.new_page()


class _NumberedCanvas(rl_canvas.Canvas):
    """Canvas that defers each page until the end to print "de N"."""

    def __init__(self, *args, generated: date | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []
        self._generated = generated or date.today()

    def showPage(self):  # noqa: N802 — ReportLab API
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(MUTED)
            self.drawCentredString(PAGE_W / 2, 9 * mm,
                                   f"Página {self._pageNumber} de {total} · "
                                   f"Generado el {self._generated.strftime('%d-%m-%Y')}")
            super().showPage()
        super().save()


# ─── sections ───────────────────────────────────────────────────────────────

def _section_title(d: _Doc, title: str, gap_before: float = 8 * mm):
    c = d.c
    if d.period and "continuación" not in title:
        title = f"{title} ({d.period})"
    d.y -= gap_before
    _text(c, M, d.y, title, 12.5, color=TITLE)
    w = min(c.stringWidth(title.split(" · ")[0], "Helvetica", 12.5) + 2, 40 * mm)
    c.setStrokeColor(RED)
    c.setLineWidth(1.4)
    c.line(M, d.y - 2.6 * mm, M + w, d.y - 2.6 * mm)
    d.y -= 7.5 * mm


def _player_header(d: _Doc, data: _Data, matches: list[dict], photo):
    c, p = d.c, data.p
    top = d.y + 2 * mm
    ps = 27 * mm
    if photo is not None:
        c.drawImage(photo, M, top - ps, ps, ps, preserveAspectRatio=True, anchor="n", mask="auto")
    else:
        c.setFillColor(CELL)
        c.roundRect(M, top - ps, ps, ps, 4, stroke=0, fill=1)
        _text(c, M + ps / 2, top - ps / 2 - 5, (p.first_name[:1] + p.last_name[:1]).upper(), 18,
              "Helvetica-Bold", MUTED, "center")
    x = M + ps + 6 * mm
    _text(c, x, top - 7 * mm, f"{p.first_name} {p.last_name}".strip(), 17, color=TITLE)
    pos = (p.position.abbreviation or p.position.name) if p.position_id else "-"
    span = (f"Competiciones: {d.cargas_period}" if d.cargas_period else
            f"Últimas {len(matches)} competiciones ({_short(matches[0]['date'])} - {_short(matches[-1]['date'])})"
            if matches else "Sin partidos con GPS")
    _text(c, x, top - 13.5 * mm, f"Posición: {pos}  ·  Categoría: {_cat_short(p.category.name)}  ·  {span}", 8.4,
          color=colors.HexColor("#334155"))
    dob = p.date_of_birth
    age = f"{(d.generated - dob).days / 365.25:.1f}".replace(".", ",") + " años" if dob else "-"
    _text(c, x, top - 19 * mm,
          f"Fecha de nacimiento: {dob.strftime('%d/%m/%Y') if dob else '-'}  ·  Cuartil de nacimiento: "
          f"{birth_quartile(dob)}  ·  Edad: {age}", 8.4, color=colors.HexColor("#334155"))
    peso, talla = data.body()
    _text(c, x, top - 24.5 * mm,
          f"Peso: {_fmt(peso, 1) + ' kg' if peso else '-'}  ·  Talla: {_fmt(talla, 1) + ' cm' if talla else '-'}",
          8.4, color=colors.HexColor("#334155"))
    d.y = top - ps - 2 * mm


def _cargas(d: _Doc, matches: list[dict]):
    c = d.c
    n = len(matches)
    rows_h = 12.2 * mm
    table_h = 8 * mm + max(n, 1) * rows_h + 6 * mm
    d.need(14 * mm + table_h)
    _section_title(d, (f"Cargas realizadas · {n} competiciones" if d.period
                       else f"Cargas realizadas · últimas {n} competiciones"
                       + (f" ({_short(matches[0]['date'])} - {_short(matches[-1]['date'])})" if matches else "")))
    if not matches:
        _text(c, M, d.y, "Sin partidos con GPS en el período." if d.period else "Sin partidos con GPS registrados.",
              9, color=MUTED)
        d.y -= 8 * mm
        return
    cols = [("Dist. total (m)", "dist"), ("HSR >20 (m)", "hsr"), ("Sprint >25 (m)", "sprint"),
            ("ACC >3", "acc"), ("DEC <-3", "dec")]
    label_w = 36 * mm
    cw = (PAGE_W - 2 * M - label_w) / len(cols)
    for i, (lab, _) in enumerate(cols):
        _text(c, M + label_w + cw * i + cw / 2, d.y, lab, 7.6, color=MUTED, anchor="center")
    d.y -= 3 * mm
    for m in matches:
        y0 = d.y - rows_h + 1.5 * mm
        lines = ["MD Amistoso" if m["friendly"] else "MD"]
        if m["opponent"]:
            opp = m["opponent"].title()
            lines += _wrap(c, f"vs {opp}", label_w - 2, 7.6)[:2]
        lines.append(m["competition"] if (m["competition"] and not m["friendly"]) else _short(m["date"]))
        for j, ln in enumerate(lines[:4]):
            _text(c, M, d.y - 3.2 * mm - j * 3 * mm, ln, 7.8 if j < len(lines) - 1 else 7,
                  color=TITLE if j < len(lines) - 1 else MUTED)
        for i, (_, k) in enumerate(cols):
            x = M + label_w + cw * i + 1.2 * mm
            c.setFillColor(CELL)
            c.roundRect(x, y0, cw - 2.4 * mm, 10 * mm, 3, stroke=0, fill=1)
            _text(c, x + (cw - 2.4 * mm) / 2, y0 + 5 * mm - 2.2, _int(m[k]), 12, anchor="center")
        d.y -= rows_h
    vm = [f"MD {_fmt(m['vmax'], 1)}" for m in matches if m["vmax"] is not None]
    if vm:
        _text(c, M, d.y - 1 * mm, "Vmáx (km/h): " + "  ·  ".join(vm), 7.3, color=MUTED)
    if d.period and getattr(d, "left_out", 0) > 0:
        d.y -= 4 * mm
        _text(c, M, d.y - 1 * mm, f"Se muestran las últimas {n} competiciones del período; {d.left_out} anteriores "
                                  "no entran. Para verlas todas, agrupá por semana o mes.", 7, color=BAD)
    d.y -= 6 * mm

    # Distancia total y velocidad: bars (left axis) + HSR / sprint lines (right).
    chart_h = 28 * mm
    d.need(14 * mm + chart_h + 22 * mm)
    _section_title(d, "Distancia total y velocidad", 8 * mm)
    _legend(c, d.y, [("bar", C_DIST, "Distancia total (m)"), ("dot", C_HSR, "HSR >20 km/h (m)"),
                     ("dot", C_SPRINT, "Sprint >25 km/h (m)")],
            note="HSR >20 km/h y sprint >25 km/h (metros, eje derecho)")
    d.y -= 5 * mm
    _combo_chart(c, M, d.y - chart_h, PAGE_W - 2 * M, chart_h, matches)
    d.y -= chart_h + 13 * mm

    # Aceleraciones y desaceleraciones: grouped bars.
    chart_h = 26 * mm
    d.need(14 * mm + chart_h + 16 * mm)
    _section_title(d, "Aceleraciones y desaceleraciones", 6 * mm)
    _legend(c, d.y, [("bar", C_DIST, "ACC >3"), ("bar", C_DEC, "DEC <-3")])
    d.y -= 5 * mm
    _grouped_chart(c, M, d.y - chart_h, PAGE_W - 2 * M, chart_h, matches)
    d.y -= chart_h + 10 * mm


def _legend(c, y, items, note: str = ""):
    x = M + 10 * mm
    for kind, col, label in items:
        c.setFillColor(col)
        if kind == "bar":
            c.rect(x, y - 0.6 * mm, 3.4 * mm, 2.6 * mm, stroke=0, fill=1)
        else:
            c.circle(x + 1.7 * mm, y + 0.7 * mm, 1.5 * mm, stroke=0, fill=1)
        _text(c, x + 5 * mm, y, label, 6.8)
        x += 5 * mm + c.stringWidth(label, "Helvetica", 6.8) + 14 * mm
    if note:
        _text(c, PAGE_W - M, y, note, 6.4, color=C_HSR, anchor="right")


def _nice(v: float) -> float:
    """A round axis maximum ≥ v (1, 2, 2.5, 5, 10 × 10ⁿ)."""
    if v <= 0:
        return 1
    import math
    e = 10 ** math.floor(math.log10(v))
    for k in (1, 2, 2.5, 5, 10):
        if v <= k * e:
            return k * e
    return 10 * e


def _axis(c, x, y, w, h, top: float, side: str, color=MUTED):
    for i in range(5):
        v = top * i / 4
        yy = y + h * i / 4
        if side == "left":
            c.setStrokeColor(GRID)
            c.setLineWidth(0.5)
            c.line(x, yy, x + w, yy)
            _text(c, x - 2 * mm, yy - 2, _int(v), 6.4, color=color, anchor="right")
        else:
            _text(c, x + w + 2 * mm, yy - 2, _int(v), 6.4, color=color)


def _combo_chart(c, x, y, w, h, ms):
    left_top = _nice(max([m["dist"] or 0 for m in ms] + [1]))
    right_top = _nice(max([m["hsr"] or 0 for m in ms] + [m["sprint"] or 0 for m in ms] + [1]))
    _axis(c, x, y, w, h, left_top, "left")
    _axis(c, x, y, w, h, right_top, "right", C_HSR)
    n = len(ms)
    slot = w / n
    bw = min(slot * 0.4, 20 * mm)
    pts_h, pts_s = [], []
    for i, m in enumerate(ms):
        cx = x + slot * i + slot / 2
        bx = cx - bw / 2 - slot * 0.12
        if m["dist"] is not None:
            bh = h * m["dist"] / left_top
            c.setFillColor(C_DIST)
            c.rect(bx, y, bw, bh, stroke=0, fill=1)
            _text(c, bx + bw / 2, y + bh + 1.2 * mm, _int(m["dist"]), 6.6, anchor="center")
        lx_h, lx_s = cx - slot * 0.12 - bw / 2 - 3 * mm, cx + slot * 0.18
        if m["hsr"] is not None:
            pts_h.append((lx_h, y + h * m["hsr"] / right_top, m["hsr"]))
        if m["sprint"] is not None:
            pts_s.append((lx_s, y + h * m["sprint"] / right_top, m["sprint"]))
        _text(c, cx, y - 4 * mm, m.get("label") or "Partido", 6.8, anchor="center")
        _text(c, cx, y - 7.2 * mm, m.get("sub") or _short(m["date"]), 6.4, color=MUTED, anchor="center")
        if m["vmax"] is not None:
            _text(c, cx, y - 10.6 * mm, f"Vmáx {_fmt(m['vmax'], 1)} km/h", 6.4, anchor="center")
    for pts, col in ((pts_h, C_HSR), (pts_s, C_SPRINT)):
        c.setStrokeColor(col)
        c.setLineWidth(1.4)
        for a, b in zip(pts, pts[1:]):
            c.line(a[0], a[1], b[0], b[1])
        for px, py, v in pts:
            c.setFillColor(col)
            c.circle(px, py, 2 * mm, stroke=0, fill=1)
            _text(c, px, py + 3 * mm, _int(v), 6.2, color=col, anchor="center")


def _grouped_chart(c, x, y, w, h, ms):
    top = _nice(max([m["acc"] or 0 for m in ms] + [m["dec"] or 0 for m in ms] + [1]))
    _axis(c, x, y, w, h, top, "left")
    n = len(ms)
    slot = w / n
    bw = min(slot * 0.32, 16 * mm)
    for i, m in enumerate(ms):
        cx = x + slot * i + slot / 2
        for j, (k, col) in enumerate((("acc", C_DIST), ("dec", C_DEC))):
            v = m[k]
            if v is None:
                continue
            bx = cx - bw - 0.4 * mm if j == 0 else cx + 0.4 * mm
            bh = h * v / top
            c.setFillColor(col)
            c.rect(bx, y, bw, bh, stroke=0, fill=1)
            _text(c, bx + bw / 2, y + bh + 1.2 * mm, _int(v), 6.6, anchor="center")
        _text(c, cx, y - 4 * mm, m.get("label") or "Partido", 6.8, anchor="center")
        _text(c, cx, y - 7.2 * mm, m.get("sub") or _short(m["date"]), 6.4, color=MUTED, anchor="center")


def _level_style(t: dict) -> tuple[colors.Color, colors.Color]:
    """(fill, ink) of the result / level pills: the band's colour, solid for
    the top two levels (Excelente, Élite), a light tint below — the club's
    report."""
    if not t["color"]:
        return CELL, INK
    col = colors.HexColor(t["color"])
    if t["rank"] and t["n_bands"] and t["rank"] >= t["n_bands"] - 1:
        return col, colors.white
    return _tint(col, 0.78), _darken(col, 0.35)


def _condicion(d: _Doc, tests: list[dict]):
    c = d.c
    d.need(14 * mm + 8 * mm + max(len(tests), 1) * 7.2 * mm)
    _section_title(d, "Condición física · " + ("evaluaciones y categorización" if d.period
                                               else "últimas evaluaciones y categorización"))
    if not tests:
        _text(c, M, d.y, "Sin evaluaciones en el período." if d.period else "Sin evaluaciones registradas.",
              9, color=MUTED)
        d.y -= 8 * mm
        return
    xs = {"test": M, "fecha": M + 70 * mm, "res": M + 96 * mm, "lvl": M + 122 * mm, "vs": M + 160 * mm}
    for k, lab in (("test", "Test"), ("fecha", "Fecha"), ("res", "Resultado"), ("lvl", "Nivel"), ("vs", "vs anterior")):
        _text(c, xs[k], d.y, lab, 7.6, color=MUTED)
    d.y -= 7.5 * mm
    pill_w = 24 * mm
    for t in tests:
        fill, ink = _level_style(t)
        _text(c, xs["test"], d.y, _fit(c, t["label"], 68 * mm, 8.2), 8.2, color=TITLE)
        _text(c, xs["fecha"], d.y, _long(t["date"]), 8, color=INK)
        c.setFillColor(fill)
        c.roundRect(xs["res"] - 1 * mm, d.y - 2.2 * mm, pill_w, 6 * mm, 2.5, stroke=0, fill=1)
        _text(c, xs["res"] - 1 * mm + pill_w / 2, d.y - 0.2 * mm, f"{_fmt(t['value'], t['dec'])}{t['unit']}", 8.2,
              color=ink, anchor="center")
        if t["band"]:
            lw = 36 * mm
            c.setFillColor(fill)
            c.roundRect(xs["lvl"] - 1 * mm, d.y - 2.2 * mm, lw, 6 * mm, 2.5, stroke=0, fill=1)
            _text(c, xs["lvl"] - 1 * mm + lw / 2, d.y - 0.2 * mm, t["band"], 8.2, color=ink, anchor="center")
        if t["delta"] is not None:
            word = "igual" if not t["delta"] else ("mejor" if t["better"] else "peor")
            col = MUTED if not t["delta"] else (GOOD if t["better"] else BAD)
            _text(c, xs["vs"] + 1 * mm, d.y, f"{_signed(t['delta'], max(t['dec'], 0) if t['dec'] != -1 else -1)} {word}",
                  7.8, color=col)
        d.y -= 6.9 * mm
    d.y -= 2 * mm


COMP_COLS = [("peso", "Peso kg", 1, "neutral"), ("mm", "Músc.  kg", 1, "up"), ("mmp", "Músc.  %", 1, "up"),
             ("ma", "Adip.  kg", 1, "down"), ("map", "Adip.  %", 1, "down"), ("pl", "Pliegues  mm", 1, "down"),
             ("imo", "IMO", 2, "up")]


def _composicion(d: _Doc, last: dict | None, prev: dict | None):
    c = d.c
    d.need(14 * mm + 32 * mm)
    _section_title(d, "Composición corporal · " + ("evaluaciones" if d.period else "últimas evaluaciones"))
    if last is None:
        _text(c, M, d.y, "Sin mediciones de composición corporal" + (" en el período." if d.period else "."),
              9, color=MUTED)
        d.y -= 8 * mm
        return
    label_w = 32 * mm
    cw = (PAGE_W - 2 * M - label_w) / len(COMP_COLS)
    for i, (_, lab, _, _) in enumerate(COMP_COLS):
        _text(c, M + label_w + cw * i + cw / 2, d.y, lab, 7.2, color=MUTED, anchor="center")
    d.y -= 7 * mm

    def row(label, when, values, fills=None, inks=None):
        _text(c, M, d.y, label, 9, color=TITLE)
        if when:
            _text(c, M + 16 * mm, d.y, when, 6.8, color=MUTED)
        for i, v in enumerate(values):
            x = M + label_w + cw * i + 0.8 * mm
            c.setFillColor(fills[i] if fills else CELL)
            c.roundRect(x, d.y - 2.4 * mm, cw - 1.6 * mm, 6.2 * mm, 2.5, stroke=0, fill=1)
            _text(c, x + (cw - 1.6 * mm) / 2, d.y - 0.3 * mm, v, 8.2, color=inks[i] if inks else INK, anchor="center")
        d.y -= 6.4 * mm

    def short_date(iso):
        if not iso:
            return ""
        y, m, dd = (int(x) for x in iso[:10].split("-"))
        return f"{dd} {MONTHS[m - 1]} {str(y)[2:]}"

    if prev:
        row("Anterior", short_date(prev.get("date")), [_fmt(prev.get(k), dec) for k, _, dec, _ in COMP_COLS])
    row("Actual", short_date(last.get("date")), [_fmt(last.get(k), dec) for k, _, dec, _ in COMP_COLS])
    if prev:
        vals, fills, inks = [], [], []
        for k, _, dec, direction in COMP_COLS:
            a, b = last.get(k), prev.get(k)
            if a is None or b is None:
                vals.append("-"); fills.append(CELL); inks.append(INK)
                continue
            dv = round(a - b, dec)
            vals.append("=" if dv == 0 else _signed(dv, dec))
            if dv == 0 or direction == "neutral":
                fills.append(CELL); inks.append(INK)
            else:
                good = (dv > 0) == (direction == "up")
                fills.append(GOOD_BG if good else BAD_BG); inks.append(GOOD if good else BAD)
        row("Cambio", "", vals, fills, inks)
        _text(c, M, d.y + 2.5 * mm, "Medición actual contra la anterior. Verde = favorable (más músculo, menos grasa), "
                                    "rojo = desfavorable. Peso e IMO sin color de juicio en peso.", 6.4, color=MUTED)
    d.y -= 2 * mm


def _kine(d: _Doc, recent: list[dict], last: dict | None, span: tuple[date, date], period: bool):
    c = d.c
    shown = recent[:7]
    lines = []
    for r in shown:
        lines.append(_wrap(c, r["text"], 104 * mm, 7.8))
    h = 14 * mm + 10 * mm + sum(max(1, len(x)) * 4.2 * mm + 1.6 * mm for x in lines) + 10 * mm
    d.need(h)
    since, until = span
    if period:
        _section_title(d, "Atenciones kinésicas")
    else:
        _section_title(d, "Atenciones kinésicas · último mes")
        _text(c, M, d.y, f"Del {since.strftime('%d/%m/%Y')} al {until.strftime('%d/%m/%Y')}", 7, color=MUTED)
        d.y -= 7 * mm
    if not recent:
        _text(c, M, d.y, "Sin atenciones kinésicas " + ("en el período." if period else "en el último mes."),
              8.8, color=GOOD)
        d.y -= 5.5 * mm
        if last:
            _text(c, M, d.y, f"Última registrada: {last['date'].strftime('%d/%m/%Y')} · {last['tipo']} · {last['who']}",
                  7.6, color=MUTED)
            d.y -= 5 * mm
        return
    for r, ln in zip(shown, lines):
        _text(c, M, d.y, r["date"].strftime("%d/%m/%Y"), 7.8, color=TITLE)
        _text(c, M + 22 * mm, d.y, _fit(c, " · ".join(x for x in (r["tipo"], r["who"]) if x), 62 * mm, 7.8), 7.8)
        for j, t in enumerate(ln or [""]):
            _text(c, M + 80 * mm, d.y - j * 3.6 * mm, t, 7.8)
        d.y -= max(1, len(ln)) * 3.6 * mm + 1.8 * mm
    if len(recent) > len(shown):
        _text(c, M, d.y, f"+ {len(recent) - len(shown)} atenciones más "
                         + ("en el período" if period else "en el último mes"), 6.8, color=MUTED)
        d.y -= 4.4 * mm
    _text(c, M, d.y, f"Total {'del período' if period else 'último mes'}: {len(recent)} atenciones", 7.8, color=TITLE)
    d.y -= 4 * mm


def _lesiones(d: _Doc, inj: list[dict]):
    c = d.c
    shown = inj[:10]                          # the club's report: the 10 latest
    # Title + column heads + three rows must fit; the rest may flow on.
    d.need(14 * mm + 6 * mm + 3 * 5.4 * mm)
    _section_title(d, "Historial de lesiones" + ("" if d.period else " · histórico"))
    if not inj:
        _text(c, M, d.y, "Sin lesiones en el período." if d.period else "Sin lesiones registradas.", 8.8, color=MUTED)
        d.y -= 6 * mm
        return
    xs = [M, M + 22 * mm, M + 88 * mm, M + 128 * mm, M + 145 * mm]

    def heads():
        for x, lab in zip(xs, ("Fecha", "Lesión", "Zona", "Días", "Estado")):
            _text(c, x, d.y, lab, 7.4, color=MUTED)
        d.y -= 5.8 * mm

    heads()
    for r in shown:
        if d.y - 4.9 * mm < d.bottom:          # the table continues overleaf
            d.new_page()
            _section_title(d, "Historial de lesiones · continuación", 2 * mm)
            heads()
        _text(c, xs[0], d.y, r["date"].strftime("%d/%m/%Y"), 7.6)
        _text(c, xs[1], d.y, _fit(c, r["what"], 64 * mm, 7.6), 7.6)
        _text(c, xs[2], d.y, _fit(c, r["zone"].capitalize(), 38 * mm, 7.6), 7.6)
        _text(c, xs[3], d.y, _int(r["days"]), 7.6)
        if r["end"]:
            _text(c, xs[4], d.y, f"Alta {r['end'].strftime('%d/%m/%y')}", 7.6, color=GOOD)
        else:
            _text(c, xs[4], d.y, "En curso", 7.6, color=BAD)
        c.setStrokeColor(GRID)
        c.setLineWidth(0.5)
        c.line(M, d.y - 1.6 * mm, PAGE_W - M, d.y - 1.6 * mm)
        d.y -= 4.9 * mm
    if len(inj) > len(shown):
        _text(c, M, d.y, f"+ {len(inj) - len(shown)} lesiones anteriores", 6.8, color=MUTED)
        d.y -= 4.4 * mm
    d.need(10 * mm)
    worst = max((r for r in inj if r["days"] is not None), key=lambda r: r["days"], default=None)
    if worst:
        _text(c, M, d.y - 0.5 * mm, "Lesión más grave", 7.8, color=TITLE)
        _text(c, M + 30 * mm, d.y - 0.5 * mm,
              _fit(c, f"{worst['what']} · {worst['zone'].capitalize()} · {worst['date'].strftime('%d/%m/%Y')} · "
                      f"{_int(worst['days'])} días", PAGE_W - 2 * M - 30 * mm, 7.6), 7.6)
        d.y -= 5 * mm
    zones: dict[str, list[date]] = defaultdict(list)
    for r in inj:
        if r["zone"]:
            zones[r["zone"].capitalize()].append(r["date"])
    rep = [(z, ds) for z, ds in zones.items() if len(ds) > 1]
    for i, (z, ds) in enumerate(sorted(rep, key=lambda x: -len(x[1]))):
        if i == 0:
            _text(c, M, d.y, "Lesiones repetidas", 7.8, color=TITLE)
        when = ", ".join(f"{dd.month:02d}/{dd.year}" for dd in sorted(ds))
        _text(c, M + 30 * mm, d.y, f"{z}: {len(ds)} lesiones ({when})", 7.6, color=colors.HexColor("#c2410c"))
        d.y -= 4.6 * mm


def _stat_lines(values: dict[str, float | None], stats: list[str], dec: int, fmt=None) -> list[str]:
    fmt = fmt or (lambda v: _fmt(v, dec) if dec != 0 else _int(v))
    if len(stats) == 1:
        v = values.get(stats[0])
        return ["-" if v is None else fmt(v)]
    return [f"{STATS[k]} {'-' if values.get(k) is None else fmt(values[k])}" for k in stats]


def _cargas_grouped(d: _Doc, matches: list[dict], gran: str, stats: list[str]):
    """Cargas by week / month / semester: each metric's chosen statistics
    per period; the charts plot the first one."""
    c = d.c
    groups = group(matches, gran)
    cols = [("Dist. total (m)", "dist"), ("HSR >20 (m)", "hsr"), ("Sprint >25 (m)", "sprint"),
            ("ACC >3", "acc"), ("DEC <-3", "dec"), ("Vmáx (km/h)", "vmax")]
    stat_names = " · ".join({"mean": "promedio", "max": "máximo", "min": "mínimo", "sum": "total"}[k] for k in stats)
    rows_h = max(10 * mm, len(stats) * 3.6 * mm + 4 * mm) + 2 * mm
    d.need(14 * mm + 8 * mm + max(len(groups), 1) * rows_h)
    gname = {"semana": "semana", "mes": "mes", "semestre": "semestre"}[gran]
    _section_title(d, f"Cargas realizadas · por {gname}, {stat_names}")
    if not groups:
        _text(c, M, d.y, "Sin partidos con GPS en el período.", 9, color=MUTED)
        d.y -= 8 * mm
        return
    label_w = 36 * mm
    cw = (PAGE_W - 2 * M - label_w) / len(cols)
    for i, (lab, _) in enumerate(cols):
        _text(c, M + label_w + cw * i + cw / 2, d.y, lab, 7.4, color=MUTED, anchor="center")
    d.y -= 3 * mm
    chart_points = []
    for g in groups:
        if d.y - rows_h < d.bottom:
            d.new_page()
            _section_title(d, "Cargas realizadas · continuación", 2 * mm)
        n = len(g["items"])
        _text(c, M, d.y - 4 * mm, g["label"], 8, color=TITLE)
        _text(c, M, d.y - 7.2 * mm, " · ".join(x for x in (g["sub"], f"{n} partido{'s' if n != 1 else ''}") if x),
              6.8, color=MUTED)
        point = {"date": g["items"][0]["date"], "label": g["label"], "sub": g["sub"] or f"{n} part."}
        for i, (_, k) in enumerate(cols):
            vals = {s_: stat([m[k] for m in g["items"]], s_) for s_ in stats}
            point[k] = vals[stats[0]]
            x = M + label_w + cw * i + 1 * mm
            c.setFillColor(CELL)
            c.roundRect(x, d.y - rows_h + 2 * mm, cw - 2 * mm, rows_h - 2 * mm, 3, stroke=0, fill=1)
            lines = _stat_lines(vals, stats, 1 if k == "vmax" else 0)
            size = 11 if len(lines) == 1 else 7.4
            y0 = d.y - (rows_h - 2 * mm) / 2 - (len(lines) - 1) * 1.8 * mm - 0.5 * mm
            for j, ln in enumerate(lines):
                _text(c, x + (cw - 2 * mm) / 2, y0 + (len(lines) - 1 - j) * 3.6 * mm, ln, size, anchor="center")
        chart_points.append(point)
        d.y -= rows_h
    d.y -= 4 * mm
    first = {"mean": "promedio", "max": "máximo", "min": "mínimo", "sum": "total"}[stats[0]]
    chart_h = 28 * mm
    d.need(14 * mm + chart_h + 22 * mm)
    _section_title(d, f"Distancia total y velocidad · {first} por {gname}", 8 * mm)
    _legend(c, d.y, [("bar", C_DIST, "Distancia total (m)"), ("dot", C_HSR, "HSR >20 km/h (m)"),
                     ("dot", C_SPRINT, "Sprint >25 km/h (m)")],
            note="HSR >20 km/h y sprint >25 km/h (metros, eje derecho)")
    d.y -= 5 * mm
    _combo_chart(c, M, d.y - chart_h, PAGE_W - 2 * M, chart_h, chart_points)
    d.y -= chart_h + 13 * mm
    chart_h = 26 * mm
    d.need(14 * mm + chart_h + 16 * mm)
    _section_title(d, f"Aceleraciones y desaceleraciones · {first} por {gname}", 6 * mm)
    _legend(c, d.y, [("bar", C_DIST, "ACC >3"), ("bar", C_DEC, "DEC <-3")])
    d.y -= 5 * mm
    _grouped_chart(c, M, d.y - chart_h, PAGE_W - 2 * M, chart_h, chart_points)
    d.y -= chart_h + 10 * mm


MAX_PERIOD_COLS = 6


def _condicion_grouped(d: _Doc, series: list[dict], gran: str, stats: list[str]):
    """Tests × periods: each cell the chosen statistics of that period's
    readings, coloured by the level of the first one (the category's bands)."""
    from exams.bands import band_for_value, band_rank

    c = d.c
    keys: dict[tuple, tuple[str, str]] = {}
    for t in series:
        for r in t["readings"]:
            k, label, sub = bucket(r["date"], gran)
            keys[k] = (label, sub)
    all_periods = sorted(keys)
    rows_h = max(6.4 * mm, len(stats) * 3.4 * mm + 2.6 * mm)
    d.need(14 * mm + 10 * mm + max(len(series), 1) * rows_h)
    gname = {"mes": "mes", "semestre": "semestre", "semana": "semana"}[gran]
    _section_title(d, f"Condición física · por {gname}")
    if not series or not all_periods:
        _text(c, M, d.y, "Sin evaluaciones en el período.", 9, color=MUTED)
        d.y -= 8 * mm
        return
    label_w = 64 * mm
    by_test = []
    for t in series:
        by = defaultdict(list)
        for r in t["readings"]:
            by[bucket(r["date"], gran)[0]].append(r["value"])
        by_test.append((t, by))
    # More periods than fit across the page: the table goes on in further
    # blocks, oldest first — never drop a period (a test measured only in the
    # first months would read as missing).
    chunks = [all_periods[i:i + MAX_PERIOD_COLS] for i in range(0, len(all_periods), MAX_PERIOD_COLS)]
    for n_chunk, periods in enumerate(chunks):
        rows = [(t, by) for t, by in by_test if any(by.get(k) for k in periods)]
        head_h = 9 * mm if gran == "semana" else 6 * mm
        if n_chunk:
            d.y -= 3 * mm
            d.need(head_h + max(len(rows), 1) * rows_h)
        cw = (PAGE_W - 2 * M - label_w) / MAX_PERIOD_COLS
        _text(c, M, d.y, "Test", 7.4, color=MUTED)
        for i, k in enumerate(periods):
            lab, sub = keys[k]
            _text(c, M + label_w + cw * i + cw / 2, d.y, lab, 7.2, color=MUTED, anchor="center")
            if gran == "semana" and sub:
                _text(c, M + label_w + cw * i + cw / 2, d.y - 3.2 * mm, sub, 6.2, color=MUTED, anchor="center")
        d.y -= head_h
        for t, by in rows:
            if d.y - rows_h < d.bottom:
                d.new_page()
                _section_title(d, "Condición física · continuación", 2 * mm)
            _text(c, M, d.y - rows_h / 2 + 1, _fit(c, t["label"], label_w - 3 * mm, 8), 8, color=TITLE)
            for i, k in enumerate(periods):
                vals = by.get(k)
                if not vals:
                    continue
                sv = {s_: stat(vals, s_) for s_ in stats}
                band = band_for_value(sv[stats[0]], t["bands"]) if t["bands"] else None
                fill, ink = _level_style({"color": (band or {}).get("color"),
                                          "rank": band_rank(band, t["bands"]) if band else None,
                                          "n_bands": len(t["bands"])})
                x = M + label_w + cw * i + 0.8 * mm
                c.setFillColor(fill)
                c.roundRect(x, d.y - rows_h + 0.8 * mm, cw - 1.6 * mm, rows_h - 1.4 * mm, 2.5, stroke=0, fill=1)
                lines = _stat_lines(sv, stats, t["dec"], lambda v, dd=t["dec"]: _fmt(v, dd))
                y0 = d.y - rows_h / 2 - (len(lines) - 1) * 1.7 * mm - 0.4 * mm
                for j, ln in enumerate(lines):
                    _text(c, x + (cw - 1.6 * mm) / 2, y0 + (len(lines) - 1 - j) * 3.4 * mm, ln,
                          8 if len(lines) == 1 else 7, color=ink, anchor="center")
            d.y -= rows_h
    _text(c, M, d.y - 1 * mm, "Color = nivel del primer estadístico según las bandas de la categoría. "
                              "Cada bloque muestra sólo los tests evaluados en esos períodos.", 6.4, color=MUTED)
    d.y -= 4 * mm


def _composicion_grouped(d: _Doc, ms: list[dict], gran: str, stats: list[str]):
    c = d.c
    groups = group(ms, gran, "day")
    rows_h = max(9 * mm, len(stats) * 3.4 * mm + 2.6 * mm)    # label + "n mediciones"
    d.need(14 * mm + 10 * mm + max(len(groups), 1) * rows_h)
    gname = {"mes": "mes", "semestre": "semestre", "semana": "semana"}[gran]
    _section_title(d, f"Composición corporal · por {gname}")
    if not groups:
        _text(c, M, d.y, "Sin mediciones de composición corporal en el período.", 9, color=MUTED)
        d.y -= 8 * mm
        return
    label_w = 32 * mm
    cw = (PAGE_W - 2 * M - label_w) / len(COMP_COLS)
    for i, (_, lab, _, _) in enumerate(COMP_COLS):
        _text(c, M + label_w + cw * i + cw / 2, d.y, lab, 7.2, color=MUTED, anchor="center")
    d.y -= 6 * mm
    for g in groups:
        if d.y - rows_h < d.bottom:
            d.new_page()
            _section_title(d, "Composición corporal · continuación", 2 * mm)
        n = len(g["items"])
        _text(c, M, d.y - rows_h / 2 + 1.6 * mm, g["label"], 8, color=TITLE)
        _text(c, M, d.y - rows_h / 2 - 1.6 * mm, f"{n} medición{'es' if n != 1 else ''}", 6.6, color=MUTED)
        for i, (k, _, dec, _) in enumerate(COMP_COLS):
            sv = {s_: stat([m.get(k) for m in g["items"]], s_) for s_ in stats}
            x = M + label_w + cw * i + 0.8 * mm
            c.setFillColor(CELL)
            c.roundRect(x, d.y - rows_h + 0.8 * mm, cw - 1.6 * mm, rows_h - 1.4 * mm, 2.5, stroke=0, fill=1)
            lines = _stat_lines(sv, stats, dec, lambda v, dd=dec: _fmt(v, dd))
            y0 = d.y - rows_h / 2 - (len(lines) - 1) * 1.7 * mm - 0.4 * mm
            for j, ln in enumerate(lines):
                _text(c, x + (cw - 1.6 * mm) / 2, y0 + (len(lines) - 1 - j) * 3.4 * mm, ln,
                      8.2 if len(lines) == 1 else 7, anchor="center")
        d.y -= rows_h
    d.y -= 2 * mm


def _counts_table(d: _Doc, title: str, head: list[str], rows: list[list[str]], widths: list[float]):
    c = d.c
    d.need(14 * mm + 8 * mm + max(len(rows), 1) * 5 * mm)
    _section_title(d, title)
    xs, x = [], M
    for w in widths:
        xs.append(x)
        x += w * mm
    for xx, h in zip(xs, head):
        _text(c, xx, d.y, h, 7.4, color=MUTED)
    d.y -= 5.6 * mm
    for r in rows:
        if d.y - 5 * mm < d.bottom:
            d.new_page()
        for j, (xx, v) in enumerate(zip(xs, r)):
            _text(c, xx, d.y, _fit(c, v, widths[j] * mm - 2 * mm, 7.6), 7.6, color=TITLE if j == 0 else INK)
        c.setStrokeColor(GRID)
        c.setLineWidth(0.5)
        c.line(M, d.y - 1.6 * mm, PAGE_W - M, d.y - 1.6 * mm)
        d.y -= 5 * mm
    d.y -= 2 * mm


def _kine_grouped(d: _Doc, recent: list[dict], gran: str):
    from collections import Counter

    gname = {"semana": "semana", "mes": "mes", "semestre": "semestre"}[gran]
    rows = []
    for g in group(recent, gran):
        tipos = Counter(r["tipo"] or "Sin tipo" for r in g["items"])
        who = Counter(r["who"] for r in g["items"] if r["who"])
        rows.append([" · ".join(x for x in (g["label"], g["sub"]) if x), str(len(g["items"])),
                     ", ".join(f"{t} ({n})" for t, n in tipos.most_common(3)),
                     ", ".join(w for w, _ in who.most_common(2))])
    if not rows:
        rows = [["Sin atenciones en el período", "0", "", ""]]
    _counts_table(d, f"Atenciones kinésicas · por {gname}", ["Período", "Atenciones", "Tipo", "Tratante"],
                  rows, [52, 22, 76, 36])


def _lesiones_grouped(d: _Doc, inj: list[dict], gran: str):
    gname = {"semana": "semana", "mes": "mes", "semestre": "semestre"}[gran]
    rows = []
    for g in group(inj, gran):
        days = [r["days"] for r in g["items"] if r["days"] is not None]
        zones = sorted({r["zone"].capitalize() for r in g["items"] if r["zone"]})
        rows.append([" · ".join(x for x in (g["label"], g["sub"]) if x), str(len(g["items"])),
                     _int(sum(days)) if days else "-", ", ".join(zones)])
    if rows:
        _counts_table(d, f"Lesiones · por {gname}", ["Período", "Lesiones", "Días perdidos", "Zonas"],
                      rows, [52, 22, 28, 84])


def _comentario(d: _Doc, text: str, author: str, today: date):
    """The doctor's note typed in the export screen, as written."""
    c = d.c
    paras = [p.strip() for p in text.replace("\r", "").split("\n")]
    lines: list[str] = []
    for p in paras:
        lines += _wrap(c, p, PAGE_W - 2 * M - 10 * mm, 8.6) if p else [""]
    line_h = 4.3 * mm
    box_h = len(lines) * line_h + 12 * mm
    d.need(14 * mm + min(box_h, 60 * mm))
    _section_title(d, "Comentario médico")
    i = 0
    while i < len(lines):
        room = int((d.y - d.bottom - 10 * mm) // line_h)
        if room < 2:
            d.new_page()
            _section_title(d, "Comentario médico · continuación", 2 * mm)
            continue
        chunk = lines[i:i + room]
        h = len(chunk) * line_h + 6 * mm
        c.setFillColor(colors.HexColor("#f5f7fb"))
        c.setStrokeColor(colors.HexColor("#c7d2fe"))
        c.setLineWidth(0.6)
        c.roundRect(M, d.y - h + 3 * mm, PAGE_W - 2 * M, h, 4, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.rect(M, d.y - h + 3 * mm, 1.4 * mm, h, stroke=0, fill=1)
        y = d.y - 1.5 * mm
        for ln in chunk:
            _text(c, M + 5 * mm, y, ln, 8.6)
            y -= line_h
        d.y -= h + 1 * mm
        i += len(chunk)
    sign = " · ".join(x for x in (author, today.strftime("%d/%m/%Y")) if x)
    _text(c, PAGE_W - M, d.y, sign, 7.4, color=MUTED, anchor="right")
    d.y -= 6 * mm


# ─── entry point ────────────────────────────────────────────────────────────

def render_informe_plantel(players: list[Player], category, *, sections: list[str] | None = None,
                           n_matches: int = 5, today: date | None = None,
                           ranges: dict[str, tuple[date | None, date | None]] | None = None,
                           comments: dict[str, str] | None = None, author: str = "",
                           views: dict[str, dict] | None = None) -> bytes:
    """One PDF, the selected sections for each player, in the given order.
    `ranges` ({section: (desde, hasta)}) keeps each section inside its own
    period — none means its default (last N matches, last month…); `comments`
    ({player_id: text}) adds the "Comentario médico" box at each one's end."""
    today = today or timezone.localdate()
    sections = [s for s in (sections or DEFAULT_SECTIONS) if s in SECTIONS]
    ctx = _context(category)
    logo = _image(category.club.logo, None) if getattr(category.club, "logo", None) else None

    buf = io.BytesIO()
    c = _NumberedCanvas(buf, pagesize=A4, generated=today)
    c.setTitle(f"Informe de plantel — {category.name}")
    d = _Doc(c, category, logo, today)
    ranges = {k: v for k, v in (ranges or {}).items() if k in SECTIONS and (v[0] or v[1])}

    def label(sec: str) -> str:
        if sec not in ranges:
            return ""
        a, b = ranges[sec]
        return f"{a.strftime('%d/%m/%Y') if a else 'inicio'} – {(b or today).strftime('%d/%m/%Y')}"

    d.cargas_period = label("cargas")
    # How each area with a period is shown: {"granularity", "stats"}.
    views = {k: v for k, v in (views or {}).items() if k in ranges}

    def view(sec: str) -> tuple[str, list[str]]:
        v = views.get(sec) or {}
        gran = v.get("granularity") if v.get("granularity") in GRANULARITIES else "detalle"
        st = [x for x in (v.get("stats") or []) if x in STATS and (x != "sum" or sec == "cargas")] or ["mean"]
        return gran, st
    comments = {str(k): v for k, v in (comments or {}).items() if v and str(v).strip()}

    for p in players:
        # With a period, every match in it (up to 10); without, the last N.
        cargas_gran, cargas_stats = view("cargas")
        data = _Data(p, ctx, (500 if cargas_gran != "detalle" else 10) if "cargas" in ranges else n_matches, today)

        def use(sec: str):
            data.date_from, data.date_to = ranges.get(sec, (None, None))
            d.period = label(sec)

        d.new_page()                          # every player starts a page
        use("cargas")
        matches = data.matches()              # the header names their span
        d.period = ""
        data.date_from = data.date_to = None
        _player_header(d, data, matches, _image(p.photo, p.photo_url))
        if "cargas" in sections:
            use("cargas")
            if cargas_gran != "detalle":
                _cargas_grouped(d, matches, cargas_gran, cargas_stats)
            else:
                d.left_out = data.matches_left_out if "cargas" in ranges else 0
                _cargas(d, matches)
        if "condicion" in sections:
            use("condicion")
            gran, st = view("condicion")
            if gran != "detalle":
                _condicion_grouped(d, data.test_series(), gran, st)
            else:
                _condicion(d, data.tests())
        if "composicion" in sections:
            use("composicion")
            gran, st = view("composicion")
            if gran != "detalle":
                _composicion_grouped(d, data.measurements(), gran, st)
            else:
                last, prev = data.composition()
                _composicion(d, last, prev)
        if "kine" in sections:
            use("kine")
            recent, last = data.kine()
            gran, _ = view("kine")
            if gran != "detalle":
                _kine_grouped(d, recent, gran)
            else:
                _kine(d, recent, last, data.kine_span(), bool(d.period))
        if "lesiones" in sections:
            use("lesiones")
            inj = data.injuries()
            gran, _ = view("lesiones")
            if gran != "detalle":
                _lesiones_grouped(d, inj, gran)
            _lesiones(d, inj)
        d.period = ""
        if comments.get(str(p.pk)):
            _comentario(d, comments[str(p.pk)], author, today)
    if not d.pages:
        d.new_page()
    c.showPage()
    c.save()
    return buf.getvalue()
