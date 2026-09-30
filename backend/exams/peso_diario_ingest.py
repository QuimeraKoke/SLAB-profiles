"""The first team's daily weigh-in → `peso_talla` (Nutricional).

Source: the nutrition staff's Google Sheet, tab **"Registro peso diario"** —
one row per player, one column per DAY (headed by a date serial), the cell is
the morning weight in kg. Kept live: a column is added every training day.

Wide, not long
--------------
The day lives in the header, not in a column, so each (player, day) cell with
a number becomes one `peso_talla` result. The row's own `Estatura` and
`Peso IDEAL` ride along on every result: IMC and "difference to ideal" are
then computed per day, and a change of target is dated instead of rewriting
the past.

What a cell can be besides a weight
-----------------------------------
`sub20` (the player was with the Sub 20 that day), `selección`, `op` /
`operación`, `tarde`, `-`, or blank. None of them is a weight, so none becomes
a result; they are COUNTED in the report — they explain the gaps in a chart.

Corrections are applied
-----------------------
Unlike the additive formativo importers, a weight the staff correct in the
sheet updates the stored result: each result carries
`result_data["origen_id"] = "<player>|<day>"`, and a changed value on a
re-read replaces the old one. Rows this importer did not write are never
touched.

Matching reuses the injury importer's tiers (`lesiones_formativo_ingest.
Matcher`): the sheet has only "Nombre" + "Apellido", so it resolves by exact or
partial name, and anything that fits two players is left out and reported.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Club
from exams.calculations import compute_result_data
from exams.lesiones_formativo_ingest import Matcher, norm, norm_cab
from exams.models import ExamResult, ExamTemplate

SHEET_ID = "1I27xvuHdPt82DT1ts4CNoVQxhDBPTdZiT-JYets0Xqc"
HOJA = "Registro peso diario"
ORIGEN = "planilla_peso_diario"
SLUG = "peso_talla"

ESTADOS = {
    "SUB": "Sub 20",            # "sub20", "sub 20" (norm drops the digits)
    "SELECCION": "Selección",
    "OP": "Operación", "OPERACION": "Operación",
    "TARDE": "Tarde",
}

_EPOCH = date(1899, 12, 30)


def _serial(v) -> date | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and 30000 < v < 80000:
        return _EPOCH + timedelta(days=int(v))
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


@dataclass
class FilaPeso:
    fila: int
    nombre: str
    categoria: str
    estatura: float | None
    peso_ideal: float | None
    pesos: dict[date, float] = field(default_factory=dict)
    estados: Counter = field(default_factory=Counter)


def parse(grid) -> tuple[list[FilaPeso], list[date]]:
    filas = [list(r) for r in grid]
    # The first rows can be blank: the header is the first one with content.
    inicio = next(i for i, r in enumerate(filas) if any(str(c).strip() for c in r))
    cab = filas[inicio]
    ix = {norm_cab(c): i for i, c in enumerate(cab) if isinstance(c, str) and c.strip()}
    i_ape = ix.get("APELLIDO", 1)
    i_cat = ix.get("CATEGORIA")
    i_est = ix.get("ESTATURA")
    i_ideal = ix.get("PESO IDEAL")
    dias = [(i, d) for i, c in enumerate(cab) if (d := _serial(c))]

    out = []
    for n, r in enumerate(filas[inicio + 1:], start=inicio + 2):
        r = r + [""] * (len(cab) - len(r))
        nombre = f"{str(r[0]).strip()} {str(r[i_ape]).strip()}".strip()
        if not str(r[i_ape]).strip():
            continue
        fp = FilaPeso(
            fila=n, nombre=nombre,
            categoria=str(r[i_cat]).strip() if i_cat is not None else "",
            estatura=_num(r[i_est]) if i_est is not None else None,
            peso_ideal=_num(r[i_ideal]) if i_ideal is not None else None,
        )
        for i, d in dias:
            v = r[i]
            peso = _num(v)
            if peso is not None:
                fp.pesos[d] = peso
            elif str(v).strip():
                fp.estados[ESTADOS.get(norm(v), str(v).strip())] += 1
        out.append(fp)
    return out, [d for _, d in dias]


@dataclass
class Reporte:
    jugadores: int = 0
    emparejados: int = 0
    creados: int = 0
    actualizados: int = 0
    iguales: int = 0
    fuera_de_rango: list = field(default_factory=list)
    sin_jugador: list = field(default_factory=list)
    ambiguos: list = field(default_factory=list)
    estados: Counter = field(default_factory=Counter)
    desde: date | None = None
    hasta: date | None = None
    por_metodo: Counter = field(default_factory=Counter)


def leer(origen: str = SHEET_ID, *, creds_file: str = "", creds_json: str = ""):
    from exams.formativo_sources import abrir, match_sheet

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    hoja = match_sheet(fuente.hojas(), HOJA)
    if hoja is None:
        raise ValueError(f"El documento no tiene la hoja {HOJA!r}")
    filas, dias = parse(fuente.filas(hoja))
    fuente.cerrar()
    return filas, dias


def run(club: Club, filas: list[FilaPeso], dias: list[date], *, commit: bool = False) -> Reporte:
    template = (ExamTemplate.objects.filter(slug=SLUG, department__club=club,
                                            is_active_version=True).first())
    if template is None:
        raise ValueError(f"No existe la plantilla '{SLUG}' — correr seed_peso_talla.")
    rango = {f["key"]: (f.get("min"), f.get("max"))
             for f in template.config_schema.get("fields", [])}

    matcher = Matcher(club, {})
    rep = Reporte(jugadores=len(filas), desde=min(dias, default=None), hasta=max(dias, default=None))

    existentes = {
        r.result_data.get("origen_id"): r
        for r in ExamResult.objects.filter(template__family_id=template.family_id,
                                           result_data__origen=ORIGEN)
    }
    crear: list[ExamResult] = []
    actualizar: list[ExamResult] = []
    tocados: set = set()

    for fp in filas:
        rep.estados.update(fp.estados)
        m = matcher.match_name(fp.nombre)
        rep.por_metodo[m.metodo] += 1
        if m.player is None:
            destino = rep.ambiguos if m.metodo == "ambiguo" else rep.sin_jugador
            destino.append(f"{fp.nombre} ({fp.categoria}, fila {fp.fila}, {len(fp.pesos)} pesos)")
            continue
        rep.emparejados += 1
        p = m.player
        for dia, peso in sorted(fp.pesos.items()):
            lo, hi = rango.get("peso", (None, None))
            if (lo is not None and peso < lo) or (hi is not None and peso > hi):
                rep.fuera_de_rango.append(f"{fp.nombre} {dia}: {peso}")
                continue
            crudo: dict[str, Any] = {"peso": peso}
            if fp.estatura:
                crudo["altura"] = fp.estatura
            if fp.peso_ideal:
                crudo["peso_ideal"] = fp.peso_ideal
            datos, snapshot = compute_result_data(template, crudo, player=p)
            oid = f"{p.pk}|{dia.isoformat()}"
            datos.update({"origen": ORIGEN, "origen_id": oid, "origen_hoja": HOJA})
            viejo = existentes.get(oid)
            if viejo is None:
                crear.append(ExamResult(
                    player=p, template=template, result_data=datos, inputs_snapshot=snapshot,
                    recorded_at=timezone.make_aware(datetime.combine(dia, time(8, 0)))))
                rep.creados += 1
                tocados.add(p.pk)
            elif viejo.result_data != datos:
                viejo.result_data, viejo.inputs_snapshot = datos, snapshot
                actualizar.append(viejo)
                rep.actualizados += 1
                tocados.add(p.pk)
            else:
                rep.iguales += 1

    if commit and (crear or actualizar):
        with transaction.atomic():
            ExamResult.objects.bulk_create(crear, batch_size=500)
            ExamResult.objects.bulk_update(actualizar, ["result_data", "inputs_snapshot"],
                                           batch_size=500)
        _refrescar(tocados, template)
    return rep


def _refrescar(player_ids, template) -> None:
    """What `bulk_create` skipped: the player's card weight and his state."""
    from decimal import Decimal

    from core.models import Player
    from dashboards.player_state import upsert_player_state

    por_jugador = defaultdict(lambda: None)
    for r in (ExamResult.objects.filter(template__family_id=template.family_id,
                                        player_id__in=player_ids)
              .order_by("player_id", "-recorded_at")
              .only("player_id", "result_data")):
        if por_jugador[r.player_id] is None:
            por_jugador[r.player_id] = r.result_data
    for p in Player.objects.filter(pk__in=player_ids).select_related("category", "position"):
        datos = por_jugador.get(p.pk) or {}
        cambios = []
        if isinstance(datos.get("peso"), (int, float)):
            p.current_weight_kg = Decimal(str(datos["peso"]))
            cambios.append("current_weight_kg")
        if isinstance(datos.get("altura"), (int, float)):
            p.current_height_cm = Decimal(str(datos["altura"]))
            cambios.append("current_height_cm")
        if cambios:
            p.save(update_fields=cambios)
        upsert_player_state(p)
