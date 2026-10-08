"""Parse and ingest the club's `GPS CATEGORÍAS.xlsx` into the two GPS exams.

Phase 7 of PLAN_FORMATIVO.md. ~15.400 rows across the per-category sheets
(`U11`…`U20`) plus `SPARRING`, split between `gps_partido` and `gps_sesion`.

No third GPS exam
-----------------
The club's columns are a strict subset of `gps_sesion`: all 13 metrics already
have a field and `gps_sesion` has 16 more the club does not use. There are
exactly TWO GPS exams system-wide by deliberate decision, and their slugs are
hardcoded in `api/player_analysis.py`, `api/daily_report.py` (including a
metric map keyed literally by `gps_sesion`), `api/player_summary.py`,
`api/command_center.py` and the frontend's GPS upload page. Splitting by team
would also break the comparison the club actually asked for — how a youth
player fares against the senior squad — since `WidgetDataSource` is
per-template.

Match or session: the club's own markers decide
-----------------------------------------------
A row is a match when any of `LOCALIA`, `CALIDAD OPONENTE` or `RESULTADO`
carries a value. That was checked rather than assumed:

* Every marked row has `CÓDIGO = MD`; not one marked row sits on another day.
  So the markers are a strict subset of match day, never a contradiction.
* 2159 rows are `MD` with **no** markers, and they do not look like matches:
  median 47,0 min and 5180 m, against 82,2 min and 8214 m for the marked ones
  and 51,5 min / 4206 m for ordinary sessions. They read as work done on match
  day, not as matches.
* Without the markers there is no opponent and no result either, so filing
  them as `gps_partido` would create match records with no match.

Those 2159 go to `gps_sesion` and are reported. If the club fills in the
metadata later, re-running reclassifies nothing on its own — the rows already
exist — so the report is the place that says which days are missing it.

`acc_dec` is left empty on purpose
----------------------------------
The club gives `AC (#)` and `DEC (#)` separately and SLAB has a field for each,
plus a legacy `acc_dec` total. Catapult does not populate `acc_dec` either (it
is absent from its `SLUG_MAP`), so leaving it empty keeps the two live sources
consistent. Summing the parts here would make the Formativo the only origin
that carries it, which is the same inconsistency pointing the other way.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Club, Player
from exams.calculations import compute_result_data
from exams.microcycle import MD_SOURCE_CLUB, MD_SOURCE_KEY
from exams.models import ExamResult, ExamTemplate

ORIGEN = "planilla_club_formativo_gps"

SLUG_PARTIDO = "gps_partido"
SLUG_SESION = "gps_sesion"

# Sheets that are neither: World Cup scouting logs hold OTHER teams' players
# (Panamá, Guatemala, Al Ahly, Inter Miami); `Pasing Indi.` breaks one session
# into 15-minute blocks, so importing it would count the same work several
# times; the rest are aggregates with no player or no date.
SHEETS_EXCLUDED = {
    "JUGADORES", "U17WC", "U20 WC", "WC CLUBES", "Pasing Gral.", "Pasing Indi.",
    "GPS PARTIDOS", "Perfiles Físicos", "VAM", "Control de Carga",
}

# Column header → template field, matched by PATTERN rather than by exact
# string. The club bakes its thresholds into the headers — `HSR (m) >20km/h`,
# `AC (#) >3ms2`, `SPRINT (m) >25km/h` — so an exact map is pinned to those
# numbers. An earlier version of this file was, and five of the twelve metrics
# went unmapped in silence: `acc`, `dec`, `hsr`, `sprint_dist` and `sprints`,
# which are most of the point. The import reported 15.352 rows and "0 filas sin
# métricas", because the other seven columns did map.
#
# Order matters: `SPRINT M` must be tried before the bare `SPRINT`, and `DEC`
# before `AC` would be wrong the other way around ("DEC" contains no "AC" but
# the anchors keep them apart anyway).
COLUMNAS: tuple[tuple[str, str], ...] = (
    (r"^DURACION",              "tot_dur"),
    (r"^DT ",                   "tot_dist"),
    (r"^MM$",                   "mpm"),
    (r"^AC ",                   "acc"),
    (r"^DEC ",                  "dec"),
    (r"^VMAX",                  "max_vel"),
    (r"^PL ",                   "player_load"),
    (r"^HSR",                   "hsr"),
    (r"^SPRINT M",              "sprint_dist"),
    (r"^SPRINT",                "sprints"),
    (r"AVG HR",                 "avg_hr_pct"),
    (r"MAX HEART RATE",         "max_hr_bpm"),
)
# Metrics every per-category sheet must yield. Heart rate is NOT here: only
# U18 and U20 record it. If one of these fails to map the sheet changed shape
# and the run says so instead of loading partial rows quietly.
ESPERADAS = frozenset({"tot_dur", "tot_dist", "mpm", "acc", "dec", "max_vel",
                       "player_load", "hsr", "sprint_dist", "sprints"})

# Any of these carrying a value means the row is a match. See the module
# docstring for why they beat `CÓDIGO = MD` as the signal.
MARCAS_PARTIDO = ("LOCALIA", "CALIDAD OPONENTE", "RESULTADO")

# Columns that are NOT metrics and are skipped on purpose: identity, the
# microcycle code (CÓDIGO — stored as the row's `md_label`, see
# `md_del_club`), the free-text note (the opponent) and the three match
# markers (stored as match fields, see `CAMPOS_PARTIDO`).
NO_METRICAS = frozenset({
    "FECHA", "JUGADOR", "FECHA DE NACIMIENTO", "EDAD", "CATEGORIA", "POSICION",
    "CODIGO", "MICRO", "OBSERVACION", *MARCAS_PARTIDO,
})

def norm(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


def _num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _fecha(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


@dataclass
class Fila:
    hoja: str
    nombre: str
    dob: date | None
    dia: date
    codigo: str
    es_partido: bool
    datos: dict[str, Any]
    observacion: str = ""
    # The match columns as the club wrote them: LOCALIA, CALIDAD OPONENTE,
    # RESULTADO (normalised headers → raw cell text).
    marcas: dict[str, str] = dc_field(default_factory=dict)

    @property
    def partido(self) -> dict[str, Any]:
        return datos_de_partido(self.codigo, self.observacion, self.marcas)

    @property
    def slug(self) -> str:
        return SLUG_PARTIDO if self.es_partido else SLUG_SESION

    @property
    def origen_id(self) -> str:
        return origen_id(self.nombre, self.dia, self.hoja, self.codigo, self.slug)


# Match-day codes the club refines in place: in Sept 2026 it re-coded every
# past `MD` row as `MD OFICIAL` or `MD AMISTOSO`. They are the same row, so
# they share an identity — with the raw code in it, the next sync imported
# each re-coded row again (1.153 matches + 871 sessions twice, 2026-09-24).
# `repair_formativo_gps` cleaned that up. The raw code stays in
# `origen_codigo` and the session label.
CODIGOS_MD = frozenset({"MD", "MD OFICIAL", "MD AMISTOSO"})


# ---------------------------------------------------------------------------
# What kind of match, against whom, where and how it went
# ---------------------------------------------------------------------------
# The club's sheet says it in four columns the import used only to tell a
# match from a session: OBSERVACIÓN (the opponent — "ENTRENAMIENTO" on a
# training), LOCALÍA (LOCAL / VISITA), CALIDAD OPONENTE (the opponent's table
# position at the time, or the knockout stage: "3", "SEMIFINAL", "4TOS DE
# FINAL", "CAMPEON") and RESULTADO (GANADO / EMPATADO / PERDIDO); the match
# type is in CÓDIGO (MD OFICIAL / MD AMISTOSO). They are stored on the row
# (`CAMPOS_PARTIDO`) and refreshed on every sync — the club fills them in
# after the fact — without touching the metrics.
CAMPOS_PARTIDO: tuple[dict, ...] = (
    {"key": "opponent", "label": "Rival", "type": "text", "group": "Partido"},
    {"key": "match_type", "label": "Tipo de partido", "type": "categorical",
     "group": "Partido", "options": ["official", "friendly"],
     "option_labels": {"official": "Oficial", "friendly": "Amistoso"}},
    {"key": "venue", "label": "Localía", "type": "categorical", "group": "Partido",
     "options": ["home", "away"], "option_labels": {"home": "Local", "away": "Visita"}},
    {"key": "result", "label": "Resultado", "type": "categorical", "group": "Partido",
     "options": ["won", "drawn", "lost"],
     "option_labels": {"won": "Ganado", "drawn": "Empatado", "lost": "Perdido"}},
    {"key": "opponent_quality", "label": "Calidad del rival", "type": "text",
     "group": "Partido"},
    {"key": "opponent_rank", "label": "Posición del rival en la tabla", "type": "number",
     "group": "Partido", "min": 1, "max": 40, "direction_of_good": "neutral"},
    # The microcycle day: the club's CÓDIGO (`md_del_club`), or derived from
    # the calendar (`exams.microcycle`) when the club gave none.
    {"key": "md_label", "label": "Día de microciclo", "type": "text", "group": "Sesión"},
)
CAMPOS_PARTIDO, CAMPO_MD = CAMPOS_PARTIDO[:-1], CAMPOS_PARTIDO[-1]
# A friendly is a session (no match markers): it only knows whom and what.
CAMPOS_SESION_PARTIDO = ("opponent", "match_type")
CLAVES_PARTIDO = tuple(c["key"] for c in CAMPOS_PARTIDO)

_LOCALIA = {"LOCAL": "home", "VISITA": "away"}
_RESULTADO = {"GANADO": "won", "EMPATADO": "drawn", "PERDIDO": "lost"}


def datos_de_partido(codigo: str, observacion: str, marcas: dict[str, str]) -> dict[str, Any]:
    """The match fields of one sheet row; {} for a training."""
    out: dict[str, Any] = {}
    rival = (observacion or "").strip()
    # Not opponents: what the club writes on a training or a sparring session.
    if rival and norm(rival) not in {"ENTRENAMIENTO", "SESION", "SPARRING"}:
        out["opponent"] = rival
    if codigo == "MD AMISTOSO":
        out["match_type"] = "friendly"
    elif codigo == "MD OFICIAL" or (codigo == "MD" and marcas):
        out["match_type"] = "official"
    if (v := _LOCALIA.get(norm(marcas.get("LOCALIA", "")))):
        out["venue"] = v
    if (v := _RESULTADO.get(norm(marcas.get("RESULTADO", "")))):
        out["result"] = v
    calidad = (marcas.get("CALIDAD OPONENTE") or "").strip()
    if calidad:
        out["opponent_quality"] = calidad
        # "3" or "4 (CAMPEÓN)" → a table position; a knockout stage has none.
        if (m := re.match(r"^(\d{1,2})\b", calidad)):
            out["opponent_rank"] = int(m.group(1))
    if not out.get("match_type") and not out.get("opponent"):
        return {}
    return out


_MD_N = re.compile(r"^MD[+-]\d{1,2}$")


def md_del_club(codigo: str, es_partido: bool) -> tuple[bool, str | None]:
    """(the club said something, the label). The club's CÓDIGO IS the
    microcycle day: "MD-2", "MD+1"; a match day — any MD variant, or a match
    row — is "MD"; "NO MD" is the club saying the session sits in no
    microcycle (None, authored). An empty code says nothing: the derived
    label (`exams.microcycle`) applies."""
    if es_partido:
        return True, "MD"
    if _MD_N.match(codigo):
        return True, codigo
    if codigo in CODIGOS_MD:
        return True, "MD"
    if codigo == "NO MD":
        return True, None
    return False, None


def asegurar_campos(template: ExamTemplate, claves: tuple[str, ...]) -> list[str]:
    """Add the match fields `claves` to `template` if missing (in place — never
    by re-seeding it, which would overwrite its whole schema). Returns the
    keys added; the caller saves."""
    schema = template.config_schema or {}
    fields = schema.setdefault("fields", [])
    tiene = {f.get("key") for f in fields}
    nuevas = [dict(c) for c in (*CAMPOS_PARTIDO, CAMPO_MD)
              if c["key"] in claves and c["key"] not in tiene]
    fields.extend(nuevas)
    template.config_schema = schema
    return [c["key"] for c in nuevas]
TIPO_AMISTOSO = "amistoso"


def codigo_identidad(codigo: str) -> str:
    return "MD" if codigo in CODIGOS_MD else codigo


def origen_id(nombre: str, dia: date, hoja: str, codigo: str, slug: str) -> str:
    return "|".join([norm(nombre), dia.isoformat(), hoja,
                     codigo_identidad(codigo) or "-", slug])


@dataclass
class Reporte:
    creados: int = 0
    ya_existian: int = 0
    duplicados_en_archivo: int = 0
    sin_datos: int = 0
    sin_fecha: int = 0
    partidos: int = 0
    sesiones: int = 0
    md_sin_marca: int = 0
    con_evento: int = 0
    partido_actualizados: int = 0
    sin_jugador: list[str] = dc_field(default_factory=list)
    sin_plantilla: list[str] = dc_field(default_factory=list)
    fuera_de_rango: list[str] = dc_field(default_factory=list)
    por_hoja: dict = dc_field(default_factory=lambda: defaultdict(int))
    columnas_sin_mapear: dict = dc_field(default_factory=dict)
    columnas_desconocidas: dict = dc_field(default_factory=dict)
    fechas_invertidas: dict = dc_field(default_factory=dict)


def parse_workbook(
    origen: str, *, creds_file: str = "", creds_json: str = "",
) -> tuple[list[Fila], dict[str, list[str]], dict[str, list[str]], dict[str, list]]:
    """`origen` is an .xlsx path or a Google Sheets id — see formativo_sources."""
    from exams.formativo_sources import abrir, match_sheet

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    filas: list[Fila] = []
    faltantes: dict[str, list[str]] = {}
    desconocidas: dict[str, list[str]] = {}
    fechas_raras: dict[str, list] = {}
    hojas = fuente.hojas()
    # Excluded by NAME, resolved against the live titles: an export truncates a
    # tab to 31 chars, so `WC CLUBES` may not be spelled identically.
    excluidas = {match_sheet(hojas, h) for h in SHEETS_EXCLUDED} - {None}
    for hoja in hojas:
        if hoja in excluidas:
            continue
        nuevas, sin_mapear, sin_reconocer, invertidas = _parse_sheet(
            fuente.filas(hoja), hoja)
        filas.extend(nuevas)
        if sin_mapear:
            faltantes[hoja] = sin_mapear
        if sin_reconocer:
            desconocidas[hoja] = sin_reconocer
        if invertidas:
            fechas_raras[hoja] = invertidas
    fuente.cerrar()
    return filas, faltantes, desconocidas, fechas_raras


def _parse_sheet(
    grid: list, hoja: str,
) -> tuple[list[Fila], list[str], list[str], list]:
    if not grid:
        return [], [], [], []
    rows = iter(grid[1:])
    crudos = [str(c or "").strip() for c in grid[0]]
    cab = [norm(c) for c in crudos]
    ix = {c: i for i, c in enumerate(cab) if c}
    if "JUGADOR" not in ix:
        return [], [], [], []

    # Resolve the column map once. First pattern wins, and a field is claimed
    # only once so `SPRINT (m)` cannot also answer for `SPRINT (#)`.
    campos: list[tuple[int, str]] = []
    tomados: set[str] = set()
    for i, c in enumerate(cab):
        if not c:
            continue
        for patron, key in COLUMNAS:
            if key not in tomados and re.search(patron, c):
                campos.append((i, key))
                tomados.add(key)
                break

    i_nombre = ix["JUGADOR"]
    i_dob = next((i for c, i in ix.items() if "NACIMIENTO" in c), None)
    i_dia = next((i for c, i in ix.items()
                  if c.startswith("FECHA") and "NACIMIENTO" not in c), None)
    i_cod = ix.get("CODIGO")
    i_obs = ix.get("OBSERVACION")
    i_marcas = [ix[m] for m in MARCAS_PARTIDO if m in ix]

    faltantes = sorted(ESPERADAS - tomados)
    fechas_en_orden: list[tuple[int, date]] = []
    # The mirror risk of a hand-kept spreadsheet. A missing metric is loud
    # already; a column the club ADDS is silent — it just never arrives, and
    # the run still reports a full load. So anything that is neither mapped
    # nor a known non-metric is surfaced too.
    mapeadas = {i for i, _ in campos}
    # Reported with the header as the club WROTE it: whoever reads this goes
    # looking for "HMLD (m)" in their spreadsheet, not for "HMLD M".
    desconocidas = sorted(
        crudos[i] for i, c in enumerate(cab)
        if c and i not in mapeadas and c not in NO_METRICAS)
    filas = []
    for r in rows:
        get = lambda i: (r[i] if i is not None and 0 <= i < len(r) else None)
        nombre = get(i_nombre)
        if not isinstance(nombre, str) or not nombre.strip():
            continue
        dia = _fecha(get(i_dia))
        datos = {}
        for i, key in campos:
            valor = _num(get(i))
            if valor is not None:
                datos[key] = valor
        if dia is not None:
            # `n_fila` cuenta como lo ve un humano en la planilla: la cabecera
            # es la 1, así que el primer dato es la 2.
            fechas_en_orden.append((len(fechas_en_orden) + 2, dia))
        filas.append(Fila(
            hoja=hoja, nombre=nombre.strip(), dob=_fecha(get(i_dob)), dia=dia,
            codigo=str(get(i_cod) or "").strip().upper(),
            es_partido=any(get(i) not in (None, "") for i in i_marcas),
            datos=datos, observacion=str(get(i_obs) or "").strip(),
            marcas={m: str(get(ix[m])).strip() for m in MARCAS_PARTIDO
                    if m in ix and get(ix[m]) not in (None, "")},
        ))
    from exams.formativo_sources import fechas_invertidas

    return filas, faltantes, desconocidas, fechas_invertidas(fechas_en_orden)


def build_matcher(club: Club):
    """Same strategy phase 2 validated: birth date first, name as the guard."""
    por_dob: dict[date, list[tuple[set, Player]]] = defaultdict(list)
    por_nombre: dict[str, Player] = {}
    for p in Player.objects.filter(category__club=club).select_related("category"):
        largo = norm(f"{p.first_name} {p.last_name} {p.second_last_name}")
        if p.date_of_birth:
            por_dob[p.date_of_birth].append((set(largo.split()), p))
        por_nombre[largo] = p
        por_nombre.setdefault(norm(f"{p.first_name} {p.last_name}"), p)
    truncados = {k[:22]: v for k, v in por_nombre.items() if len(k) > 22}

    def match(nombre: str, dob: date | None) -> Player | None:
        clave = norm(nombre)
        if dob and por_dob.get(dob):
            candidatos = sorted(por_dob[dob],
                                key=lambda t: -len(t[0] & set(clave.split())))
            tokens, player = candidatos[0]
            if len(tokens & set(clave.split())) >= 2:
                return player
        return por_nombre.get(clave) or truncados.get(clave[:22])

    return match


# Words that say nothing about WHICH opponent: legal forms, articles, and our
# own name (an event title reads "COLO COLO vs UNIVERSIDAD DE CHILE").
_RUIDO_RIVAL = frozenset({
    "DE", "DEL", "LA", "EL", "LOS", "CLUB", "CD", "FC", "SADP", "SAD", "CSD",
    "DEPORTES", "DEPORTIVO", "UNIVERSIDAD", "CHILE", "VS", "SAN", "SANTA",
    "UNIDO", "CIUDAD",
})
# How far the club's GPS date and the fixture's date may disagree. The sheet
# records the day the team played; a fixture moved by the federation keeps its
# old date in COMET for a while. Same opponent, same team, ≤3 days apart is
# one match — nobody plays the same rival twice in a week.
MAX_DIAS_RIVAL = 3


def _tokens_rival(texto: str) -> set[str]:
    # "O´HIGGINS", "O'Higgins" and "Ohiggins" are one club: apostrophes join.
    texto = re.sub(r"[´'`’]", "", texto or "")
    return {w for w in norm(texto).replace(".", " ").split()
            if len(w) >= 3 and w not in _RUIDO_RIVAL}


class EventMatcher:
    """Finds the match a `gps_partido` row belongs to.

    By the TEAM that played — the sheet: `U18` → bracket `Sub 18` — not by the
    player's category. A player plays up: a Serie 2009 in the U18 match is on
    the U18 sheet, and their category has no 2026 matches at all, so looking it
    up by category left every one of them unlinked, and linked a SUB-20 who
    played the U18 match to the SUB-20 match of the same day.

    Then by the OPPONENT, which the club writes in `OBSERVACION`: the fixture's
    date can be off by a day or three (see `MAX_DIAS_RIVAL`). Without an
    opponent only a same-day match of that team counts, and only if it is the
    only one.
    """

    def __init__(self, club: Club):
        from events.models import Event

        self.por_bracket: dict[str, list[tuple[date, set[str], Any]]] = defaultdict(list)
        eventos = list(Event.objects.filter(category__club=club, event_type="match")
                       .select_related("bracket", "opponent_team"))
        # A match created by hand (or by a GPS upload) has no bracket: it is
        # its category's usual one.
        usual: dict = defaultdict(Counter)
        for e in eventos:
            if e.bracket_id:
                usual[e.category_id][e.bracket.name] += 1
        for e in eventos:
            br = e.bracket.name if e.bracket_id else (
                usual[e.category_id].most_common(1)[0][0] if usual[e.category_id] else None)
            if br is None:
                continue
            rival = e.opponent_team.name if e.opponent_team else _rival_del_titulo(e.title)
            self.por_bracket[br].append(
                (timezone.localtime(e.starts_at).date(), _tokens_rival(rival), e))

    @staticmethod
    def bracket_de_hoja(hoja: str) -> str | None:
        m = re.fullmatch(r"U(\d{2})", hoja.strip().upper())
        return f"Sub {m.group(1)}" if m else None

    def evento(self, hoja: str, dia: date, rival: str):
        br = self.bracket_de_hoja(hoja)
        if br is None:
            return None
        cerca = [(abs((d - dia).days), toks, e) for d, toks, e in self.por_bracket.get(br, [])
                 if abs((d - dia).days) <= MAX_DIAS_RIVAL]
        buscado = _tokens_rival(rival)
        if buscado:
            puntaje = [(len(buscado & toks), -dist, e) for dist, toks, e in cerca]
            puntaje = sorted((p for p in puntaje if p[0] > 0), key=lambda p: p[:2], reverse=True)
            if not puntaje or (len(puntaje) > 1 and puntaje[0][:2] == puntaje[1][:2]):
                return None
            return puntaje[0][2]
        mismo_dia = [e for dist, _, e in cerca if dist == 0]
        return mismo_dia[0] if len(mismo_dia) == 1 else None


def _rival_del_titulo(titulo: str) -> str:
    """"COLO COLO vs UNIVERSIDAD DE CHILE" → "COLO COLO"."""
    lados = re.split(r"\s+vs\.?\s+", titulo or "", flags=re.I)
    otros = [l for l in lados if "CHILE" not in norm(l)]
    return otros[0] if otros else (titulo or "")


def rival_de_sesion(sesion: str) -> str:
    """The opponent from a stored label: "Partido 2026-09-05 · MD · WANDERERS"."""
    partes = (sesion or "").split(" · ")
    return partes[2] if len(partes) >= 3 else ""


def _descartar_fuera_de_rango(template: ExamTemplate, datos: dict) -> list[str]:
    """Drop values outside the field's min/max, keep the row.

    Same call as the physical import: a session holds a dozen metrics and one
    impossible cell is no reason to lose the other eleven.
    """
    descartados = []
    for f in template.config_schema.get("fields") or []:
        valor = datos.get(f["key"])
        if not isinstance(valor, (int, float)):
            continue
        lo, hi = f.get("min"), f.get("max")
        if (lo is not None and valor < lo) or (hi is not None and valor > hi):
            descartados.append(f"{f['key']}={valor}")
            datos.pop(f["key"])
    return descartados


def run(origen: str, club: Club, *, commit: bool = False,
        fire_alerts: bool = False, solo_hojas: set[str] | None = None,
        creds_file: str = "", creds_json: str = "") -> Reporte:
    filas, faltantes, desconocidas, fechas_raras = parse_workbook(
        origen, creds_file=creds_file, creds_json=creds_json)
    if solo_hojas:
        filas = [f for f in filas if f.hoja in solo_hojas]
    match = build_matcher(club)
    eventos = EventMatcher(club)
    rep = Reporte()
    rep.columnas_sin_mapear = faltantes
    rep.columnas_desconocidas = desconocidas
    rep.fechas_invertidas = fechas_raras

    plantillas: dict[str, ExamTemplate | None] = {}
    for slug in (SLUG_PARTIDO, SLUG_SESION):
        plantillas[slug] = (
            ExamTemplate.objects.filter(
                slug=slug, department__club=club, is_active_version=True).first()
            or ExamTemplate.objects.filter(slug=slug, department__club=club).first())
        if plantillas[slug] is None:
            rep.sin_plantilla.append(slug)

    ids = [f.origen_id for f in filas if f.dia]
    en_base: dict[str, ExamResult] = {
        r.result_data["origen_id"]: r
        for r in ExamResult.objects.filter(result_data__origen=ORIGEN,
                                           result_data__origen_id__in=ids)
        .select_related("template").only("id", "result_data", "template__slug")}
    a_refrescar: dict[Any, ExamResult] = {}
    vistos: set[str] = set()
    a_crear: list[ExamResult] = []

    for fila in filas:
        if fila.dia is None:
            rep.sin_fecha += 1
            continue
        template = plantillas.get(fila.slug)
        if template is None:
            continue
        if not fila.datos:
            rep.sin_datos += 1
            continue
        if fila.origen_id in en_base:
            if fila.origen_id in vistos:
                # A second sheet row with the same identity (a training and a
                # "SPARRING" the same day): only the first one is the row's,
                # as on creation — refreshing from both would flip it each sync.
                rep.duplicados_en_archivo += 1
                continue
            vistos.add(fila.origen_id)
            rep.ya_existian += 1
            existente = en_base[fila.origen_id]
            if _refrescar_partido(existente, fila):
                a_refrescar[existente.pk] = existente
            continue
        if fila.origen_id in vistos:
            rep.duplicados_en_archivo += 1
            continue
        player = match(fila.nombre, fila.dob)
        if player is None:
            rep.sin_jugador.append(f"{fila.nombre} ({fila.hoja}, {fila.dia})")
            continue

        datos = dict(fila.datos)
        descartados = _descartar_fuera_de_rango(template, datos)
        if descartados:
            rep.fuera_de_rango.append(
                f"{fila.nombre} {fila.dia} {fila.hoja}: {'; '.join(descartados)}")
        if not datos:
            rep.sin_datos += 1
            continue

        datos["fecha"] = fila.dia.isoformat()
        # A human label for the row, since the club has no session name. The
        # microcycle day is the club's own CÓDIGO (`md_label`, below).
        etiqueta = "Partido" if fila.es_partido else "Sesión"
        datos["sesion"] = f"{etiqueta} {fila.dia.isoformat()}" + (
            f" · {fila.codigo}" if fila.codigo else "")
        if not fila.es_partido:
            # A friendly the club codes `MD AMISTOSO` stays a session (it has
            # no match markers) but is labelled as one: not a regular training.
            datos["tipo_sesion"] = (TIPO_AMISTOSO if fila.codigo == "MD AMISTOSO"
                                    else "entrenamiento")
        if fila.observacion:
            datos["sesion"] += f" · {fila.observacion[:60]}"
        datos.update(_partido_para(fila.partido, template.slug))
        datos.update(_md_para(fila) or {})

        datos, snapshot = compute_result_data(template, datos, player=player)
        datos["origen"] = ORIGEN
        datos["origen_hoja"] = fila.hoja
        datos["origen_id"] = fila.origen_id
        datos["origen_codigo"] = fila.codigo or ""

        evento = (eventos.evento(fila.hoja, fila.dia, fila.observacion)
                  if fila.es_partido else None)
        if evento is not None:
            rep.con_evento += 1
        a_crear.append(ExamResult(
            template=template, player=player, event=evento,
            recorded_at=timezone.make_aware(
                datetime.combine(fila.dia, datetime.min.time())),
            result_data=datos, inputs_snapshot=snapshot))
        rep.creados += 1
        rep.por_hoja[fila.hoja] += 1
        if fila.es_partido:
            rep.partidos += 1
        else:
            rep.sesiones += 1
            if fila.codigo == "MD":
                rep.md_sin_marca += 1
        vistos.add(fila.origen_id)

    rep.partido_actualizados = len(a_refrescar)
    if commit and a_refrescar:
        ExamResult.objects.bulk_update(list(a_refrescar.values()), ["result_data"],
                                       batch_size=500)
    if commit and a_crear:
        with transaction.atomic():
            ExamResult.objects.bulk_create(a_crear, batch_size=500)
            if fire_alerts:
                _fire_band_alerts(a_crear)
    return rep


def _partido_para(datos: dict, slug: str) -> dict:
    claves = CLAVES_PARTIDO if slug == SLUG_PARTIDO else CAMPOS_SESION_PARTIDO
    return {k: v for k, v in datos.items() if k in claves}


_CLAVES_MD = ("md_label", MD_SOURCE_KEY)


def _md_para(fila: Fila) -> dict | None:
    """The microcycle keys the sheet sets, or None when it sets none."""
    dijo, label = md_del_club(fila.codigo, fila.es_partido)
    return {"md_label": label, MD_SOURCE_KEY: MD_SOURCE_CLUB} if dijo else None


def _refrescar_partido(r: ExamResult, fila: Fila) -> bool:
    """Bring an existing row's match fields and the club's microcycle day in
    line with the sheet. Only those keys: a re-sync never rewrites a metric."""
    claves = CLAVES_PARTIDO if r.template.slug == SLUG_PARTIDO else CAMPOS_SESION_PARTIDO
    nuevos = _partido_para(fila.partido, r.template.slug)
    md = _md_para(fila)
    if md is not None:
        claves = (*claves, *_CLAVES_MD)
        nuevos |= md
    actual = {k: r.result_data.get(k) for k in claves if k in r.result_data}
    if actual == nuevos:
        return False
    for k in claves:
        r.result_data.pop(k, None)
    r.result_data.update(nuevos)
    return True


def _fire_band_alerts(results: list[ExamResult]) -> int:
    """`bulk_create` fires no signals, so alerts are explicit — and off by
    default: this is a 2024–2026 backfill and a two-year-old reading is expired
    again by the next staleness sweep."""
    from goals.evaluator import ALERT_STALE_DAYS, evaluate_threshold_rules_for_result

    corte = timezone.now() - timezone.timedelta(days=ALERT_STALE_DAYS)
    n = 0
    for r in results:
        if r.recorded_at and r.recorded_at >= corte:
            n += len(evaluate_threshold_rules_for_result(r) or [])
    return n
