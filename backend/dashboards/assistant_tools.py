"""Live-data tools for the floating team assistant.

The assistant already reasons over a cached squad *snapshot* (see
`dashboards.assistant.build_team_context`). These tools let it go further and
query the exam database on demand — so it can answer precise, ad-hoc questions
the snapshot doesn't pre-compute:

  - "¿quién es el más rápido?"            → ranking_jugadores(gps…, max_vel_total)
  - "¿quién salta más alto?"               → ranking_jugadores(cmj, …)
  - "¿cuándo fue la última vez que se cargó CK?" → listar_examenes (última_fecha)
  - "mostrame los últimos datos de Assadi"  → historial_jugador

Everything is **read-only**, scoped to the assistant's `category` and its
**active** players, and bounded (row/field/limit caps) so a tool call can't
blow up the context or the DB. Each handler returns a JSON-safe dict; a dict
with an ``"error"`` key is surfaced to the model as a tool error so it can
correct its parameters.
"""

from __future__ import annotations

import json
import logging
import unicodedata

logger = logging.getLogger(__name__)

_MAX_LIMIT = 30
_DEFAULT_LIMIT = 10
_MAX_ALERTS = 20
_MAX_FIELDS = 60          # per template in the catalog
_MAX_HISTORY_VALUES = 24  # value keys returned per historical result
_MAX_VALUE_CHARS = 160    # truncate long free-text values (e.g. molestias)
_RANKABLE_TYPES = ("number", "calculated")


# ─── Tool schemas (sent to the model) ────────────────────────────────

TOOLS = [
    {
        "name": "listar_examenes",
        "description": (
            "Lista los exámenes/tests de la categoría con sus campos medibles "
            "(`campo` = clave, etiqueta, unidad), cuántos resultados tienen, la "
            "ÚLTIMA FECHA con datos y cuántos jugadores tienen datos. Usalo para "
            "(1) descubrir qué se puede consultar y con qué `slug`/`campo` llamar "
            "a las otras herramientas, y (2) responder cuándo fue la última vez "
            "que un examen tuvo datos. No requiere argumentos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "ranking_jugadores",
        "description": (
            "Ordena a los jugadores activos de la categoría por una métrica "
            "numérica de un examen. Para preguntas tipo 'quién es el más "
            "rápido' (velocidad máxima de GPS), 'quién salta más alto' (CMJ), "
            "'quién tiene peor wellness', etc. Si no conocés el `slug`/`campo` "
            "exactos, llamá primero a listar_examenes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "slug del examen (ver listar_examenes)."},
                "campo": {"type": "string", "description": "clave del campo numérico a ordenar."},
                "agregacion": {
                    "type": "string",
                    "enum": ["ultimo", "max", "min", "promedio"],
                    "description": (
                        "Cómo resumir los varios resultados de cada jugador. "
                        "'ultimo' = valor más reciente (default); 'max'/'min' = "
                        "mejor/peor marca histórica; 'promedio' = media."
                    ),
                },
                "orden": {
                    "type": "string",
                    "enum": ["desc", "asc"],
                    "description": (
                        "desc = de mayor a menor (default; usalo para 'el más "
                        "rápido/más alto'). asc = de menor a mayor ('el más bajo')."
                    ),
                },
                "limite": {"type": "integer", "description": "cuántos devolver (default 10, máx 30)."},
                "dias": {"type": "integer", "description": "opcional: considerar solo los últimos N días."},
            },
            "required": ["slug", "campo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "historial_jugador",
        "description": (
            "Devuelve los resultados recientes de UN jugador (buscado por "
            "nombre), opcional­mente limitados a un examen. Para 'cuándo fue la "
            "última vez que X hizo un CMJ' o 'mostrame los últimos datos de Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "jugador": {"type": "string", "description": "nombre del jugador (o parte de él)."},
                "slug": {"type": "string", "description": "opcional: limitar a un examen."},
                "limite": {"type": "integer", "description": "cuántos resultados recientes (default 10, máx 30)."},
            },
            "required": ["jugador"],
            "additionalProperties": False,
        },
    },
    {
        "name": "estado_jugador",
        "description": (
            "Ficha cruzada (multi-área) del estado ACTUAL de UN jugador: "
            "disponibilidad, readiness con su justificación, carga semanal vs "
            "umbrales, últimas métricas con su banda de referencia (médico, "
            "físico, nutrición…) y alertas activas. Usalo para profundizar en "
            "un jugador puntual; el plantel del snapshot solo trae nombre, "
            "posición, estado y edad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "jugador": {"type": "string", "description": "nombre del jugador (o parte de él)."},
            },
            "required": ["jugador"],
            "additionalProperties": False,
        },
    },
]


# ─── Dispatch ────────────────────────────────────────────────────────


def run_tool(category, name: str, tool_input: dict | None) -> tuple[str, bool]:
    """Execute tool `name` for `category`. Returns ``(json_str, is_error)``.
    Never raises — a failure becomes an error tool-result so the chat survives."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Herramienta desconocida: {name}"}, ensure_ascii=False), True
    try:
        result = handler(category, tool_input or {})
    except Exception:  # noqa: BLE001 — a tool crash must not 500 the chat
        logger.exception("Assistant tool %s failed (input=%s)", name, tool_input)
        return json.dumps({"error": "La consulta falló."}, ensure_ascii=False), True
    is_error = isinstance(result, dict) and "error" in result
    return json.dumps(result, ensure_ascii=False, default=str), is_error


# ─── Handlers ────────────────────────────────────────────────────────


def _listar_examenes(category, _args: dict) -> dict:
    from django.db.models import Count, Max

    from exams.models import ExamResult, ExamTemplate

    pids = _active_pids(category)
    templates = (
        ExamTemplate.objects
        .filter(applicable_categories=category, is_active_version=True)
        .select_related("department")
        .distinct()
    )
    examenes = []
    for t in templates:
        # Aggregate across every version sharing this slug (results from older
        # versions still count toward "has data" and recency).
        version_ids = list(
            ExamTemplate.objects
            .filter(slug=t.slug, applicable_categories=category)
            .values_list("id", flat=True)
        )
        agg = ExamResult.objects.filter(
            template_id__in=version_ids, player_id__in=pids,
        ).aggregate(
            n=Count("id"), last=Max("recorded_at"),
            jugadores=Count("player_id", distinct=True),
        )
        n = agg["n"] or 0
        campos = _catalog_fields(t) if n else []
        examenes.append({
            "slug": t.slug,
            "examen": t.name,
            "area": getattr(t.department, "name", None),
            "resultados": n,
            "ultima_fecha": agg["last"].date().isoformat() if agg["last"] else None,
            "jugadores_con_datos": agg["jugadores"] or 0,
            "campos": campos,
        })
    examenes.sort(key=lambda r: (r["resultados"] == 0, r["examen"].lower()))
    return {
        "categoria": category.name,
        "nota": "Conteos y fechas son solo de jugadores activos del plantel.",
        "examenes": examenes,
    }


def _ranking_jugadores(category, args: dict) -> dict:
    from datetime import timedelta

    from django.utils import timezone

    from exams.models import ExamResult, ExamTemplate

    slug = (args.get("slug") or "").strip()
    campo = (args.get("campo") or "").strip()
    if not slug or not campo:
        return {"error": "Faltan `slug` y/o `campo`. Revisá listar_examenes."}

    agregacion = args.get("agregacion") if args.get("agregacion") in ("ultimo", "max", "min", "promedio") else "ultimo"
    orden = "asc" if args.get("orden") == "asc" else "desc"
    limite = _clamp_limit(args.get("limite"))
    dias = _positive_int(args.get("dias"))

    version_ids = list(
        ExamTemplate.objects
        .filter(slug=slug, applicable_categories=category)
        .values_list("id", flat=True)
    )
    if not version_ids:
        return {"error": f"No existe el examen '{slug}' para esta categoría. Usá listar_examenes para ver los slugs válidos."}

    active = (
        ExamTemplate.objects.filter(slug=slug, applicable_categories=category, is_active_version=True).first()
        or ExamTemplate.objects.filter(slug=slug, applicable_categories=category).first()
    )
    fmeta = _field_meta(active, campo)
    if fmeta is None:
        valid = [f.get("key") for f in _schema_fields(active) if f.get("type") in _RANKABLE_TYPES]
        return {"error": f"El examen '{slug}' no tiene el campo '{campo}'.", "campos_numericos_validos": valid}
    if fmeta.get("type") not in _RANKABLE_TYPES:
        return {"error": f"El campo '{campo}' no es numérico (tipo '{fmeta.get('type')}'); no se puede rankear."}

    info = _active_player_info(category)
    pids = list(info)
    qs = ExamResult.objects.filter(template_id__in=version_ids, player_id__in=pids)
    if dias:
        qs = qs.filter(recorded_at__gte=timezone.now() - timedelta(days=dias))
    rows = qs.order_by("recorded_at").values_list("player_id", "recorded_at", "result_data")

    acc: dict = {}
    for pid, recorded_at, data in rows:
        v = _num((data or {}).get(campo))
        if v is None:
            continue
        acc.setdefault(pid, []).append((v, recorded_at))

    reduced = []
    for pid, vals in acc.items():
        value, fecha = _reduce(vals, agregacion)
        reduced.append((pid, value, fecha))
    reduced.sort(key=lambda r: r[1], reverse=(orden == "desc"))

    ranking = [
        {
            "jugador": info[pid]["nombre"],
            "posicion": info[pid]["posicion"],
            "valor": round(value, 2),
            "fecha": fecha.date().isoformat() if fecha else None,
        }
        for pid, value, fecha in reduced[:limite]
    ]
    return {
        "examen": active.name,
        "slug": slug,
        "campo": campo,
        "etiqueta_campo": fmeta.get("label"),
        "unidad": fmeta.get("unit") or None,
        "agregacion": agregacion,
        "orden": orden,
        "ventana_dias": dias,
        "jugadores_evaluados": len(acc),
        "sin_datos": len(pids) - len(acc),
        "ranking": ranking,
    }


def _historial_jugador(category, args: dict) -> dict:
    from exams.models import ExamResult

    nombre = (args.get("jugador") or "").strip()
    if not nombre:
        return {"error": "Indicá el nombre del jugador."}
    slug = (args.get("slug") or "").strip()
    limite = _clamp_limit(args.get("limite"))

    player, candidatos = _match_player(category, nombre)
    if player is None:
        out = {"error": f"No encontré a '{nombre}' entre los jugadores activos del plantel."}
        if candidatos:
            out["candidatos"] = candidatos
        return out

    qs = ExamResult.objects.filter(player=player).select_related("template")
    if slug:
        qs = qs.filter(template__slug=slug)
    qs = qs.order_by("-recorded_at")[:limite]

    resultados = []
    for r in qs:
        labels = {f.get("key"): f for f in _schema_fields(r.template) if f.get("key")}
        valores = {}
        for k, raw in (r.result_data or {}).items():
            fm = labels.get(k)
            if not fm or fm.get("type") == "file":
                continue
            valores[fm.get("label") or k] = _trim_value(raw)
            if len(valores) >= _MAX_HISTORY_VALUES:
                break
        resultados.append({
            "examen": r.template.name,
            "slug": r.template.slug,
            "fecha": r.recorded_at.date().isoformat(),
            "valores": valores,
        })
    return {
        "jugador": f"{player.first_name} {player.last_name}".strip(),
        "posicion": (player.position.role or player.position.abbreviation) if player.position else None,
        "estado": player.status,
        "resultados": resultados,
    }


def _estado_jugador(category, args: dict) -> dict:
    from dashboards.models import PlayerMetricState, PlayerReadiness
    from goals.models import Alert, AlertStatus

    nombre = (args.get("jugador") or "").strip()
    if not nombre:
        return {"error": "Indicá el nombre del jugador."}
    player, candidatos = _match_player(category, nombre)
    if player is None:
        out = {"error": f"No encontré a '{nombre}' entre los jugadores activos del plantel."}
        if candidatos:
            out["candidatos"] = candidatos
        return out

    state = PlayerMetricState.objects.filter(player=player).first()
    st = (getattr(state, "state", None) or {}) if state else {}
    load = (st.get("weekly_load") or {}).get("metrics") or []
    latest = st.get("latest") or []

    readiness = PlayerReadiness.objects.filter(player=player).first()
    alerts = list(
        Alert.objects.filter(player=player, status=AlertStatus.ACTIVE)
        .order_by("-severity", "-last_fired_at")[:_MAX_ALERTS]
    )

    return {
        "jugador": f"{player.first_name} {player.last_name}".strip(),
        "posicion": (player.position.role or player.position.abbreviation) if player.position else None,
        "estado": player.status,
        "edad": player.age,
        "readiness": (
            {
                "score": readiness.score,
                "fuente": readiness.source,
                "justificacion": readiness.rationale or None,
                "flags": readiness.flags or None,
            }
            if readiness else None
        ),
        "carga_semanal": [
            {"metrica": m.get("label"), "estado": m.get("status"), "total": m.get("total"),
             "min": m.get("min"), "max": m.get("max"), "unidad": m.get("unit")}
            for m in load
        ],
        "metricas_recientes": [
            {"area": m.get("template"), "metrica": m.get("field"), "valor": m.get("value"),
             "unidad": m.get("unit"), "banda": m.get("band")}
            for m in latest
        ],
        "alertas_activas": [
            {"severidad": a.severity, "mensaje": a.message[:160]} for a in alerts
        ],
    }


_HANDLERS = {
    "listar_examenes": _listar_examenes,
    "ranking_jugadores": _ranking_jugadores,
    "historial_jugador": _historial_jugador,
    "estado_jugador": _estado_jugador,
}


# ─── Helpers ─────────────────────────────────────────────────────────


def _active_pids(category) -> list:
    from core.models import Player

    return list(
        Player.objects.filter(category=category, is_active=True).values_list("id", flat=True)
    )


def _active_player_info(category) -> dict:
    from core.models import Player

    info = {}
    for p in (
        Player.objects.filter(category=category, is_active=True).select_related("position")
    ):
        info[p.id] = {
            "nombre": f"{p.first_name} {p.last_name}".strip(),
            "posicion": (p.position.role or p.position.abbreviation) if p.position else None,
        }
    return info


def _schema_fields(template) -> list:
    if template is None:
        return []
    return [
        f for f in (template.config_schema or {}).get("fields") or []
        if isinstance(f, dict) and f.get("key")
    ]


def _catalog_fields(template) -> list:
    out = []
    for f in _schema_fields(template)[:_MAX_FIELDS]:
        out.append({
            "campo": f.get("key"),
            "etiqueta": f.get("label"),
            "tipo": f.get("type"),
            "unidad": f.get("unit") or None,
            "mejor_direccion": f.get("direction_of_good") or None,
            "rankeable": f.get("type") in _RANKABLE_TYPES,
        })
    return out


def _field_meta(template, key: str):
    for f in _schema_fields(template):
        if f.get("key") == key:
            return f
    return None


def _reduce(vals: list, agregacion: str):
    """`vals` is [(value, recorded_at)] ascending by recorded_at."""
    if not vals:
        return None, None
    if agregacion == "max":
        return max(vals, key=lambda x: x[0])
    if agregacion == "min":
        return min(vals, key=lambda x: x[0])
    if agregacion == "promedio":
        return sum(v for v, _ in vals) / len(vals), vals[-1][1]
    return vals[-1]  # "ultimo" — latest recorded_at


def _match_player(category, q: str):
    """Return (player, candidates). Accent-insensitive; exact full-name wins,
    then unique substring/token match; ambiguity returns candidate names."""
    from core.models import Player

    players = list(
        Player.objects.filter(category=category, is_active=True).select_related("position")
    )
    nq = _norm(q)
    if not nq:
        return None, []

    def full(p):
        return _norm(f"{p.first_name} {p.last_name}")

    for p in players:
        if full(p) == nq:
            return p, []

    hits = [p for p in players if nq in full(p) or nq in _norm(p.last_name)]
    if len(hits) == 1:
        return hits[0], []
    if not hits:
        toks = [t for t in nq.split() if t]
        hits = [p for p in players if toks and all(t in full(p) for t in toks)]
    if len(hits) == 1:
        return hits[0], []
    if len(hits) > 1:
        return None, [f"{p.first_name} {p.last_name}".strip() for p in hits[:8]]
    return None, []


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def _num(raw):
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _trim_value(raw):
    if isinstance(raw, str) and len(raw) > _MAX_VALUE_CHARS:
        return raw[:_MAX_VALUE_CHARS] + "…"
    return raw


def _clamp_limit(raw) -> int:
    n = _positive_int(raw)
    if not n:
        return _DEFAULT_LIMIT
    return min(n, _MAX_LIMIT)


def _positive_int(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
