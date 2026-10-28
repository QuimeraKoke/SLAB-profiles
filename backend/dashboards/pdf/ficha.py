"""Ficha integral — the one-page infographic of a player, per department or general.

Modelled on the formativo's own sheets ("Ficha integral de condición física y
composición corporal"): A4 landscape, a navy header with the player's chips,
coloured sections of cards — each a test's evolution, its last value and the
band it falls in, with one line of reading — and at the bottom the player's
standardised profile (radar) next to a synthesis: strengths, what to
prioritise, and short / medium / long term.

How a metric is judged, in order:
  1. the category's bands (`category_bands`), else the field's own bands — the
     club's scale is the authority when there is one;
  2. otherwise its percentile among the category's players (latest value each,
     `direction_of_good` respected) — needs `MIN_PEERS` to say anything.
The radar always uses the percentile: it puts every axis on the same 0–100.

The text is built from those judgements, deterministically: no model call, so
the same data always prints the same words and costs nothing.

Departments without a spec (notes-only ones) have no ficha.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from core.models import Player
from dashboards import category_bands
from exams.bands import band_for_value
from exams.models import ExamResult, ExamTemplate

_TZ = ZoneInfo("America/Santiago")
PAGE_W, PAGE_H = landscape(A4)
MARGIN = 9 * mm
MIN_PEERS = 5
MAX_POINTS = 8
STALE_DAYS = 365

NAVY = colors.HexColor("#0b4a8b")
NAVY_DARK = colors.HexColor("#083a6e")
RED = colors.HexColor("#e5232b")
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
CARD_BG = colors.HexColor("#f3f6fa")
CARD_EDGE = colors.HexColor("#d6dde8")
SECTION_COLORS = {
    "blue": colors.HexColor("#0b5aa0"),
    "purple": colors.HexColor("#6b2fa0"),
    "teal": colors.HexColor("#0f766e"),
    "red": colors.HexColor("#b42318"),
    "green": colors.HexColor("#15803d"),
    "slate": colors.HexColor("#334155"),
}
POS_GREEN = colors.HexColor("#15803d")
NEG_RED = colors.HexColor("#b42318")

# Every scale the club uses, on one ladder: 0 = worst … 6 = best. A label the
# ladder doesn't know is judged by its position (bands listed worst→best).
_LADDER = {
    "muy deficiente": 0, "deficiente": 1, "regular": 2, "aceptable": 2.5,
    "bueno": 3.5, "muy bueno": 4, "excelente": 5, "elite": 6, "élite": 6,
    "elevado": 0.5, "bajo": 0.5, "vigilar": 1.5, "normal": 3.5, "estable": 3.5,
    "alta variabilidad": 0.5, "profesional / bueno": 4,
}
STRONG_AT = 4      # Muy bueno and up
WEAK_AT = 1        # Deficiente and down


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class M:
    """One card: `template` slug + `key`; `title` on the card, `short` on the
    radar and in the text."""
    template: str
    key: str
    title: str
    short: str
    unit: str | None = None
    decimals: int = 2
    per_match_min: float | None = None   # gps_partido: skip short appearances
    # Overrides the field's `direction_of_good` — GPS fields are "neutral" in
    # the template (a recovery session SHOULD be low), but in a match more
    # running is the better reading.
    direction: str | None = None


@dataclass(frozen=True)
class Section:
    title: str
    color: str
    metrics: tuple[M, ...] = ()
    subtitle: str = ""
    kind: str = "cards"   # cards | injuries | season


CONDICION = Section("Condición física", "blue", (
    M("fuerza", "fr", "Fuerza relativa · 1RM/PC", "fuerza relativa", "x PC"),
    M("resistencia", "vo2_max", "Resistencia · Yo-Yo VO2máx", "resistencia", "ml/kg/min"),
    M("carreras", "t10_best", "Aceleración · 10 metros", "aceleración", "s"),
    M("carreras", "t30_best", "Velocidad · 30 metros", "velocidad", "s"),
    M("neuromuscular", "cmj_best", "Saltabilidad · CMJ", "saltabilidad", "cm", 1),
), "Mejor por evaluación | bandas de la categoría")

CONDICION_2 = Section("Fuerza, potencia y cambio de dirección", "blue", (
    M("fuerza", "rm_estimado", "Fuerza · 1RM Back Squat", "fuerza máxima", "kg", 1),
    M("neuromuscular", "tiro_best", "Potencia de tiro", "potencia de tiro", "km/h", 1),
    M("carreras", "cod_der_best", "COD 505 · derecha", "cambio de dirección (der.)", "s"),
    M("carreras", "cod_izq_best", "COD 505 · izquierda", "cambio de dirección (izq.)", "s"),
    M("resistencia", "palier", "Yo-Yo IR1 · palier", "palier Yo-Yo", "", 1),
))

COMPOSICION = Section("Composición corporal", "purple", (
    M("pentacompartimental", "suma_pliegues", "Sumatoria 6 pliegues", "pliegues", "mm", 1),
    M("pentacompartimental", "masa_adiposa_pct", "% Masa adiposa", "masa adiposa", "%"),
    M("pentacompartimental", "masa_muscular_pct", "% Masa muscular", "masa muscular", "%"),
), "Método pentacompartimental | bandas del club")

GPS = Section("GPS de partido", "teal", (
    M("gps_partido", "tot_dist", "Distancia total", "volumen en partido", "m", 0, 45, "up"),
    M("gps_partido", "hsr", "HSR > 19,8 km/h", "carrera de alta intensidad", "m", 0, 45, "up"),
    M("gps_partido", "mpm", "Metros por minuto", "intensidad (m/min)", "m/min", 1, 45, "up"),
    M("gps_partido", "sprint_dist", "Distancia sprint", "sprint", "m", 0, 45, "up"),
    M("gps_partido", "max_vel", "Velocidad máxima", "velocidad máxima", "km/h", 1, 45, "up"),
), "Por partido con ≥ 45 min | percentil en la categoría")

SPECS: dict[str, tuple[str, list[Section]]] = {
    "fisico": ("Ficha física", [CONDICION, CONDICION_2, GPS]),
    "nutricional": ("Ficha nutricional", [
        Section("Composición corporal", "purple", (
            *COMPOSICION.metrics,
            M("pentacompartimental", "imo", "Índice músculo/óseo", "relación músculo/hueso", "", 2),
        ), COMPOSICION.subtitle),
        Section("Antropometría", "purple", (
            M("pentacompartimental", "peso", "Peso", "peso", "kg", 1),
            M("pentacompartimental", "talla", "Talla", "talla", "cm", 1),
            M("pentacompartimental", "masa_muscular", "Masa muscular", "masa muscular (kg)", "kg", 1),
            M("pentacompartimental", "masa_adiposa", "Masa adiposa", "masa adiposa (kg)", "kg", 1),
        ), "Percentil en la categoría"),
    ]),
    "psicosocial": ("Ficha psicosocial", [
        Section("Fatiga central", "slate", (
            M("fatiga_central", "cff_mean", "CFF media", "CFF", "Hz", 1),
            M("fatiga_central", "delta_basal_pct", "Variación vs basal", "variación vs basal", "%", 1),
            M("fatiga_central", "ea", "Estado de ánimo", "estado de ánimo", "/10", 1),
            M("fatiga_central", "pr", "Percepción de recuperación", "recuperación percibida", "/10", 1),
        ), "Frecuencia crítica de fusión y autorreporte"),
    ]),
    "medico": ("Ficha médica", [
        Section("Evaluación neuromuscular", "red", (
            M("cmj", "jump_height", "CMJ · altura", "salto (CMJ)", "cm", 1),
            M("cmj", "rsi_modified", "CMJ · RSI mod.", "reactividad (RSI)", "m/s"),
            M("imtp", "peak_force_bodymass", "IMTP · fuerza/peso", "fuerza isométrica", "N/kg", 1),
            M("nordico", "left_max", "Nórdico · izquierda", "isquios izq.", "N", 0),
            M("nordico", "right_max", "Nórdico · derecha", "isquios der.", "N", 0),
        ), "ForceDecks / NordBord | percentil en la categoría"),
        Section("Marcadores", "red", (
            M("ck", "valor", "CK", "CK", "U/L", 0),
            M("hip_adab", "squeeze_imbalance", "Aductores · asimetría", "asimetría aductores", "%", 1),
            M("nordico", "imbalance", "Nórdico · asimetría", "asimetría isquios", "%", 1),
        ), "Último registro"),
        Section("Historial de lesiones", "red", kind="injuries"),
    ]),
    "tactico": ("Ficha táctica", [
        Section("Temporada", "green", kind="season"),
        Section("Partido a partido", "green", (
            M("ficha_partido", "minutos", "Minutos por partido", "minutos", "min", 0),
            M("rendimiento_de_partido", "rating", "Calificación", "calificación", "/10", 1),
            M("gps_partido", "tot_dist", "GPS · distancia total", "volumen en partido", "m", 0,
              45, "up"),
            M("gps_partido", "hsr", "GPS · HSR", "alta intensidad", "m", 0, 45, "up"),
        ), "Planilla oficial y GPS | percentil en la categoría"),
    ]),
}
GENERAL = ("Ficha integral", [CONDICION, COMPOSICION, Section("Disponibilidad y competencia", "green",
                                                                kind="season")])


def has_ficha(department_slug: str | None) -> bool:
    return not department_slug or department_slug in SPECS


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class Reading:
    m: M
    points: list[tuple[date, float]] = field(default_factory=list)
    band: dict | None = None
    level: float | None = None      # 0–6 on the ladder, when banded
    percentile: float | None = None  # 0–100 among the category
    direction: str = "neutral"
    unit: str = ""

    @property
    def last(self) -> float | None:
        return self.points[-1][1] if self.points else None

    @property
    def prev(self) -> float | None:
        return self.points[-2][1] if len(self.points) > 1 else None

    @property
    def verdict(self) -> str | None:
        """"strong" / "weak" / None — band first, percentile otherwise."""
        if self.level is not None:
            return "strong" if self.level >= STRONG_AT else "weak" if self.level <= WEAK_AT else None
        if self.percentile is not None:
            return "strong" if self.percentile >= 75 else "weak" if self.percentile <= 25 else None
        return None


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _field(t: ExamTemplate, key: str) -> dict:
    return next((f for f in (t.config_schema or {}).get("fields", [])
                 if isinstance(f, dict) and f.get("key") == key), {})


def _level(band: dict, bands: list[dict]) -> float:
    label = str(band.get("label") or "").strip().lower()
    for name, v in _LADDER.items():
        if label == name or label.startswith(name + " ("):
            return v
    if label.startswith("alerta"):
        return 0.5
    i = bands.index(band) if band in bands else 0
    return 6 * i / max(1, len(bands) - 1)


def period_start(today: date | None = None) -> datetime:
    """Reports read the current year and the previous one (club's call,
    2026-10-28): long enough to see a trend across seasons, short enough that a
    2023 test doesn't set a category percentile or a player's "last" value."""
    today = today or datetime.now(_TZ).date()
    return datetime(today.year - 1, 1, 1, tzinfo=_TZ)


class _Data:
    def __init__(self, player: Player):
        self.desde = period_start()
        self.player = player
        self.cat = player.category
        self.club_id = self.cat.club_id
        self._tpl: dict[str, ExamTemplate | None] = {}
        self.cat_bands = category_bands.build(self.cat.id)
        self.peer_ids = list(Player.objects.filter(category=self.cat, is_active=True)
                             .values_list("id", flat=True))

    def template(self, slug: str) -> ExamTemplate | None:
        if slug not in self._tpl:
            self._tpl[slug] = (ExamTemplate.objects
                               .filter(slug=slug, department__club_id=self.club_id)
                               .order_by("-is_active_version").first())
        return self._tpl[slug]

    def reading(self, m: M) -> Reading:
        t = self.template(m.template)
        r = Reading(m)
        if t is None:
            return r
        f = _field(t, m.key)
        r.direction = m.direction or f.get("direction_of_good") or "neutral"
        r.unit = m.unit if m.unit is not None else (f.get("unit") or "")
        qs = ExamResult.objects.filter(template__family_id=t.family_id, player=self.player,
                                       recorded_at__gte=self.desde)
        if m.per_match_min:
            qs = qs.filter(result_data__tot_dur__gte=m.per_match_min)
        by_day: dict[date, float] = {}
        for when, data in qs.order_by("recorded_at").values_list("recorded_at", "result_data"):
            v = _num((data or {}).get(m.key))
            if v is None:
                continue
            d = when.astimezone(_TZ).date()
            if d in by_day:
                # Best per evaluation day, like the club's sheet.
                by_day[d] = min(by_day[d], v) if r.direction == "down" else max(by_day[d], v)
            else:
                by_day[d] = v
        r.points = sorted(by_day.items())
        if not r.points:
            return r
        bands = (self.cat_bands.get((t.family_id or t.id, m.key))
                 or f.get("reference_ranges") or [])
        if bands:
            b = band_for_value(r.last, bands)
            if b:
                r.band, r.level = b, _level(b, bands)
        r.percentile = self._percentile(t, m, r.last, r.direction)
        return r

    def _percentile(self, t, m: M, value: float, direction: str) -> float | None:
        qs = ExamResult.objects.filter(template__family_id=t.family_id,
                                       player_id__in=self.peer_ids, recorded_at__gte=self.desde)
        if m.per_match_min:
            qs = qs.filter(result_data__tot_dur__gte=m.per_match_min)
        latest: dict[Any, float] = {}
        for pid, data in qs.order_by("-recorded_at").values_list("player_id", "result_data"):
            if pid not in latest and (v := _num((data or {}).get(m.key))) is not None:
                latest[pid] = v
        vals = list(latest.values())
        if len(vals) < MIN_PEERS or direction == "neutral":
            return None
        below = sum(1 for v in vals if v < value) + 0.5 * sum(1 for v in vals if v == value)
        p = 100 * below / len(vals)
        return 100 - p if direction == "down" else p

    # -- header ----------------------------------------------------------
    def body(self) -> tuple[float | None, float | None]:
        for slug in ("pentacompartimental", "peso_talla"):
            t = self.template(slug)
            if t is None:
                continue
            row = (ExamResult.objects.filter(template__family_id=t.family_id, player=self.player)
                   .order_by("-recorded_at").values_list("result_data", flat=True).first())
            if row and (_num(row.get("talla")) or _num(row.get("peso"))):
                return _num(row.get("talla")), _num(row.get("peso"))
        return (_num(self.player.current_height_cm), _num(self.player.current_weight_kg))

    # -- special sections ------------------------------------------------
    def injuries(self) -> list[dict]:
        """One entry per injury EPISODE, newest first — an injury has a record
        per stage (aguda, …, closed), and listing records repeats it."""
        from exams.models import Episode

        out = []
        for e in (Episode.objects.filter(player=self.player, template__slug="lesiones",
                                         started_at__gte=self.desde)
                  .order_by("-started_at")[:6]):
            dias = None
            row = (ExamResult.objects.filter(episode=e).order_by("-recorded_at")
                   .values_list("result_data", flat=True).first())
            if row:
                dias = _num(row.get("dias_perdidos"))
            out.append({
                "date": e.started_at.astimezone(_TZ).date(),
                "end": e.ended_at.astimezone(_TZ).date() if e.ended_at else None,
                "what": (e.title or "Lesión").replace(" — ", " · "),
                "days": dias,
            })
        return out

    def season(self) -> dict:
        year = datetime.now(_TZ).year
        out: dict[str, Any] = {"year": year}
        t = self.template("ficha_partido")
        if t is not None:
            rows = list(ExamResult.objects.filter(template__family_id=t.family_id,
                                                  player=self.player, recorded_at__year=year)
                        .values_list("result_data", flat=True))
            out["partidos"] = sum(1 for r in rows if (_num(r.get("minutos")) or 0) > 0)
            out["citaciones"] = len(rows)
            out["minutos"] = sum(_num(r.get("minutos")) or 0 for r in rows)
            out["goles"] = sum(_num(r.get("goles")) or 0 for r in rows)
            out["asistencias"] = sum(_num(r.get("asistencias")) or 0 for r in rows)
        lesiones = [i for i in self.injuries() if i["date"].year == year]
        out["lesiones"] = len(lesiones)
        out["dias_baja"] = sum(i["days"] or 0 for i in lesiones)
        return out


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def _fmt(v: float | None, dec: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _delta_pct(r: Reading) -> float | None:
    if r.last is None or r.prev in (None, 0):
        return None
    return 100 * (r.last - r.prev) / abs(r.prev)


def _in_points(r: Reading) -> bool:
    """A % field, or one that crosses zero: its change reads in points — a
    relative change of −2,6 % against 0,3 % is "−897 %", which says nothing."""
    return r.unit == "%" or (r.prev is not None and r.last is not None and r.prev * r.last <= 0)


def _improved(r: Reading) -> bool | None:
    if r.last is None or r.prev is None or r.direction == "neutral":
        return None
    if _in_points(r):
        diff = r.last - r.prev
        if abs(diff) < 0.5:
            return None
        return (diff > 0) == (r.direction == "up")
    d = _delta_pct(r)
    if d is None or abs(d) < 1:
        return None
    return (d > 0) == (r.direction == "up")


def card_line(r: Reading) -> str:
    if r.last is None:
        return "Sin evaluación registrada."
    parts = [f"Última {r.points[-1][0]:%d/%m/%y}"]
    imp = _improved(r)
    if _in_points(r) and r.prev is not None:
        diff = r.last - r.prev
        if abs(diff) >= 0.5:
            parts.append(f"{diff:+.1f} pts vs la anterior".replace(".", ","))
        d = None
    else:
        d = _delta_pct(r)
    if imp is not None and d is not None:
        parts.append(f"{'mejora' if imp else 'retrocede'} {abs(d):.1f}% vs la anterior".replace(".", ","))
    elif d is not None and abs(d) >= 1:
        parts.append(f"{d:+.1f}% vs la anterior".replace(".", ","))
    if r.band:
        parts.append(f"rango {str(r.band.get('label')).capitalize()}")
    elif r.percentile is not None:
        parts.append(f"percentil {r.percentile:.0f} en la categoría")
    age = (datetime.now(_TZ).date() - r.points[-1][0]).days
    if age > STALE_DAYS:
        parts.append(f"evaluación de hace {age // 30} meses")
    if len(r.points) == 1:
        parts.append("primera evaluación registrada")
    return "; ".join(parts) + "."


# Left/right pairs the reading compares: (right key, left key, what).
_LADOS = (("cod_der_best", "cod_izq_best", "cambio de dirección (COD 505)"),
          ("right_max", "left_max", "fuerza de isquios (nórdico)"))
_PIE_TXT = {"right": ("derecho", "derecha"), "left": ("izquierdo", "izquierda"),
            "both": ("ambidiestro", None)}


def laterality(readings: list[Reading], foot: str) -> list[str]:
    """The player's foot, and for each left/right test which side is better —
    and whether that is the side of the foot. Under 3 % apart is symmetric."""
    by_key = {r.m.key: r for r in readings if r.last is not None}
    lines = []
    pie, lado_pie = _PIE_TXT.get(foot or "", (None, None))
    if pie:
        lines.append(f"Perfil: {pie}.")
    for der_k, izq_k, que in _LADOS:
        der, izq = by_key.get(der_k), by_key.get(izq_k)
        if not der or not izq:
            continue
        down = der.direction == "down"
        diff = 100 * abs(der.last - izq.last) / max(abs(der.last), abs(izq.last), 1e-9)
        if diff < 3:
            lines.append(f"{que.capitalize()}: simétrico ({_fmt(der.last, der.m.decimals)} der. · "
                         f"{_fmt(izq.last, izq.m.decimals)} izq.).")
            continue
        mejor = "derecha" if (der.last < izq.last) == down else "izquierda"
        frase = (f"{que.capitalize()}: mejor hacia la {mejor} "
                 f"({_fmt(der.last, der.m.decimals)} der. · {_fmt(izq.last, izq.m.decimals)} izq., "
                 f"{diff:.0f} %)")
        if lado_pie:
            frase += ", su lado hábil" if mejor == lado_pie else ", el contrario a su perfil"
        lines.append(frase + ".")
    return lines


def synthesis(readings: list[Reading], foot: str = "",
              sides: list[Reading] | None = None) -> dict[str, Any]:
    """`sides`: readings for the left/right comparison when the sheet doesn't
    draw them (the general ficha has no COD cards); defaults to `readings`."""
    con = [r for r in readings if r.last is not None]
    strong = sorted((r for r in con if r.verdict == "strong"),
                    key=lambda r: -(r.level if r.level is not None else (r.percentile or 0) / 100 * 6))
    weak = sorted((r for r in con if r.verdict == "weak"),
                  key=lambda r: (r.level if r.level is not None else (r.percentile or 0) / 100 * 6))
    mejora = [r for r in con if _improved(r) is True]
    baja = [r for r in con if _improved(r) is False]
    faltan = [r for r in readings if r.last is None]

    def nombres(rs):
        ns = list(dict.fromkeys(r.m.short for r in rs))
        return ", ".join(ns[:-1]) + (" y " if len(ns) > 1 else "") + ns[-1] if ns else ""

    if not con:
        return {"lines": ["Sin evaluaciones registradas para este jugador en esta área."],
                "plazos": []}
    lines = []
    lines.append(f"Fortalezas: {nombres(strong)}." if strong
                 else "Sin fortalezas destacadas en la última evaluación.")
    lines.append(f"A priorizar: {nombres(weak)}." if weak
                 else "Sin déficits marcados: ningún indicador en rango deficiente.")
    lines += laterality(sides if sides is not None else readings, foot)
    if mejora:
        lines.append(f"Evoluciona a favor en {nombres(mejora[:4])}.")
    if baja:
        lines.append(f"Retrocede en {nombres(baja[:4])}.")
    if faltan:
        lines.append(f"Sin datos de {nombres(faltan[:4])}.")
    plazos = [
        ("Corto plazo", f"Abordar {weak[0].m.short} y asegurar disponibilidad." if weak
         else "Sostener el nivel actual y asegurar disponibilidad."),
        ("Mediano plazo", (f"Mejorar {nombres(weak[1:3]) or weak[0].m.short} manteniendo "
                           f"{nombres(strong[:2]) or 'lo logrado'}.") if weak
         else f"Potenciar {nombres(strong[:2]) or 'las cualidades rezagadas'}."),
        ("Largo plazo", "Construir un perfil equilibrado según edad, maduración y posición."),
    ]
    def punto(t: str) -> str:
        # Labels like "isquios der." already end the sentence.
        return t.replace("..", ".")
    return {"lines": [punto(x) for x in lines], "plazos": [(a, punto(b)) for a, b in plazos]}


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _ink_for(fill) -> colors.Color:
    c = fill if isinstance(fill, colors.Color) else colors.HexColor(fill)
    lum = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
    return INK if lum > 0.6 else colors.white


def _text(c, x, y, s, size=8, font="Helvetica", color=INK, anchor="left"):
    c.setFont(font, size)
    c.setFillColor(color)
    {"left": c.drawString, "right": c.drawRightString,
     "center": c.drawCentredString}[anchor](x, y, s)


def _wrap(c, s, width, size, font="Helvetica") -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if c.stringWidth(t, font, size) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _month(d: date) -> str:
    return ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov",
            "dic"][d.month - 1] + f"-{d.year % 100:02d}"


def _spark(c, r: Reading, x, y, w, h, color):
    pts = r.points[-MAX_POINTS:]
    if not pts:
        _text(c, x + w / 2, y + h / 2, "Sin datos", 7, color=MUTED, anchor="center")
        return
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    n = len(pts)
    px = [x + (w * (i + 0.5) / n) for i in range(n)]
    py = [y + 8 + (h - 15) * (v - lo) / (hi - lo) for v in vals]
    c.setStrokeColor(colors.HexColor("#d1d5db"))
    c.setLineWidth(0.4)
    c.line(x, y + 6.5, x + w, y + 6.5)
    c.setStrokeColor(color)
    c.setLineWidth(1.3)
    for i in range(1, n):
        c.line(px[i - 1], py[i - 1], px[i], py[i])
    for i, (d, v) in enumerate(pts):
        c.setFillColor(color)
        c.circle(px[i], py[i], 1.6, stroke=0, fill=1)
        _text(c, px[i], py[i] + 3, _fmt(v, r.m.decimals), 5.6, color=INK, anchor="center")
        if n <= 6 or i % 2 == (n - 1) % 2:
            _text(c, px[i], y, _month(d), 5.2, color=MUTED, anchor="center")


def _card(c, r: Reading, x, y, w, h, color):
    c.setFillColor(CARD_BG)
    c.setStrokeColor(CARD_EDGE)
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, 3, stroke=1, fill=1)
    hh = 6 * mm
    c.setFillColor(color)
    c.roundRect(x, y + h - hh, w, hh, 3, stroke=0, fill=1)
    c.rect(x, y + h - hh, w, 2, stroke=0, fill=1)
    _text(c, x + w / 2, y + h - hh + 2.1 * mm, r.m.title.upper(), 6.4, "Helvetica-Bold",
          colors.white, "center")
    line_h = 7
    text_lines = _wrap(c, card_line(r), w - 8, 5.8)[:2]
    value_y = y + 4 + len(text_lines) * line_h + 2
    chart_y = value_y + 14
    _spark(c, r, x + 4, chart_y, w - 8, (y + h - hh - 2) - chart_y, color)
    val = f"{_fmt(r.last, r.m.decimals)}" + (f" {r.unit}" if r.unit and r.last is not None else "")
    _text(c, x + 5, value_y, val, 11.5, "Helvetica-Bold", INK)
    if r.band or r.percentile is not None:
        label = (str(r.band.get("label")) if r.band else f"P{r.percentile:.0f}").upper()
        fill = colors.HexColor(r.band.get("color")) if r.band and r.band.get("color") else (
            POS_GREEN if r.verdict == "strong" else NEG_RED if r.verdict == "weak"
            else colors.HexColor("#94a3b8"))
        pw = max(18 * mm, c.stringWidth(label, "Helvetica-Bold", 6.2) + 10)
        pw = min(pw, w * 0.55)
        c.setFillColor(fill)
        c.roundRect(x + w - pw - 5, value_y - 2, pw, 11, 5.5, stroke=0, fill=1)
        _text(c, x + w - pw / 2 - 5, value_y + 1.6, label, 6.2, "Helvetica-Bold",
              _ink_for(fill), "center")
    for i, ln in enumerate(text_lines):
        _text(c, x + 5, y + 4 + (len(text_lines) - 1 - i) * line_h, ln, 5.8,
              color=colors.HexColor("#374151"))


def _section_bar(c, s: Section, x, y, w):
    col = SECTION_COLORS[s.color]
    c.setFillColor(col)
    c.roundRect(x, y, w, 6 * mm, 3, stroke=0, fill=1)
    _text(c, x + 5 * mm, y + 1.9 * mm, s.title.upper(), 9, "Helvetica-Bold", colors.white)
    if s.subtitle:
        _text(c, x + w - 5 * mm, y + 2.1 * mm, s.subtitle, 6.3, color=colors.white, anchor="right")


def _header(c, player: Player, data: _Data, subtitle: str):
    h = 30 * mm
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - h, PAGE_W, h, stroke=0, fill=1)
    # Photo, or initials.
    px, py, ps = MARGIN, PAGE_H - h + 3 * mm, 24 * mm
    drawn = False
    if player.photo:
        try:
            with player.photo.open("rb") as fh:
                c.drawImage(ImageReader(io.BytesIO(fh.read())), px, py, ps, ps,
                            preserveAspectRatio=True, mask="auto")
            drawn = True
        except Exception:  # noqa: BLE001 — a missing file falls back below
            drawn = False
    if not drawn and player.photo_url:
        try:
            import requests

            resp = requests.get(player.photo_url, timeout=4)
            if resp.ok:
                c.drawImage(ImageReader(io.BytesIO(resp.content)), px, py, ps, ps,
                            preserveAspectRatio=True, mask="auto")
                drawn = True
        except Exception:  # noqa: BLE001 — a dead photo link must not kill the PDF
            drawn = False
    if not drawn:
        c.setFillColor(NAVY_DARK)
        c.roundRect(px, py, ps, ps, 4, stroke=0, fill=1)
        ini = (player.first_name[:1] + player.last_name[:1]).upper()
        _text(c, px + ps / 2, py + ps / 2 - 5, ini, 20, "Helvetica-Bold", colors.white, "center")
    nx = px + ps + 5 * mm
    club = player.category.club.name.upper()
    _text(c, nx, PAGE_H - 9 * mm, club, 7, "Helvetica-Bold", colors.HexColor("#bfdbfe"))
    name = " ".join(x for x in (player.first_name, player.last_name,
                                getattr(player, "second_last_name", "")) if x).upper()
    room = PAGE_W - MARGIN - 8 * (20.5 * mm + 1.8 * mm) - nx - 3 * mm
    size = 15
    while size > 9 and c.stringWidth(name, "Helvetica-Bold", size) > room:
        size -= 0.5
    _text(c, nx, PAGE_H - 16 * mm, name, size, "Helvetica-Bold", colors.white)
    _text(c, nx, PAGE_H - 21.5 * mm, subtitle.upper(), 7, color=colors.HexColor("#dbeafe"))

    talla, peso = data.body()
    dob = player.date_of_birth
    chips = [
        ("CATEGORÍA", player.category.name, RED),
        ("POSICIÓN", (player.position.name if player.position_id else "—"), NAVY_DARK),
        ("EDAD", f"{player.age} AÑOS" if player.age is not None else "—", NAVY_DARK),
        ("PERFIL", (player.get_preferred_foot_display() if player.preferred_foot else "—"), NAVY_DARK),
        ("TALLA", f"{_fmt(talla, 1)} cm" if talla else "—", NAVY_DARK),
        ("PESO", f"{_fmt(peso, 1)} kg" if peso else "—", NAVY_DARK),
        ("F. NACIMIENTO", dob.strftime("%d-%m-%Y") if dob else "—", NAVY_DARK),
        ("CUARTIL NAC.", f"Q{(dob.month - 1) // 3 + 1}" if dob else "—", RED),
    ]
    cw, gap = 20.5 * mm, 1.8 * mm
    x = PAGE_W - MARGIN - len(chips) * cw - (len(chips) - 1) * gap
    cy = PAGE_H - h + 8 * mm
    for label, value, fill in chips:
        c.setFillColor(fill)
        c.roundRect(x, cy, cw, 14 * mm, 3, stroke=0, fill=1)
        v = str(value).upper()
        if c.stringWidth(v, "Helvetica-Bold", 8) < cw - 4:
            _text(c, x + cw / 2, cy + 7.5 * mm, v, 8, "Helvetica-Bold", colors.white, "center")
        else:
            for j, ln in enumerate(_wrap(c, v, cw - 4, 6.4, "Helvetica-Bold")[:2]):
                _text(c, x + cw / 2, cy + 9 * mm - j * 7.5, ln, 6.4, "Helvetica-Bold",
                      colors.white, "center")
        _text(c, x + cw / 2, cy + 2.5 * mm, label, 5, color=colors.HexColor("#cbd5e1"),
              anchor="center")
        x += cw + gap


def _footer(c, player: Player, dept_name: str):
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, 8 * mm, stroke=0, fill=1)
    hoy = datetime.now(_TZ)
    mes = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
           "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"][hoy.month - 1]
    _text(c, MARGIN, 3 * mm, f"{dept_name.upper()} · DATOS {hoy.year - 1}–{hoy.year} · "
          f"GENERADO POR SLAB EL {hoy:%d-%m-%Y}", 6.5, "Helvetica-Bold", colors.white)
    _text(c, PAGE_W - MARGIN, 3 * mm, f"{player.category.club.name.upper()} | {mes} {hoy.year}",
          6.5, "Helvetica-Bold", colors.white, "right")


def _radar(c, readings: list[Reading], x, y, w, h):
    c.setFillColor(colors.white)
    c.setStrokeColor(CARD_EDGE)
    c.roundRect(x, y, w, h, 3, stroke=1, fill=1)
    axes = [r for r in readings if r.percentile is not None][:8]
    if len(axes) < 3:
        _text(c, x + w / 2, y + h / 2, "Perfil estandarizado: faltan datos de la categoría.",
              7, color=MUTED, anchor="center")
        return
    cx, cy = x + w / 2, y + h / 2 + 3
    rad = min(w, h - 12) / 2 - 12
    n = len(axes)
    ang = [math.pi / 2 - 2 * math.pi * i / n for i in range(n)]
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.setLineWidth(0.4)
    for ring in (0.25, 0.5, 0.75, 1):
        p = c.beginPath()
        for i, a in enumerate(ang):
            px, py = cx + rad * ring * math.cos(a), cy + rad * ring * math.sin(a)
            p.moveTo(px, py) if i == 0 else p.lineTo(px, py)
        p.close()
        c.drawPath(p, stroke=1, fill=0)
    for i, a in enumerate(ang):
        c.line(cx, cy, cx + rad * math.cos(a), cy + rad * math.sin(a))
        lx, ly = cx + (rad + 8) * math.cos(a), cy + (rad + 8) * math.sin(a)
        anchor = "center" if abs(math.cos(a)) < 0.3 else ("left" if math.cos(a) > 0 else "right")
        _text(c, lx, ly - 2, axes[i].m.short.capitalize()[:24], 5.6, "Helvetica-Bold", INK, anchor)
    # The median of the category, then the player.
    p = c.beginPath()
    for i, a in enumerate(ang):
        px, py = cx + rad * 0.5 * math.cos(a), cy + rad * 0.5 * math.sin(a)
        p.moveTo(px, py) if i == 0 else p.lineTo(px, py)
    p.close()
    c.setStrokeColor(colors.HexColor("#94a3b8"))
    c.setDash(2, 2)
    c.drawPath(p, stroke=1, fill=0)
    c.setDash()
    p = c.beginPath()
    for i, a in enumerate(ang):
        v = max(0.04, axes[i].percentile / 100)
        px, py = cx + rad * v * math.cos(a), cy + rad * v * math.sin(a)
        p.moveTo(px, py) if i == 0 else p.lineTo(px, py)
    p.close()
    c.setFillColor(colors.HexColor("#93c5fd"))
    c.setFillAlpha(0.45)
    c.setStrokeColor(NAVY)
    c.setLineWidth(1.2)
    c.drawPath(p, stroke=1, fill=1)
    c.setFillAlpha(1)
    _text(c, x + w / 2, y + 3, "Percentil en la categoría · línea punteada = mediana", 5.4,
          color=MUTED, anchor="center")


def _synthesis(c, syn: dict, x, y, w, h):
    c.setFillColor(colors.white)
    c.setStrokeColor(CARD_EDGE)
    c.roundRect(x, y, w, h, 3, stroke=1, fill=1)
    ty = y + h - 7 * mm
    for ln in syn["lines"]:
        head, _, rest = ln.partition(":")
        for j, wl in enumerate(_wrap(c, ln, w - 10 * mm, 7.6)):
            if j == 0 and rest and head in ("Fortalezas", "A priorizar"):
                col = POS_GREEN if head == "Fortalezas" else NEG_RED
                _text(c, x + 5 * mm, ty, head + ":", 7.6, "Helvetica-Bold", col)
                _text(c, x + 5 * mm + c.stringWidth(head + ": ", "Helvetica-Bold", 7.6), ty,
                      wl[len(head) + 2:], 7.6, color=INK)
            else:
                _text(c, x + 5 * mm, ty, wl, 7.6, color=INK)
            ty -= 10
    ty -= 4
    for label, txt in syn["plazos"]:
        if ty < y + 5:
            break
        _text(c, x + 5 * mm, ty, label.upper(), 7, "Helvetica-Bold", RED)
        for j, wl in enumerate(_wrap(c, txt, w - 40 * mm, 7.2)[:2]):
            _text(c, x + 33 * mm, ty - j * 9, wl, 7.2, color=INK)
        ty -= 12


def _injuries(c, items: list[dict], x, y, w, h):
    c.setFillColor(CARD_BG)
    c.setStrokeColor(CARD_EDGE)
    c.roundRect(x, y, w, h, 3, stroke=1, fill=1)
    if not items:
        _text(c, x + 6 * mm, y + h / 2 - 3, "Sin lesiones registradas.", 8, color=MUTED)
        return
    col_w = (w - 8 * mm) / 3
    for i, it in enumerate(items):
        cx = x + 4 * mm + (i % 3) * col_w
        cy = y + h - 9 * mm - (i // 3) * 11 * mm
        fin = it["end"].strftime("%d-%m-%Y") if it["end"] else "EN CURSO"
        _text(c, cx, cy, f"{it['date']:%d-%m-%Y} → {fin}", 7, "Helvetica-Bold",
              RED if not it["end"] else INK)
        dias = f" · {int(it['days'])} días de baja" if it["days"] else ""
        _text(c, cx, cy - 8, (it["what"][:52] + dias), 6.6, color=colors.HexColor("#374151"))


def _season(c, s: dict, x, y, w, h):
    tiles = [
        ("PARTIDOS JUGADOS", s.get("partidos"), f"de {s.get('citaciones', 0)} citaciones"),
        ("MINUTOS", s.get("minutos"), f"temporada {s['year']}"),
        ("GOLES", s.get("goles"), ""),
        ("ASISTENCIAS", s.get("asistencias"), ""),
        (f"LESIONES {s['year']}", s.get("lesiones"),
         f"{int(s.get('dias_baja') or 0)} días de baja"),
    ]
    tw = (w - (len(tiles) - 1) * 3 * mm) / len(tiles)
    for i, (label, val, sub) in enumerate(tiles):
        tx = x + i * (tw + 3 * mm)
        c.setFillColor(CARD_BG)
        c.setStrokeColor(CARD_EDGE)
        c.roundRect(tx, y, tw, h, 3, stroke=1, fill=1)
        _text(c, tx + tw / 2, y + h - 4.5 * mm, label, 6.3, "Helvetica-Bold", MUTED, "center")
        _text(c, tx + tw / 2, y + h / 2 - 4.5, "—" if val is None else _fmt(val, 0), 15,
              "Helvetica-Bold", INK, "center")
        if sub:
            _text(c, tx + tw / 2, y + 2.5 * mm, sub, 6, color=MUTED, anchor="center")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_ficha_pdf(player: Player, department_slug: str | None = None,
                     department_name: str = "") -> bytes:
    title, sections = SPECS.get(department_slug or "", GENERAL)
    data = _Data(player)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle(f"{title} — {player.first_name} {player.last_name}")
    _header(c, player, data, f"{title} · {department_name or 'todas las áreas'}")
    _footer(c, player, department_name or "Ficha integral")

    readings: dict[str, list[Reading]] = {}
    for s in sections:
        readings[s.title] = [data.reading(m) for m in s.metrics]
    # A section the player has no data in is left out (a youth player has no
    # VALD tests): the sheet adapts to what was measured. The synthesis still
    # names what is missing from the sections that remain.
    sections = [s for s in sections
                if s.kind != "cards" or any(r.last is not None for r in readings[s.title])]
    all_readings = [r for s in sections for r in readings.get(s.title, [])]

    top = PAGE_H - 30 * mm - 3 * mm
    bottom_block = 42 * mm
    avail = top - (8 * mm + 4 * mm) - bottom_block - 4 * mm
    bar = 6 * mm
    gap = 2.5 * mm
    fixed = {"injuries": 22 * mm, "season": 16 * mm}
    rows = sum(math.ceil(len(s.metrics) / 5) for s in sections if s.kind == "cards")
    rest = (avail - len(sections) * (bar + gap + 1.5 * mm)
            - sum(fixed.get(s.kind, 0) + gap for s in sections if s.kind != "cards"))
    unit_h = max(min(rest / max(1, rows), 58 * mm), 33 * mm)
    units = [math.ceil(len(s.metrics) / 5) if s.kind == "cards" else 0 for s in sections]
    y = top
    inner_w = PAGE_W - 2 * MARGIN
    for s, u in zip(sections, units):
        y -= bar
        _section_bar(c, s, MARGIN, y, inner_w)
        y -= 1.5 * mm
        if s.kind == "injuries":
            hh = fixed["injuries"]
            _injuries(c, data.injuries(), MARGIN, y - hh, inner_w, hh)
            y -= hh + gap
            continue
        if s.kind == "season":
            hh = fixed["season"]
            _season(c, data.season(), MARGIN, y - hh, inner_w, hh)
            y -= hh + gap
            continue
        rs = readings[s.title]
        per_row = min(5, len(rs))
        cw = (inner_w - (per_row - 1) * gap) / per_row
        for i, r in enumerate(rs):
            row, col = divmod(i, 5)
            _card(c, r, MARGIN + col * (cw + gap), y - (row + 1) * unit_h + (gap if row else 0),
                  cw, unit_h - gap, SECTION_COLORS[s.color])
        y -= u * unit_h + gap

    by = 8 * mm + 4 * mm
    rw = 82 * mm
    # Fills the page when the sections are short, up to a size that still reads
    # as a block — beyond that, white space beats an empty frame.
    bh = min(max(30 * mm, y - by), 62 * mm)
    by = y - bh
    con_radar = sum(1 for r in all_readings if r.percentile is not None) >= 3
    if not con_radar:
        rw, gap_r = 0, 0
    else:
        gap_r = gap
    blocks = ([("PERFIL ESTANDARIZADO", MARGIN, rw)] if con_radar else []) + [
        ("SÍNTESIS Y ORIENTACIÓN DEL DESARROLLO", MARGIN + rw + gap_r, inner_w - rw - gap_r)]
    for label, bx, bw in blocks:
        c.setFillColor(SECTION_COLORS["purple"] if label.startswith("SÍN") else NAVY)
        c.roundRect(bx, by + bh - 6 * mm, bw, 6 * mm, 3, stroke=0, fill=1)
        _text(c, bx + 4 * mm, by + bh - 4.2 * mm, label, 8, "Helvetica-Bold", colors.white)
    if con_radar:
        _radar(c, all_readings, MARGIN, by, rw, bh - 7 * mm)
    drawn = {(r.m.template, r.m.key) for r in all_readings}
    sides = all_readings + [data.reading(m) for m in CONDICION_2.metrics + SPECS["medico"][1][0].metrics
                            if m.key in {k for pair in _LADOS for k in pair[:2]}
                            and (m.template, m.key) not in drawn]
    _synthesis(c, synthesis(all_readings, player.preferred_foot, sides), MARGIN + rw + gap_r, by, inner_w - rw - gap_r,
               bh - 7 * mm)

    c.showPage()
    c.save()
    return buf.getvalue()
