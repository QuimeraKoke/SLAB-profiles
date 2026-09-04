"""Parse and ingest the club's `EVALUACIONES FÍSICAS CATEGORÍAS.xlsx`.

Phase 6 of PLAN_FORMATIVO.md. Six sheets land in five templates:

    CARRERAS                 → carreras           (long: 4 tests per row)
    NEUROMUSCULAR            → neuromuscular      (long: 2 tests per row)
    RESISTENCIA              → resistencia
    RESISTENCIA 1000 METROS  → resistencia_1000m
    FUERZA                   → fuerza  (ejercicio = Sentadilla)
    PRESS DE BANCO           → fuerza  (ejercicio = Press de banco)

Long sheets are pivoted
-----------------------
`CARRERAS` writes one row per (player, date, **test**) — T10, T30, COD 505 der
and izq — so its 4341 rows are 2132 sessions. Loading a result per row would
create four near-empty exams where the club ran one testing session, and every
chart would show four points a day. Rows are grouped by (player, date) and
folded into a single result.

Derived columns are not imported
--------------------------------
`BEST`, `METROS`, `VO2 MAX` (shuttle), `%RM` and `FR` are all computed by the
templates from verified formulas, so importing them would store the same
conclusion twice and let the two drift. Three columns ARE imported, because
SLAB cannot derive them: `PROM` (the engine cannot count how many attempts
were recorded), `VAM` in the shuttle test (a 91-row lookup table) and `VO2 MAX`
in the 1000 m (not a function of time alone). See `seed_formativo_templates`.

Provenance and idempotency
--------------------------
Every row carries three reserved keys in `result_data`, following the pattern
Catapult already established with `result_data["catapult_activity_id"]`:

* `origen` — which source produced the row. Without it, once these rows are in
  nobody can tell a club-spreadsheet HSR (>20 km/h) from a Catapult one
  (>19.8), and comparing the two is exactly what the club asked for.
* `origen_hoja` — the sheet, so a single family can be re-imported.
* `origen_id` — `(player, date, variant)`, queried with a JSONB lookup to skip
  rows already loaded. Re-running is a no-op rather than a duplicate.

Additive: existing results are never overwritten.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Club, Player
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate

ORIGEN = "planilla_club_formativo"

# Long-format sheets: the test name lives in a column, one row per test.
TESTS_LARGOS = {
    "CARRERAS": {
        "T10 (s)": "t10",
        "T30 (s)": "t30",
        "COD 505 DER": "cod_der",
        "COD 505 IZQ": "cod_izq",
    },
    "NEUROMUSCULAR": {
        "CMJ (cm)": "cmj",
        "TIRO (km/h)": "tiro",
    },
}
SLUG_LARGO = {"CARRERAS": "carreras", "NEUROMUSCULAR": "neuromuscular"}

# Wide sheets: column header → template key. Only raw inputs are listed;
# anything the template computes is deliberately absent.
ANCHAS: dict[str, tuple[str, dict[str, str], dict[str, Any]]] = {
    "RESISTENCIA": ("resistencia", {
        "PALIER": "palier",
        "VAM": "vam",
    }, {}),
    "RESISTENCIA 1000 METROS": ("resistencia_1000m", {
        "TIEMPO (S)": "tiempo_s",
        "METROS": "metros",
        "VO2 MAX": "vo2_max",
    }, {}),
    "FUERZA": ("fuerza", {
        "PESO CORPORAL (kg)": "peso_corporal",
        "1RM (kg)": "rm_estimado",
        "ULTIMA CARGA (kg)": "ultima_carga_kg",
        "ULTIMA CARGA (m/s)": "ultima_carga_ms",
    }, {"ejercicio": "Sentadilla"}),
    "PRESS DE BANCO": ("fuerza", {
        "PESO CORPORAL (kg)": "peso_corporal",
        "1RM (kg)": "rm_estimado",
        "ULTIMA CARGA (kg)": "ultima_carga_kg",
        "ULTIMA CARGA (m/s)": "ultima_carga_ms",
    }, {"ejercicio": "Press de banco"}),
}

# `BEST 20 KG` / `BEST (20KG)` → `v_20kg`. The two sheets spell it differently
# and `PRESS DE BANCO` repeats the plain `20 KG` header twice for its two
# attempts, so only the BEST column is read — matching on "BEST" avoids
# picking up whichever duplicate openpyxl happened to index last.
RE_CARGA = re.compile(r"BEST\s*\(?\s*(\d+)\s*KG", re.I)


def norm(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", text).split())


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
    slug: str
    nombre: str
    dob: date | None
    dia: date
    datos: dict[str, Any]
    variante: str = ""

    @property
    def origen_id(self) -> str:
        partes = [norm(self.nombre), self.dia.isoformat(), self.slug]
        if self.variante:
            partes.append(self.variante)
        return "|".join(partes)


@dataclass
class Reporte:
    creados: int = 0
    ya_existian: int = 0
    duplicados_en_archivo: int = 0
    sin_jugador: list[str] = field(default_factory=list)
    sin_plantilla: list[str] = field(default_factory=list)
    sin_datos: int = 0
    sin_fecha: dict = field(default_factory=dict)
    fuera_de_rango: list[str] = field(default_factory=list)
    por_hoja: dict = field(default_factory=lambda: defaultdict(int))
    alertas: int = 0


# ── parsing ─────────────────────────────────────────────────────────────
# The column naming the test is headed `NEUROMUSCULAR` in BOTH long sheets —
# the club built `CARRERAS` by copying the other one and left the header. So it
# cannot be looked up by the sheet's own name: doing that read zero of the 4341
# `CARRERAS` rows and the import reported a clean run.
COL_TEST = ("NEUROMUSCULAR", "EVALUACIÓN", "EVALUACION", "TEST")


def _cabecera(rows):
    for fila in rows:
        cab = [str(c or "").strip() for c in fila]
        if any(c.upper() in ("JUGADOR", "NOMBRE") for c in cab):
            return cab
    return None


def _desfase(cab: list[str], muestras: list[tuple]) -> int:
    """How many columns the data sits to the LEFT of its own header.

    `PRESS DE BANCO` declares `FECHA, JUGADOR, FECHA DE NACIMIENTO, …` but its
    rows start at the player's name: there is no date column at all, so every
    value sits one place left of the header that describes it. Reading it
    literally would have taken `PESO CORPORAL` from the position column.

    Detected by type rather than by sheet name, so a sheet the club fixes (or
    breaks) later is handled without editing this file: the player column must
    hold text and the birth-date column must hold a date.
    """
    ix = {c.upper(): i for i, c in enumerate(cab) if c}
    i_nombre = ix.get("JUGADOR", ix.get("NOMBRE"))
    i_dob = next((i for c, i in ix.items() if "NACIMIENTO" in c), None)
    if i_nombre is None or i_dob is None:
        return 0
    for desfase in (0, 1):
        ok = 0
        for r in muestras:
            n, d = i_nombre - desfase, i_dob - desfase
            if n < 0 or d < 0 or max(n, d) >= len(r):
                continue
            if isinstance(r[n], str) and r[n].strip() and _fecha(r[d]):
                ok += 1
        if muestras and ok >= max(1, len(muestras) // 2):
            return desfase
    return 0


def parse_workbook(
    origen: str, *, creds_file: str = "", creds_json: str = "",
) -> tuple[list[Fila], dict[str, int]]:
    """`origen` is an .xlsx path or a Google Sheets id — see formativo_sources."""
    from exams.formativo_sources import abrir, match_sheet

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    filas: list[Fila] = []
    sin_fecha: dict[str, int] = {}
    hojas = fuente.hojas()
    # The sheets are looked up by the name the parser knows, resolved against
    # the live titles: an export truncates a tab title to 31 characters.
    for conocida, es_largo in ([(h, True) for h in TESTS_LARGOS]
                               + [(h, False) for h in ANCHAS]):
        real = match_sheet(hojas, conocida)
        if real is None:
            continue
        grid = fuente.filas(real)
        nuevas, n = (_parse_largo(grid, conocida) if es_largo
                     else _parse_ancho(grid, conocida))
        filas.extend(nuevas)
        if n:
            sin_fecha[real] = n
    fuente.cerrar()
    return filas, sin_fecha


def _abrir(grid):
    """Header, the rows after it, and the shift the data actually has."""
    filas = [list(f) for f in grid]
    cab = _cabecera(iter(filas))
    if cab is None:
        return None, [], 0
    inicio = next(i for i, f in enumerate(filas)
                  if [str(c or "").strip() for c in f] == cab) + 1
    datos = [f for f in filas[inicio:] if any(v is not None for v in f)]
    return cab, datos, _desfase(cab, datos[:20])


def _indices(cab, desfase=0):
    ix = {c.upper(): i for i, c in enumerate(cab) if c}
    def get(*claves, contiene=None, empieza=None):
        for c, i in ix.items():
            if c in claves or (contiene and contiene in c) or (
                    empieza and c.startswith(empieza) and "NACIMIENTO" not in c):
                j = i - desfase
                return j if j >= 0 else None
        return None
    return (get("JUGADOR", "NOMBRE"), get(contiene="NACIMIENTO"),
            get(empieza="FECHA"))


def _parse_largo(grid, hoja: str) -> list[Fila]:
    """One row per test → one `Fila` per (player, date), tests folded in."""
    cab, datos, desfase = _abrir(grid)
    if cab is None:
        return [], 0
    i_nombre, i_dob, i_dia = _indices(cab, desfase)
    ix = {c.upper(): i - desfase for i, c in enumerate(cab) if c}
    i_test = next((ix[c] for c in COL_TEST if c in ix), None)
    i_reps = [ix.get(f"REP {n}") for n in (1, 2, 3)]
    i_prom = ix.get("PROM")
    mapa = TESTS_LARGOS[hoja]
    if i_test is None:
        return [], len(datos)

    agrupado: dict[tuple, Fila] = {}
    sin_fecha = 0
    for r in datos:
        get = lambda i: r[i] if i is not None and 0 <= i < len(r) else None
        nombre, dia = get(i_nombre), _fecha(get(i_dia))
        prefijo = mapa.get(str(get(i_test) or "").strip())
        if not isinstance(nombre, str) or prefijo is None:
            continue
        if dia is None:
            sin_fecha += 1
            continue
        clave = (norm(nombre), dia)
        fila = agrupado.get(clave)
        if fila is None:
            fila = agrupado[clave] = Fila(
                hoja=hoja, slug=SLUG_LARGO[hoja], nombre=nombre.strip(),
                dob=_fecha(get(i_dob)), dia=dia, datos={})
        for n, i_rep in enumerate(i_reps, 1):
            valor = _num(get(i_rep))
            if valor is not None:
                fila.datos[f"{prefijo}_{n}"] = valor
        prom = _num(get(i_prom))
        if prom is not None:
            fila.datos[f"{prefijo}_prom"] = prom
    return list(agrupado.values()), sin_fecha


def _parse_ancho(grid, hoja: str) -> list[Fila]:
    slug, mapa, fijos = ANCHAS[hoja]
    cab, datos_filas, desfase = _abrir(grid)
    if cab is None:
        return [], 0
    i_nombre, i_dob, i_dia = _indices(cab, desfase)
    columnas = [(i - desfase, mapa[c.upper()]) for i, c in enumerate(cab)
                if c and c.upper() in mapa]
    cargas = [(i - desfase, f"v_{m.group(1)}kg") for i, c in enumerate(cab)
              if c and (m := RE_CARGA.match(c.strip()))]

    filas, sin_fecha = [], 0
    for r in datos_filas:
        get = lambda i: r[i] if i is not None and 0 <= i < len(r) else None
        nombre, dia = get(i_nombre), _fecha(get(i_dia))
        if not isinstance(nombre, str) or not nombre.strip():
            continue
        if dia is None:
            sin_fecha += 1
            continue
        datos: dict[str, Any] = dict(fijos)
        for i, key in columnas:
            valor = _num(get(i))
            if valor is not None:
                datos[key] = valor
        for i, key in cargas:
            valor = _num(get(i))
            # A load the player never attempted is written as 0, not left
            # blank. Kept as a measurement it fails the 0.1 m/s floor and
            # takes the whole session down with it: 678 of 682 FUERZA rows
            # were rejected that way.
            if valor:
                datos[key] = valor
        filas.append(Fila(hoja=hoja, slug=slug, nombre=nombre.strip(),
                          dob=_fecha(get(i_dob)), dia=dia, datos=datos,
                          variante=str(fijos.get("ejercicio", ""))))
    return filas, sin_fecha


# ── matching ────────────────────────────────────────────────────────────
def build_matcher(club: Club):
    """Birth date first, name second — the strategy phase 2 validated.

    The workbooks name players inconsistently (with and without the maternal
    surname, truncated to 22 characters in some sheets), while the birth date
    matched 251 players with zero ambiguity. Token overlap stays as a guard so
    that two people sharing a birth date are never merged: four players in this
    club share 2012-01-04 because of one filled-down cell.
    """
    por_dob: dict[date, list[tuple[set, Player]]] = defaultdict(list)
    por_nombre: dict[str, Player] = {}
    for p in Player.objects.filter(category__club=club).select_related("category"):
        largo = norm(f"{p.first_name} {p.last_name} {p.second_last_name}")
        tokens = set(largo.split())
        if p.date_of_birth:
            por_dob[p.date_of_birth].append((tokens, p))
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


# ── ingest ──────────────────────────────────────────────────────────────
def _descartar_fuera_de_rango(template: ExamTemplate, datos: dict) -> list[str]:
    """Drop values outside their field's own min/max, keep the rest of the row.

    Catches what no chart would: a date serial in a velocity column
    (`v_60kg=45992`), a T30 of 2.68 s (30 m at 40 km/h), a shot at 4 km/h.

    The offending VALUE is dropped rather than the whole session, for two
    reasons. A testing session holds several tests, and one bad COD cell is no
    reason to lose that day's T10. And `best` is a MINIMUM for time tests, so
    keeping an impossibly low value would make it win — the bad number would
    become the headline figure on the chart.
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
    filas, sin_fecha = parse_workbook(
        origen, creds_file=creds_file, creds_json=creds_json)
    rep_sin_fecha = sin_fecha
    if solo_hojas:
        filas = [f for f in filas if f.hoja in solo_hojas]
    match = build_matcher(club)
    rep = Reporte()
    rep.sin_fecha = rep_sin_fecha

    plantillas: dict[str, ExamTemplate | None] = {}
    for slug in {f.slug for f in filas}:
        plantillas[slug] = (
            ExamTemplate.objects.filter(
                slug=slug, department__club=club, is_active_version=True).first()
            or ExamTemplate.objects.filter(slug=slug, department__club=club).first())
        if plantillas[slug] is None:
            rep.sin_plantilla.append(slug)

    # One query for every id we are about to consider, instead of one per row.
    ids = [f.origen_id for f in filas]
    en_base = set(
        ExamResult.objects.filter(result_data__origen=ORIGEN,
                                  result_data__origen_id__in=ids)
        .values_list("result_data__origen_id", flat=True))
    vistos: set[str] = set()

    a_crear: list[ExamResult] = []
    for fila in filas:
        template = plantillas.get(fila.slug)
        if template is None:
            continue
        util = {k: v for k, v in fila.datos.items() if k != "ejercicio"}
        if not util:
            rep.sin_datos += 1
            continue
        if fila.origen_id in en_base:
            rep.ya_existian += 1
            continue
        if fila.origen_id in vistos:
            # Same (player, date, variant) twice in the workbook — 12 of the
            # 682 FUERZA rows. Not a duplicate of something already loaded, so
            # it is counted apart: one is a re-entry, the other means the file
            # needs a look.
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
        if not {k: v for k, v in datos.items() if k != "ejercicio"}:
            rep.sin_datos += 1
            continue

        datos, snapshot = compute_result_data(template, datos, player=player)
        datos["origen"] = ORIGEN
        datos["origen_hoja"] = fila.hoja
        datos["origen_id"] = fila.origen_id
        a_crear.append(ExamResult(
            template=template, player=player,
            recorded_at=timezone.make_aware(
                datetime.combine(fila.dia, datetime.min.time())),
            result_data=datos, inputs_snapshot=snapshot))
        rep.creados += 1
        rep.por_hoja[fila.hoja] += 1
        vistos.add(fila.origen_id)

    if commit and a_crear:
        with transaction.atomic():
            ExamResult.objects.bulk_create(a_crear, batch_size=500)
            if fire_alerts:
                rep.alertas = _fire_band_alerts(a_crear)
    return rep


def _fire_band_alerts(results: list[ExamResult]) -> int:
    """`bulk_create` emits no post_save signals, so alerts are explicit.

    Off by default here: this is a 2024–2026 backfill, and an alert anchored on
    a two-year-old reading is expired again by the next `expire_stale_alerts`
    sweep — firing it would only churn the alert list. Same call as
    `penta_ingest`.
    """
    from goals.evaluator import ALERT_STALE_DAYS, evaluate_threshold_rules_for_result

    corte = timezone.now() - timezone.timedelta(days=ALERT_STALE_DAYS)
    n = 0
    for r in results:
        if r.recorded_at and r.recorded_at >= corte:
            n += len(evaluate_threshold_rules_for_result(r) or [])
    return n
