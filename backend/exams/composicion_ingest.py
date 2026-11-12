"""The formativo's anthropometry summary sheet ("COMPOSICIÓN CORPORAL POWER BI")
→ `pentacompartimental` (Nutricional).

Source: the nutrition staff's Google Sheet, ONE TAB PER CATEGORY (`sub 20`,
`SUB 18` … `sub 11`, `PLANTEL FEM`). Two header rows (a group row —
"Masa Muscular", "Masa Adiposa"… — over a unit row — "kg", "%"…), then one row
per assessment: name, date ("Informes"), and the RESULTS of the 5-component
model, not its raw measurements:

    peso · talla · masa muscular kg/% · masa adiposa kg/% · IMO · Σ 6 pliegues
    (+ Sub 11–14) maduración Mirwald · edad PHV · cm por crecer · estatura proyectada

Values computed outside SLAB
----------------------------
The template's masses are formulas over ~27 raw measurements this sheet does
not carry, so recomputing them here would turn every mass into None. Each row
is stored with `result_data[EXTERNAL] = "planilla"`, and `compute_result_data`
keeps the calculated values such a result already has (it still fills the
ones it can, like IMC from peso/talla). The assessments the club ALSO imported
from the ISAK software (with raw measurements) win: a sheet row within
±`SAME_ASSESSMENT_DAYS` of one of those is skipped, not duplicated — on the
590 rows that overlap today the weight differs by a median 0,0 kg.

Corrections are applied: the rows this importer wrote carry
`origen_id = "<player>|<day>"`, and a changed value on a re-read replaces the
stored one. Rows it did not write are never touched; nothing is deleted.

Matching: the tab says the category, so the name is matched against that
category's players first (`NameMatcher`), then the rest of the club — except
that the women's tab only matches women and the men's tabs only men.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Category, Club, Player
from exams.calculations import EXTERNAL, compute_result_data
from exams.models import ExamResult, ExamTemplate

SHEET_ID = "1yuloU-oN3RUmdAi8Fqv8gdy4XJ1uDx6bY3NPf_y8n9U"
ORIGEN = "planilla_composicion"
SLUG = "pentacompartimental"
SAME_ASSESSMENT_DAYS = 3
FEM_TAB = "PLANTEL FEM"

# (group header, unit header) → field. Matched on normalised text, so a renamed
# or moved column is found by its header and a missing one is just absent.
HEADERS: list[tuple[str, str, str]] = [
    ("MEDIDAS BASICAS", "M. CORPORAL", "peso"),
    ("MEDIDAS BASICAS", "TALLA", "talla"),
    ("MASA MUSCULAR", "KG", "masa_muscular"),
    ("MASA MUSCULAR", "%", "masa_muscular_pct"),
    ("MASA ADIPOSA", "KG", "masa_adiposa"),
    ("MASA ADIPOSA", "%", "masa_adiposa_pct"),
    ("INDICES", "IMO", "imo"),
    ("SUMATORIA DE PLIEGUES", "6 PLIEGUES", "suma_pliegues"),
    ("INDICE DE MADURACION", "MIRWALD", "mirwald_offset"),
    ("PEAK HEIGHT VELOCITY", "MIRWALD", "phv_edad"),
    ("CENTIMETROS POR CRECER", "MIRWALD", "cm_por_crecer"),
    ("ESTATURA PROYECTADA", "MIRWALD", "estatura_proyectada"),
]

# Fields the summary has and the template may not (added in place, never by
# re-seeding — that would overwrite the club's schema).
MATURATION_FIELDS = [
    {"key": "mirwald_offset", "label": "Maduración (años desde el PHV, Mirwald)", "type": "number",
     "unit": "años", "decimals": 2, "min": -6, "max": 6},
    {"key": "phv_edad", "label": "Edad del PHV (Mirwald)", "type": "number", "unit": "años",
     "decimals": 2, "min": 9, "max": 19},
    {"key": "cm_por_crecer", "label": "Centímetros por crecer (Mirwald)", "type": "number", "unit": "cm",
     "decimals": 1, "min": -5, "max": 70},
    {"key": "estatura_proyectada", "label": "Estatura proyectada (Mirwald)", "type": "number", "unit": "cm",
     "decimals": 1, "min": 140, "max": 215},
]

# A row whose kg and % disagree by more than this has its columns shifted.
PCT_TOLERANCE = 2.5


def norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        from integrations.google_sheets.client import serial_to_date

        return serial_to_date(v)
    s = str(v or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


@dataclass
class Fila:
    hoja: str
    fila: int           # 1-based row in the sheet
    nombre: str
    fecha_txt: str
    fecha: date | None
    valores: dict[str, float]


def columnas(grid: list[list[Any]]) -> dict[int, str]:
    """Column index → field, from the two header rows."""
    if len(grid) < 2:
        return {}
    grupo, unidad = grid[0], grid[1]
    out: dict[int, str] = {}
    actual = ""
    for i in range(max(len(grupo), len(unidad))):
        g = norm(grupo[i]) if i < len(grupo) else ""
        actual = g or actual
        u = norm(unidad[i]) if i < len(unidad) else ""
        for grp, uni, key in HEADERS:
            if actual.startswith(grp) and u == uni and key not in out.values():
                out[i] = key
                break
    return out


def parse(hoja: str, grid: list[list[Any]]) -> list[Fila]:
    cols = columnas(grid)
    out = []
    for n, r in enumerate(grid[2:], start=3):
        nombre = str(r[0]).strip() if r else ""
        if not nombre:
            continue
        valores = {}
        for i, key in cols.items():
            if i < len(r) and (v := _num(r[i])) is not None:
                valores[key] = v
        fecha = _date(r[1]) if len(r) > 1 else None
        fecha_txt = fecha.strftime("%d/%m/%Y") if fecha else (str(r[1]).strip() if len(r) > 1 else "")
        out.append(Fila(hoja, n, nombre, fecha_txt, fecha, valores))
    return out


def leer(origen: str = SHEET_ID, *, creds_file: str = "", creds_json: str = "") -> tuple[str, list[Fila]]:
    from integrations.google_sheets.client import Documento

    doc = Documento(origen, creds_file=creds_file, creds_json=creds_json)
    titulo = doc.titulo()
    hojas = doc.worksheets()
    filas: list[Fila] = []
    for hoja, grid in doc.values_batch(hojas).items():
        # Only the measurement tabs: the document also has others (a roster
        # "Base de Datos" with RUTs) that are not assessments.
        if {"peso", "talla"} <= set(columnas(grid).values()):
            filas.extend(parse(hoja, grid))
    return titulo, filas


# ── matching ────────────────────────────────────────────────────────────────

def _is_fem(category: Category | None) -> bool:
    return bool(category) and "FEMENINO" in norm(category.name)


def _tab_categories(hoja: str, cats: list[Category], season: int) -> list[Category]:
    if norm(hoja) == FEM_TAB:
        return [c for c in cats if _is_fem(c)]
    m = re.search(r"(\d+)", hoja)
    if not m:
        return []
    sub = int(m.group(1))
    out = []
    for c in cats:
        if _is_fem(c):
            continue
        if re.search(rf"\bSUB-?\s?{sub}\b", norm(c.name)):
            out.append(c)
            continue
        try:
            _, hint = c.season_label_parts(season)
        except Exception:  # noqa: BLE001 — a category without a cohort has no Sub
            hint = ""
        if norm(hint) == f"SUB {sub}":
            out.append(c)
    return out


class _Matchers:
    def __init__(self, club: Club):
        from exams import sheet_aliases
        from exams.formativo_saltos_ingest import NameMatcher

        self._cls = NameMatcher
        self.aliases = sheet_aliases.load(club)
        self.cats = list(Category.objects.filter(club=club))
        players = list(Player.objects.filter(category__club=club).select_related("category"))
        self.by_cat = defaultdict(list)
        for p in players:
            self.by_cat[p.category_id].append(p)
        self.men = [p for p in players if not _is_fem(p.category)]
        self.women = [p for p in players if _is_fem(p.category)]
        self.season = timezone.localdate().year
        self._cache: dict[str, Any] = {}

    def match(self, hoja: str, nombre: str):
        """(player | None, reason). On a tie, the one whose FIRST name is the
        written first word wins: "Grettel Suazo" is Grettel Ainara, not her
        twin Arantza Grettel (same surnames, same birth date)."""
        m = self.for_tab(hoja)
        p, why = m.match(nombre)
        if p is None and why.startswith("ambiguo"):
            first = norm(nombre).split()[:1]
            found = {c.pk: c for pool in (m.team, m.club) for c in m.candidates(nombre, pool)}
            exact = [c for c in found.values() if first and norm(c.first_name).split()[:1] == first]
            if len(exact) == 1:
                return exact[0], "ok (primer nombre)"
        return p, why

    def for_tab(self, hoja: str):
        if hoja not in self._cache:
            fem = norm(hoja) == FEM_TAB
            team = [p for c in _tab_categories(hoja, self.cats, self.season) for p in self.by_cat[c.id]]
            m = self._cls(team, self.women if fem else self.men)
            m.aliases = self.aliases
            self._cache[hoja] = m
        return self._cache[hoja]


# ── run ─────────────────────────────────────────────────────────────────────

@dataclass
class Reporte:
    filas: int = 0
    creados: int = 0
    actualizados: int = 0
    iguales: int = 0
    ya_estaban: int = 0
    repetidas: int = 0
    # {(hoja, nombre): [filas]}
    sin_jugador: dict = field(default_factory=lambda: defaultdict(list))
    ambiguos: dict = field(default_factory=lambda: defaultdict(list))
    # [(Fila, motivo)]
    rechazadas: list = field(default_factory=list)
    fuera_de_rango: list = field(default_factory=list)


def asegurar_campos(template: ExamTemplate) -> list[str]:
    schema = template.config_schema or {}
    fields = schema.setdefault("fields", [])
    tiene = {f.get("key") for f in fields if isinstance(f, dict)}
    nuevas = [dict(f) for f in MATURATION_FIELDS if f["key"] not in tiene]
    fields.extend(nuevas)
    template.config_schema = schema
    return [f["key"] for f in nuevas]


def _es(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _incoherente(v: dict[str, float]) -> str | None:
    peso = v.get("peso")
    if not peso:
        return None
    for kg, pct, label in (("masa_muscular", "masa_muscular_pct", "masa muscular"),
                           ("masa_adiposa", "masa_adiposa_pct", "masa adiposa")):
        if v.get(kg) is not None and v.get(pct) is not None and abs(v[kg] / peso * 100 - v[pct]) > PCT_TOLERANCE:
            return (f"Los kg y el % de {label} no cuadran ({_es(v[kg])} kg de {_es(peso)} kg no es {_es(v[pct])} %): "
                    "parece que las columnas de la fila están corridas.")
    return None


def run(club: Club, filas: list[Fila], *, commit: bool = False) -> Reporte:
    template = (ExamTemplate.objects.filter(slug=SLUG, department__club=club, is_active_version=True)
                .first())
    if template is None:
        raise ValueError(f"No existe la plantilla '{SLUG}' en {club}.")
    if commit and asegurar_campos(template):
        template.save(update_fields=["config_schema"])
    else:
        asegurar_campos(template)  # in memory: the ranges below include them
    rango = {f["key"]: (f.get("min"), f.get("max"))
             for f in (template.config_schema or {}).get("fields", []) if isinstance(f, dict)}
    fam = template.family_id or template.id

    rep = Reporte(filas=len(filas))
    matchers = _Matchers(club)

    propios: dict[str, ExamResult] = {}
    ajenos: dict[Any, list[date]] = defaultdict(list)
    for r in ExamResult.objects.filter(template__family_id=fam, player__category__club=club):
        if (r.result_data or {}).get("origen") == ORIGEN:
            propios[r.result_data.get("origen_id")] = r
        else:
            ajenos[r.player_id].append(timezone.localtime(r.recorded_at).date())

    por_clave: dict[str, tuple[Fila, Player, dict]] = {}
    for f in filas:
        p, why = matchers.match(f.hoja, f.nombre)
        if p is None:
            (rep.ambiguos if why.startswith("ambiguo") else rep.sin_jugador)[(f.hoja, f.nombre)].append(f.fila)
            continue
        if f.fecha is None:
            rep.rechazadas.append((f, "La fila no tiene una fecha válida en «Informes»"
                                      + (f" ({f.fecha_txt})." if f.fecha_txt else ".")))
            continue
        if f.fecha > timezone.localdate():
            rep.rechazadas.append((f, f"La fecha {f.fecha_txt} está en el futuro."))
            continue
        # A value outside its metric's possible range is left out (and
        # reported); the rest of the row still loads.
        malos = [k for k, v in f.valores.items()
                 if (lo := rango.get(k, (None, None))[0]) is not None and v < lo
                 or (hi := rango.get(k, (None, None))[1]) is not None and v > hi]
        if malos:
            rep.fuera_de_rango.append((f, malos))
        if not f.valores.get("peso") or not f.valores.get("talla") or {"peso", "talla"} & set(malos):
            rep.rechazadas.append((f, "Le falta el peso o la talla, o no son valores posibles."))
            continue
        if (motivo := _incoherente(f.valores)) is not None:
            rep.rechazadas.append((f, motivo))
            continue
        valores = {k: v for k, v in f.valores.items() if k not in malos}
        if any(abs((d - f.fecha).days) <= SAME_ASSESSMENT_DAYS for d in ajenos.get(p.id, ())):
            rep.ya_estaban += 1
            continue
        clave = f"{p.pk}|{f.fecha.isoformat()}"
        if clave in por_clave:
            rep.repetidas += 1
        por_clave[clave] = (f, p, valores)  # the lower row wins: the sheet is edited downward

    crear: list[ExamResult] = []
    actualizar: list[ExamResult] = []
    for clave, (f, p, valores) in por_clave.items():
        crudo: dict[str, Any] = {**valores, EXTERNAL: "planilla"}
        datos, snapshot = compute_result_data(template, crudo, player=p)
        datos.update({"origen": ORIGEN, "origen_id": clave, "origen_hoja": f.hoja})
        viejo = propios.get(clave)
        if viejo is None:
            crear.append(ExamResult(
                player=p, template=template, result_data=datos, inputs_snapshot=snapshot,
                recorded_at=timezone.make_aware(datetime.combine(f.fecha, time(12, 0)))))
        elif viejo.result_data != datos:
            viejo.result_data, viejo.inputs_snapshot = datos, snapshot
            actualizar.append(viejo)
        else:
            rep.iguales += 1
    rep.creados, rep.actualizados = len(crear), len(actualizar)

    if commit and (crear or actualizar):
        from exams.penta_ingest import _fire_band_alerts

        with transaction.atomic():
            ExamResult.objects.bulk_create(crear, batch_size=500)
            ExamResult.objects.bulk_update(actualizar, ["result_data", "inputs_snapshot"], batch_size=500)
            _fire_band_alerts(crear)
        _refrescar({r.player_id for r in (*crear, *actualizar)})
    return rep


def _refrescar(player_ids) -> None:
    """What `bulk_create` skipped: each player's computed state."""
    from dashboards.player_state import upsert_player_state

    for p in Player.objects.filter(pk__in=player_ids).select_related("category", "position"):
        upsert_player_state(p)


def resumen(rep: Reporte) -> dict:
    return {"filas": rep.filas, "creados": rep.creados, "actualizados": rep.actualizados,
            "iguales": rep.iguales, "ya_estaban": rep.ya_estaban, "repetidas": rep.repetidas,
            "sin_jugador": len(rep.sin_jugador), "ambiguos": len(rep.ambiguos),
            "rechazadas": len(rep.rechazadas), "fuera_de_rango": len(rep.fuera_de_rango)}

