"""Team injury widgets — aggregations over injury EPISODES, not exam values.

Every other team widget works per player on exam values (latest, average,
sum of a field). An injury report works per INJURY: how many by body region,
cause or position, how many days each player lost, which ones are open. Doing
that with the per-player widgets goes wrong in specific ways — a leaderboard
over `dias_perdidos` sums the opening AND the closing result of every
injury, doubling it — so these read `exams.Episode` directly, through
`exams.injury_ranges`, which already merges each episode's summary.

Three widgets:

* `team_injury_kpis` — headline strip.
* `team_injury_list` — a table of injuries: the open ones, or all in the period.
* `team_injury_breakdown` — injuries grouped by a dimension (region, type,
  muscle, position, cause, context, recurrence, side, severity, month,
  player), measured as a count or as days lost, drawn as bars, donut or table.

Two rules, the same as `/comparar` (frontend `lib/injuryStats.ts`):

* **Counts are injuries that STARTED in the period.** One from last season
  still being rehabbed is not a new injury.
* **Days lost are the days INSIDE the period**, whenever the injury started;
  an open injury counts up to today. Per player the days are a UNION, so two
  overlapping injuries do not count a day twice.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from core.models import Category

from .models import TeamReportWidget

SEVERE_DAYS = 28

DIMENSIONES = {
    "body_part": "Parte del cuerpo",
    "type": "Tipo de lesión",
    "musculo": "Músculo",
    "position": "Posición de juego",
    "modo": "Causa",
    "exposicion": "Exposición",
    "recurrencia": "Recurrencia",
    "lado": "Lateralidad",
    "severity": "Severidad",
    "month": "Mes",
    "player": "Jugador",
}
SIN_DATO = "Sin dato"
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _hoy() -> date:
    return timezone.localdate()


def _dia(dt: datetime | date | None) -> date | None:
    """The calendar day of a datetime. The report API sends its window as NAIVE
    datetimes (parsed from `?date_from=2026-08-31`); episodes are aware."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    return timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()


class _Lesion:
    """One injury with its dates resolved and its fields flattened."""

    def __init__(self, r: dict[str, Any], hoy: date):
        self.r = r
        self.id = str(r["id"])
        self.player_id = str(r["player_id"])
        self.player_name = r["player_name"]
        self.inicio = _dia(r["started_at"])
        self.alta = _dia(r["ended_at"])
        self.abierta = r["status"] == "open"
        self.fin = self.alta or (hoy if self.abierta else self.inicio)
        self.s = r.get("summary") or {}

    @property
    def dias(self) -> int:
        """Whole duration — elapsed so far when open."""
        return max(0, (self.fin - self.inicio).days)

    def dias_en(self, desde: date | None, hasta: date) -> int:
        a = max(self.inicio, desde) if desde else self.inicio
        b = min(self.fin, hasta)
        return max(0, (b - a).days)

    def valor(self, dim: str) -> str:
        s = self.s
        if dim == "player":
            return self.player_name
        if dim == "position":
            return self.r.get("position") or SIN_DATO
        if dim == "month":
            return f"{_MESES[self.inicio.month - 1]} {self.inicio.year}"
        if dim == "severity":
            return s.get("severity") or ("En curso" if self.abierta else SIN_DATO)
        if dim == "exposicion":
            # Official matches were only confirmed from an ANFP sheet; for the
            # rest the club's own "Partido / Entrenamiento" was kept apart.
            v = s.get("exposicion") or s.get("exposicion_club")
            if v and "partido" in v.lower():
                return "Partido"
            return v or SIN_DATO
        v = s.get(dim)
        if dim == "lado" and v == "NA":
            return "No aplica"
        return str(v) if v not in (None, "") else SIN_DATO


def _lesiones(category: Category, position_id, player_ids) -> tuple[list[_Lesion], dict]:
    from exams.injury_ranges import for_players
    from exams.models import ExamTemplate

    from .team_aggregation import _roster_query

    roster = list(_roster_query(category, position_id, player_ids))
    hoy = _hoy()
    filas = for_players([p.id for p in roster], ExamTemplate.objects.all())
    return [_Lesion(r, hoy) for r in filas], {str(p.id): p for p in roster}


def _ventana(date_from: datetime | None, date_to: datetime | None) -> tuple[date | None, date]:
    return (_dia(date_from) if date_from else None,
            min(_dia(date_to), _hoy()) if date_to else _hoy())


def _iniciadas(lesiones, desde, hasta) -> list[_Lesion]:
    return [l for l in lesiones if (desde is None or l.inicio >= desde) and l.inicio <= hasta]


def _dias_por_jugador(lesiones, desde, hasta) -> dict[str, int]:
    """Union of injured days per player, clipped to the window."""
    tramos = defaultdict(list)
    for l in lesiones:
        a = max(l.inicio, desde) if desde else l.inicio
        b = min(l.fin, hasta)
        if a < b:
            tramos[l.player_id].append((a, b))
    out = {}
    for pid, ts in tramos.items():
        ts.sort()
        total, fin = 0, None
        for a, b in ts:
            if fin is None or a > fin:
                total += (b - a).days
                fin = b
            elif b > fin:
                total += (b - fin).days
                fin = b
        out[pid] = total
    return out


def _base(widget: TeamReportWidget, chart_type: str, desde, hasta) -> dict[str, Any]:
    return {
        "chart_type": chart_type,
        "title": widget.title,
        "description": widget.description,
        "column_span": widget.column_span,
        "period": {"from": desde.isoformat() if desde else None, "to": hasta.isoformat()},
    }


# ── resolvers ───────────────────────────────────────────────────────────
def resolve_kpis(widget, category, *, position_id: UUID | None = None,
                 player_ids: Sequence[UUID] | None = None,
                 date_from=None, date_to=None, **_) -> dict[str, Any]:
    lesiones, roster = _lesiones(category, position_id, player_ids)
    desde, hasta = _ventana(date_from, date_to)
    nuevas = _iniciadas(lesiones, desde, hasta)
    dias = _dias_por_jugador(lesiones, desde, hasta)
    abiertas = [l for l in lesiones if l.abierta]
    return _base(widget, "team_injury_kpis", desde, hasta) | {
        "roster_size": len(roster),
        "injured_now": len({l.player_id for l in abiertas}),
        "open_injuries": len(abiertas),
        "injuries": len(nuevas),
        "players_injured": len({l.player_id for l in nuevas}),
        "days_lost": sum(dias.values()),
        "avg_days": round(sum(l.dias for l in nuevas) / len(nuevas), 1) if nuevas else None,
        "severe": sum(1 for l in nuevas if l.dias > SEVERE_DAYS),
        "recurrence_pct": (round(100 * sum(1 for l in nuevas
                                           if l.s.get("recurrencia") == "Recurrente") / len(nuevas))
                           if nuevas else None),
    }


COLUMNAS = ["player", "started", "diagnosis", "lado", "days", "tratamiento", "recurrencia"]
COLUMNAS_TODAS = COLUMNAS + ["body_part", "type", "modo", "severity", "stage", "ended"]


def resolve_list(widget, category, *, position_id: UUID | None = None,
                 player_ids: Sequence[UUID] | None = None,
                 date_from=None, date_to=None, **_) -> dict[str, Any]:
    """`display_config`: `status` "open" (default) | "period"; `columns` (list)."""
    cfg = widget.display_config or {}
    status = cfg.get("status") if cfg.get("status") in ("open", "period") else "open"
    columnas = [c for c in (cfg.get("columns") or COLUMNAS) if c in COLUMNAS_TODAS]
    lesiones, _roster = _lesiones(category, position_id, player_ids)
    desde, hasta = _ventana(date_from, date_to)
    elegidas = ([l for l in lesiones if l.abierta] if status == "open"
                else _iniciadas(lesiones, desde, hasta))
    elegidas.sort(key=lambda l: (l.inicio, l.player_name))
    filas = [{
        "id": l.id,
        "player_id": l.player_id,
        "player": l.player_name,
        "started": l.inicio.isoformat(),
        "ended": l.alta.isoformat() if l.alta else None,
        "open": l.abierta,
        "days": l.dias,
        "diagnosis": l.s.get("diagnosis") or l.r.get("title") or "",
        "lado": l.s.get("lado") or "",
        "tratamiento": l.s.get("tratamiento") or "",
        "recurrencia": {"Recurrente": "Sí", "Nueva": "No"}.get(l.s.get("recurrencia"), ""),
        "body_part": l.s.get("body_part") or "",
        "type": l.s.get("type") or "",
        "modo": l.s.get("modo") or "",
        "severity": l.s.get("severity") or "",
        "stage": l.r.get("stage_label") or "",
    } for l in elegidas]
    return _base(widget, "team_injury_list", desde, hasta) | {
        "status": status, "columns": columnas, "rows": filas, "empty": not filas,
    }


def resolve_breakdown(widget, category, *, position_id: UUID | None = None,
                      player_ids: Sequence[UUID] | None = None,
                      date_from=None, date_to=None, **_) -> dict[str, Any]:
    """`display_config`: `dimension` (DIMENSIONES), `measure` "count" | "days",
    `render` "bar" | "donut" | "table", `limit` (int), `hide_unknown` (bool)."""
    cfg = widget.display_config or {}
    dim = cfg.get("dimension") if cfg.get("dimension") in DIMENSIONES else "body_part"
    medida = cfg.get("measure") if cfg.get("measure") in ("count", "days") else "count"
    render = cfg.get("render") if cfg.get("render") in ("bar", "donut", "table") else "bar"
    limite = int(cfg.get("limit") or 0)

    lesiones, _roster = _lesiones(category, position_id, player_ids)
    desde, hasta = _ventana(date_from, date_to)

    valores: Counter = Counter()
    n: Counter = Counter()
    ids: dict[str, str] = {}
    if medida == "count":
        for l in _iniciadas(lesiones, desde, hasta):
            k = l.valor(dim)
            valores[k] += 1
            n[k] += 1
    elif dim == "player":
        for pid, d in _dias_por_jugador(lesiones, desde, hasta).items():
            nombre = next(l.player_name for l in lesiones if l.player_id == pid)
            valores[nombre] += d
            ids[nombre] = pid
        for l in lesiones:
            if l.dias_en(desde, hasta) > 0:
                n[l.player_name] += 1
    else:
        for l in lesiones:
            d = l.dias_en(desde, hasta)
            if d > 0:
                k = l.valor(dim)
                valores[k] += d
                n[k] += 1
    if dim == "player" and medida == "count":
        ids = {l.player_name: l.player_id for l in lesiones}

    items = [{"label": k, "value": v, "n": n[k], "player_id": ids.get(k)}
             for k, v in valores.items() if v > 0]
    if dim == "month":
        items.sort(key=lambda i: (int(i["label"][-4:]), _MESES.index(i["label"][:3])))
    else:
        items.sort(key=lambda i: (-i["value"], i["label"]))
    desconocido = [i for i in items if i["label"] == SIN_DATO]
    items = [i for i in items if i["label"] != SIN_DATO]
    if limite > 0 and len(items) > limite:
        resto = items[limite:]
        items = items[:limite] + [{"label": f"Otros ({len(resto)})",
                                   "value": sum(i["value"] for i in resto),
                                   "n": sum(i["n"] for i in resto), "player_id": None}]
    if desconocido and not cfg.get("hide_unknown"):
        items += desconocido
    return _base(widget, "team_injury_breakdown", desde, hasta) | {
        "dimension": dim, "dimension_label": DIMENSIONES[dim],
        "measure": medida, "measure_label": "Lesiones" if medida == "count" else "Días perdidos",
        "render": render, "items": items,
        "total": sum(i["value"] for i in items), "empty": not items,
    }
