"""MD+2: the morning-after-next check of the squad — CK, hydration, CMJ and
central fatigue — entered and read on one screen.

Two days after a match the medical/physical staff take four tests. They used
to go into four forms, one template at a time, none of them tied to the
match. Here:

* the MATCH is picked for them: the latest one actually PLAYED (the club's
  calendar holds duplicates — a COMET sheet and an API-Football fixture for
  the same game, the second with no participants — and scheduled cups);
* the PLAYERS who played it come first, the rest of the squad folded below;
* one table takes the four tests and saves them together, each result
  linked to the match and labelled `md_label = "MD+2"` (club-authored, so
  the calendar never relabels it), dated match day + 2;
* the same table reads as a TRAFFIC LIGHT per test and per player.

The light, per test (decided with the club, 2026-10-22):
* CK, hydration, central fatigue — the field's bands (category bands first,
  `dashboards.category_bands`), mapped to green / amber / red by colour;
* CMJ — against the player's OWN reference: the drop from the mean of his
  last readings before this one (< 5 % green, 5–10 % amber, > 10 % red),
  because a player who jumps 38 cm is not in trouble if he always does.
A test applies to a category only if its template applies to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

MD_LABEL = "MD+2"
DIAS = 2
CMJ_REFERENCIA_N = 5          # readings that make a player's CMJ reference
CMJ_AMARILLO = -5.0           # % drop from the reference
CMJ_ROJO = -10.0
PARTIDOS_OPCIONES = 8


@dataclass(frozen=True)
class Prueba:
    key: str
    slug: str
    label: str
    campos: tuple[str, ...]          # what the table takes
    indicadores: tuple[str, ...]     # what the light reads (may be calculated)
    relativo: bool = False           # CMJ: against the player's reference


PRUEBAS = (
    Prueba("ck", "ck", "CK", ("valor",), ("valor",)),
    Prueba("hidratacion", "densidad_urinaria", "Hidratación",
           ("densidad_urinaria",), ("densidad_urinaria",)),
    Prueba("cmj", "cmj", "CMJ", ("jump_height",), ("jump_height",), relativo=True),
    Prueba("fatiga_central", "fatiga_central", "Fatiga central",
           ("i1", "i2", "i3", "pr", "ea"), ("delta_basal_pct", "pr", "ea")),
)

ORDEN = {"verde": 0, "amarillo": 1, "rojo": 2}
# The COMET sheet records the role, not always the minutes.
ROLES_QUE_JUEGAN = {"titular", "suplente_ingresa"}


def _jugo(part) -> bool:
    return part is not None and ((part.minutes_played or 0) > 0
                                 or part.match_role in ROLES_QUE_JUEGAN)


# ─── traffic-light colours ───────────────────────────────────────────────

def _nivel_de_color(hex_color: str | None, alerta: bool = False) -> str:
    """The club's band colours → green / amber / red. Red when the band says
    so (`alert`) or is red-ish; amber for orange/yellow; anything else
    (greens, the blue "Elite") is fine."""
    if alerta:
        return "rojo"
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return "verde"
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if r > 0.6 and g < 0.45:
        return "rojo"
    if r > 0.7 and g >= 0.45 and b < 0.45:
        return "amarillo"
    return "verde"


def _nivel_de_banda(valor: float, bandas: list[dict]) -> tuple[str | None, str | None]:
    from exams.bands import band_for_value

    banda = band_for_value(valor, bandas) if bandas else None
    if banda is None:
        return None, None
    return _nivel_de_color(banda.get("color"), bool(banda.get("alert"))), banda.get("label")


# ─── the match ──────────────────────────────────────────────────────────

def partidos_jugados(category, limite: int = PARTIDOS_OPCIONES) -> list:
    """The category's matches that were PLAYED, newest first: past, and with
    a sheet (participants) or a PLAYED status — not the duplicate fixture
    with nobody on it, not the cup that is only scheduled."""
    from events.models import Event

    return list(
        Event.objects.filter(category=category, event_type=Event.TYPE_MATCH,
                             starts_at__lte=timezone.now())
        .annotate(n=Count("participants"))
        .filter(Q(n__gt=0) | Q(metadata__status="PLAYED"))
        .order_by("-starts_at")[:limite]
    )


def fecha_md2(evento) -> date:
    return timezone.localtime(evento.starts_at).date() + timedelta(days=DIAS)


# ─── the screen ─────────────────────────────────────────────────────────

@dataclass
class Contexto:
    category: Any
    evento: Any
    pruebas: list[tuple[Prueba, Any]] = field(default_factory=list)  # (prueba, template)


def contexto(category, evento) -> Contexto:
    from exams.models import ExamTemplate

    ctx = Contexto(category, evento)
    for pr in PRUEBAS:
        t = (ExamTemplate.objects.filter(department__club=category.club, slug=pr.slug,
                                         is_active_version=True,
                                         applicable_categories=category).first())
        if t is not None:
            ctx.pruebas.append((pr, t))
    return ctx


def _campo(template, key: str) -> dict:
    return next((f for f in (template.config_schema or {}).get("fields") or []
                 if f.get("key") == key), {"key": key, "label": key})


def payload(ctx: Contexto) -> dict:
    """Everything the screen draws: the match, the tests and their fields,
    and per player the values entered for THIS match's MD+2 with their light."""
    from core.models import Player
    from dashboards import category_bands
    from events.models import EventParticipant
    from exams.models import ExamResult

    evento, category = ctx.evento, ctx.category
    dia = fecha_md2(evento)
    participaciones = {p.player_id: p for p in
                       EventParticipant.objects.filter(event=evento)}
    plantel = list(Player.objects.filter(category=category, is_active=True)
                   .select_related("position").order_by("last_name", "first_name"))
    # Someone who played but has moved category since still belongs here.
    extra = (Player.objects.filter(pk__in=[pid for pid, p in participaciones.items() if _jugo(p)])
             .exclude(pk__in=[p.pk for p in plantel]).select_related("position"))
    jugadores = plantel + list(extra)

    actuales: dict = {}
    for r in ExamResult.objects.filter(
            event=evento, result_data__md_label=MD_LABEL,
            template__family_id__in=[t.family_id for _, t in ctx.pruebas],
            player__in=jugadores).select_related("template"):
        actuales[(r.player_id, r.template.family_id)] = r

    referencias = _referencias_cmj(ctx, jugadores, dia)
    with category_bands.scope(category.id):
        bandas = {(pr.key, k): category_bands.for_field(t, k, _campo(t, k).get("reference_ranges"))
                  for pr, t in ctx.pruebas for k in pr.indicadores}

    filas = []
    for p in jugadores:
        part = participaciones.get(p.id)
        minutos = (part.minutes_played or 0) if part else 0
        roles = dict(EventParticipant.MatchRole.choices)
        valores, luces = {}, {}
        for pr, t in ctx.pruebas:
            r = actuales.get((p.id, t.family_id))
            datos = (r.result_data or {}) if r else {}
            valores[pr.key] = {"result_id": str(r.pk) if r else None,
                               **{k: datos.get(k) for k in (*pr.campos, *pr.indicadores)}}
            luces[pr.key] = _luz(pr, datos, bandas, referencias.get(p.id)) if r else None
        niveles = [l["nivel"] for l in luces.values() if l and l.get("nivel")]
        filas.append({
            "player_id": str(p.id),
            "nombre": f"{p.first_name} {p.last_name}".strip(),
            "posicion": p.position.abbreviation if p.position else "",
            "jugo": _jugo(part),
            "minutos": minutos or None,
            "rol": roles.get(part.match_role) if part and part.match_role else None,
            "valores": valores,
            "luces": luces,
            "general": max(niveles, key=ORDEN.get) if niveles else None,
            "cmj_referencia": referencias.get(p.id),
        })
    filas.sort(key=lambda f: (not f["jugo"], -ORDEN.get(f["general"] or "verde", 0) if f["jugo"] else 0,
                              f["nombre"]))

    return {
        "partido": _evento_out(evento),
        "fecha_md2": dia.isoformat(),
        "es_hoy": dia == timezone.localdate(),
        "opciones": [_evento_out(e) for e in partidos_jugados(category)],
        "pruebas": [{
            "key": pr.key, "label": pr.label, "template_id": str(t.id), "relativo": pr.relativo,
            "campos": [{k: _campo(t, c).get(k) for k in ("key", "label", "unit", "min", "max", "step")}
                       for c in pr.campos],
        } for pr, t in ctx.pruebas],
        "criterio_cmj": {"amarillo": CMJ_AMARILLO, "rojo": CMJ_ROJO, "n": CMJ_REFERENCIA_N},
        "jugadores": filas,
    }


def _evento_out(e) -> dict:
    meta = e.metadata or {}
    return {"id": str(e.id), "titulo": e.title, "fecha": timezone.localtime(e.starts_at).date().isoformat(),
            "marcador": meta.get("score"), "fecha_md2": fecha_md2(e).isoformat()}


def _referencias_cmj(ctx: Contexto, jugadores, dia: date) -> dict:
    """Per player, the mean of his last CMJ heights BEFORE the MD+2 day."""
    from exams.models import ExamResult

    t = next((t for pr, t in ctx.pruebas if pr.relativo), None)
    if t is None:
        return {}
    corte = timezone.make_aware(datetime.combine(dia, time.min))
    vistos: dict = {}
    for pid, data in (ExamResult.objects
                      .filter(template__family_id=t.family_id, player__in=jugadores,
                              recorded_at__lt=corte)
                      .order_by("player_id", "-recorded_at")
                      .values_list("player_id", "result_data")):
        v = (data or {}).get("jump_height")
        if isinstance(v, (int, float)) and len(vistos.setdefault(pid, [])) < CMJ_REFERENCIA_N:
            vistos[pid].append(float(v))
    return {pid: round(sum(vs) / len(vs), 1) for pid, vs in vistos.items() if vs}


def _luz(pr: Prueba, datos: dict, bandas: dict, referencia: float | None) -> dict | None:
    if pr.relativo:
        v = datos.get("jump_height")
        if not isinstance(v, (int, float)):
            return None
        if not referencia:
            return {"nivel": None, "detalle": "sin referencia previa", "valor": v}
        cambio = (v - referencia) / referencia * 100
        nivel = "rojo" if cambio < CMJ_ROJO else "amarillo" if cambio < CMJ_AMARILLO else "verde"
        return {"nivel": nivel, "valor": v, "cambio_pct": round(cambio, 1),
                "detalle": f"{cambio:+.1f} % vs su referencia ({referencia} cm)".replace(".", ",")}
    peor, detalles, valor = None, [], None
    for k in pr.indicadores:
        v = datos.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        valor = v if valor is None else valor
        nivel, etiqueta = _nivel_de_banda(float(v), bandas.get((pr.key, k)) or [])
        if nivel is None:
            continue
        if etiqueta:
            detalles.append(etiqueta)
        if peor is None or ORDEN[nivel] > ORDEN[peor]:
            peor = nivel
    if valor is None:
        return None
    out = {"nivel": peor, "valor": valor, "detalle": " · ".join(dict.fromkeys(detalles))}
    if pr.key == "fatiga_central" and isinstance(datos.get("delta_basal_pct"), (int, float)):
        # The light reads the change from his basal, not a frequency.
        out["texto"] = f"{datos['delta_basal_pct']:+.1f} % vs basal".replace(".", ",")
    return out


# ─── saving ────────────────────────────────────────────────────────────

def guardar(ctx: Contexto, filas: list[dict], *, allowed_players: set) -> dict:
    """Upsert, per player and test, the MD+2 result of this match. A test
    whose cells are all empty is skipped (and an existing one is left as
    it is — clearing is the record's delete, not a blank cell)."""
    from django.db import transaction

    from core.models import Player
    from exams.calculations import compute_result_data
    from exams.microcycle import MD_SOURCE_CLUB, MD_SOURCE_KEY
    from exams.models import ExamResult

    dia = fecha_md2(ctx.evento)
    cuando = timezone.make_aware(datetime.combine(dia, time(9, 0)))
    pruebas = {pr.key: (pr, t) for pr, t in ctx.pruebas}
    creados = actualizados = 0
    with transaction.atomic():
        for fila in filas:
            pid = str(fila.get("player_id") or "")
            if pid not in allowed_players:
                continue
            player = Player.objects.get(pk=pid)
            for key, valores in (fila.get("valores") or {}).items():
                if key not in pruebas or not isinstance(valores, dict):
                    continue
                pr, t = pruebas[key]
                crudo = {c: valores.get(c) for c in pr.campos
                         if valores.get(c) not in (None, "")}
                if not crudo:
                    continue
                for c, v in list(crudo.items()):
                    try:
                        crudo[c] = float(v)
                    except (TypeError, ValueError):
                        crudo.pop(c)
                if not crudo:
                    continue
                existente = (ExamResult.objects.filter(
                    player=player, template__family_id=t.family_id, event=ctx.evento,
                    result_data__md_label=MD_LABEL).first())
                base = dict(existente.result_data or {}) if existente else {}
                base.update(crudo)
                base.update({"fecha": dia.isoformat(), "md_label": MD_LABEL,
                             MD_SOURCE_KEY: MD_SOURCE_CLUB})
                datos, snapshot = compute_result_data(t, base, player=player)
                if existente:
                    existente.result_data = datos
                    existente.inputs_snapshot = snapshot
                    existente.save(update_fields=["result_data", "inputs_snapshot"])
                    actualizados += 1
                else:
                    # `create`, not bulk: alerts and player state follow each result.
                    ExamResult.objects.create(player=player, template=t, event=ctx.evento,
                                              recorded_at=cuando, result_data=datos,
                                              inputs_snapshot=snapshot)
                    creados += 1
    return {"creados": creados, "actualizados": actualizados}
