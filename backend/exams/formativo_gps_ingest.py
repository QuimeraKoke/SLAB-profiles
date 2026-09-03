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
# microcycle day (derived by `exams.microcycle` from the club's own match
# dates), the free-text note, and the three match markers that decide which
# exam a row lands in.
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

    @property
    def slug(self) -> str:
        return SLUG_PARTIDO if self.es_partido else SLUG_SESION

    @property
    def origen_id(self) -> str:
        return "|".join([norm(self.nombre), self.dia.isoformat(), self.hoja,
                         self.codigo or "-", self.slug])


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
    sin_jugador: list[str] = dc_field(default_factory=list)
    sin_plantilla: list[str] = dc_field(default_factory=list)
    fuera_de_rango: list[str] = dc_field(default_factory=list)
    por_hoja: dict = dc_field(default_factory=lambda: defaultdict(int))
    columnas_sin_mapear: dict = dc_field(default_factory=dict)
    columnas_desconocidas: dict = dc_field(default_factory=dict)


def parse_workbook(
    path: str,
) -> tuple[list[Fila], dict[str, list[str]], dict[str, list[str]]]:
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    filas: list[Fila] = []
    faltantes: dict[str, list[str]] = {}
    desconocidas: dict[str, list[str]] = {}
    for hoja in book.sheetnames:
        if hoja in SHEETS_EXCLUDED:
            continue
        nuevas, sin_mapear, sin_reconocer = _parse_sheet(book[hoja], hoja)
        filas.extend(nuevas)
        if sin_mapear:
            faltantes[hoja] = sin_mapear
        if sin_reconocer:
            desconocidas[hoja] = sin_reconocer
    book.close()
    return filas, faltantes, desconocidas


def _parse_sheet(sheet, hoja: str) -> tuple[list[Fila], list[str], list[str]]:
    rows = sheet.iter_rows(values_only=True)
    try:
        crudos = [str(c or "").strip() for c in next(rows)]
    except StopIteration:
        return [], [], []
    cab = [norm(c) for c in crudos]
    ix = {c: i for i, c in enumerate(cab) if c}
    if "JUGADOR" not in ix:
        return [], [], []

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
        filas.append(Fila(
            hoja=hoja, nombre=nombre.strip(), dob=_fecha(get(i_dob)), dia=dia,
            codigo=str(get(i_cod) or "").strip().upper(),
            es_partido=any(get(i) not in (None, "") for i in i_marcas),
            datos=datos, observacion=str(get(i_obs) or "").strip(),
        ))
    return filas, faltantes, desconocidas


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


def _eventos_por_dia(club) -> dict[tuple[Any, date], Any]:
    """Match events keyed by (category, day), to link the `partido` rows.

    `ExamResult.event` is nullable, so a row whose match is not in SLAB still
    imports — it just cannot be read from the match's own view. The club's
    export starts in 2024 and the COMET events start 2025-01-23, so the whole
    first season has no event to link to and that is expected.
    """
    from events.models import Event

    return {
        (e.category_id, e.starts_at.date()): e
        for e in Event.objects.filter(category__club=club, event_type="match")
        .only("id", "category_id", "starts_at")
    }


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


def run(path: str, club: Club, *, commit: bool = False,
        fire_alerts: bool = False, solo_hojas: set[str] | None = None) -> Reporte:
    filas, faltantes, desconocidas = parse_workbook(path)
    if solo_hojas:
        filas = [f for f in filas if f.hoja in solo_hojas]
    match = build_matcher(club)
    eventos = _eventos_por_dia(club)
    rep = Reporte()
    rep.columnas_sin_mapear = faltantes
    rep.columnas_desconocidas = desconocidas

    plantillas: dict[str, ExamTemplate | None] = {}
    for slug in (SLUG_PARTIDO, SLUG_SESION):
        plantillas[slug] = (
            ExamTemplate.objects.filter(
                slug=slug, department__club=club, is_active_version=True).first()
            or ExamTemplate.objects.filter(slug=slug, department__club=club).first())
        if plantillas[slug] is None:
            rep.sin_plantilla.append(slug)

    ids = [f.origen_id for f in filas if f.dia]
    en_base = set(
        ExamResult.objects.filter(result_data__origen=ORIGEN,
                                  result_data__origen_id__in=ids)
        .values_list("result_data__origen_id", flat=True))
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
            rep.ya_existian += 1
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
        # microcycle day is NOT stored as a metric: `exams.microcycle` derives
        # it from the club's own match dates.
        etiqueta = "Partido" if fila.es_partido else "Sesión"
        datos["sesion"] = f"{etiqueta} {fila.dia.isoformat()}" + (
            f" · {fila.codigo}" if fila.codigo else "")
        if not fila.es_partido:
            datos["tipo_sesion"] = "entrenamiento"
        if fila.observacion:
            datos["sesion"] += f" · {fila.observacion[:60]}"

        datos, snapshot = compute_result_data(template, datos, player=player)
        datos["origen"] = ORIGEN
        datos["origen_hoja"] = fila.hoja
        datos["origen_id"] = fila.origen_id
        datos["origen_codigo"] = fila.codigo or ""

        evento = eventos.get((player.category_id, fila.dia)) if fila.es_partido else None
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

    if commit and a_crear:
        with transaction.atomic():
            ExamResult.objects.bulk_create(a_crear, batch_size=500)
            if fire_alerts:
                _fire_band_alerts(a_crear)
    return rep


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
