"""Floating team assistant — a grounded, tool-using chat about the squad.

Answers the staff's free-form questions ("¿quién está en riesgo?", "¿quién es
el más rápido?", "¿cuándo se cargó CK por última vez?") by combining:

  - the specialists' KNOWLEDGE BASES (every active department `InsightAgent`),
  - a light team SNAPSHOT (KPIs, squad counts, next match, decisions, alerts,
    and the roster roll — name/position/status/age only), and
  - DB-SEARCH TOOLS (`dashboards.assistant_tools`) that let the model pull
    precise data on demand instead of us stuffing every metric into the prompt:
    discover exams → rank players by a metric → a player's history / full state.

The model reasons over an agentic loop: it decides which tools to call, we run
them against the DB (read-only, category-scoped, bounded), feed results back,
and repeat until it answers. Reuses the Anthropic SDK conventions from
`pdf/narrative.py`.

Never raises: any failure (no key, API/SDK error) returns a friendly
fallback string so the chat UI always gets a reply.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from core.models import Player
from dashboards.assistant_tools import TOOLS, run_tool

logger = logging.getLogger(__name__)

_MAX_TOKENS = 2000
_MAX_HISTORY = 20  # most recent turns kept (chat stays bounded)
_MAX_CONTENT = 4000  # per-message char cap
_MAX_TOOL_ROUNDS = 5  # agentic loop cap (each round may run several tools)

_MAX_ALERTS = 40
_MAX_METRICS_PER_PLAYER = 12

# Orchestrator persona for the multidisciplinary panel. The specialists'
# knowledge bases (from every active InsightAgent) and a light team snapshot
# are appended at call time; the model pulls precise data via the DB tools.
_ASSISTANT_PROMPT = (
    "Eres el panel de análisis multidisciplinario de SLAB, una plataforma de "
    "ciencias del deporte de un club de fútbol profesional. Integrás las "
    "perspectivas de las áreas médica, física, nutricional, psicosocial y "
    "táctica para responder preguntas del cuerpo técnico sobre el plantel, en "
    "español (Chile), de forma breve, clara y accionable.\n\n"
    "Dispones de:\n"
    "1) la BASE DE CONOCIMIENTO de cada especialista (médico, físico, "
    "nutrición, psicosocial, táctico);\n"
    "2) un SNAPSHOT del equipo: KPIs, estado del plantel, disponibilidad por "
    "línea, próximo partido, jugadores que requieren decisión, calidad de "
    "datos, alertas activas y la lista del plantel (nombre, posición, estado, "
    "edad);\n"
    "3) HERRAMIENTAS para consultar la base de datos en vivo cuando necesitás "
    "datos precisos que el snapshot no trae (valores exactos, rankings, fechas "
    "de carga, ficha detallada de un jugador):\n"
    "   - listar_examenes: qué exámenes/tests existen, sus campos (con su "
    "`slug` y `campo`), cuántos datos tienen y su última fecha con datos.\n"
    "   - ranking_jugadores: ordenar jugadores por una métrica (p. ej. el más "
    "rápido = velocidad máxima de GPS; el que más salta = CMJ).\n"
    "   - historial_jugador: resultados recientes de un jugador puntual.\n"
    "   - estado_jugador: ficha cruzada actual de un jugador (readiness, carga "
    "semanal, métricas con su banda, alertas).\n\n"
    "Cómo trabajar:\n"
    "- Para datos puntuales o numéricos (quién es el más X, un valor exacto, "
    "cuándo se cargó Y, el detalle de un jugador) USÁ las herramientas en vez "
    "de adivinar. Si no conocés el `slug`/`campo` exactos, primero llamá a "
    "listar_examenes y después a la herramienta correcta.\n"
    "- Razoná los pasos: descubrir → consultar → responder. Si una herramienta "
    "devuelve error o vacío, corregí los parámetros (revisá listar_examenes) o "
    "aclaralo en la respuesta.\n"
    "- No inventes datos (valores, lesiones, fechas, métricas). Lo que "
    "devuelven las herramientas y el snapshot es la fuente de verdad; si ahí no "
    "hay datos, decilo claramente.\n"
    "- Cuando la pregunta cruce áreas, integrá las visiones relevantes "
    "(p. ej. «desde lo físico… desde lo médico…»).\n"
    "- Sé conciso y accionable: 1 a 5 frases o una lista corta. Citá valores y "
    "fechas concretos cuando los obtengas de las herramientas.\n"
    "- Si preguntan por un jugador que no está en el plantel, indícalo."
)


def answer_team_question(category, messages: list[dict]) -> str:
    """Return the assistant's reply to the conversation `messages`
    (`[{role, content}]`), grounded in `category`'s current snapshot.
    Never raises — returns a friendly fallback on any failure."""
    from dashboards.pdf.narrative import resolve_insight_agent

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()
    if not api_key:
        return (
            "El asistente de IA no está configurado en este entorno "
            "(falta ANTHROPIC_API_KEY). Aun así podés explorar el Centro de "
            "mando para ver el estado del plantel."
        )

    convo = _sanitize(messages)
    if not convo:
        return "¿En qué puedo ayudarte sobre el plantel?"

    # Optional orchestrator-persona override (InsightAgent key="assistant");
    # the specialist knowledge below comes from ALL the other active agents.
    agent = resolve_insight_agent("assistant")
    model = (
        ((agent.model or "").strip() if agent else "")
        or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-7")
    )
    role = (agent.system_prompt.strip() if agent and agent.system_prompt else "") or _ASSISTANT_PROMPT

    system = role
    if agent and (agent.knowledge or "").strip():
        system += "\n\n# Lineamientos del panel\n" + agent.knowledge.strip()
    specialists = _specialist_knowledge()
    if specialists:
        system += "\n\n" + specialists
    system += (
        "\n\n# Snapshot del equipo (JSON; el detalle por jugador se obtiene "
        "con las herramientas)\n"
        + json.dumps(build_team_overview(category), ensure_ascii=False, default=str)
    )

    return _chat(api_key, model, system, convo, category)


def _specialist_knowledge() -> str:
    """Compose the knowledge bases of every active department `InsightAgent`
    (excluding the orchestrator persona) into one labeled section, so the
    panel reasons with all the specialists' domain expertise at once."""
    try:
        from dashboards.models import InsightAgent

        agents = list(
            InsightAgent.objects.filter(is_active=True).exclude(key="assistant")
        )
    except Exception:  # noqa: BLE001 — DB hiccup must not break the chat
        logger.exception("Failed to gather specialist agents.")
        return ""

    parts: list[str] = []
    for a in agents:
        kb = (a.knowledge or "").strip()
        if not kb:
            continue
        head = f"## {a.name}"
        if (a.description or "").strip():
            head += f" — {a.description.strip()}"
        parts.append(f"{head}\n{kb}")
    if not parts:
        return ""
    return (
        "# Conocimiento de los especialistas (agentes por área)\n\n"
        + "\n\n".join(parts)
    )


def build_team_context(category) -> dict:
    """Full cross-department snapshot the panel reasons over: the Centro de
    mando aggregation + every active alert + the full roster, each player
    carrying their materialized state (status, weekly load vs thresholds,
    and every tracked metric with its reference band — i.e. médico, físico,
    nutrición, etc. data in one place)."""
    from api.command_center import build_command_center, _STATUS_LABEL
    from dashboards.models import PlayerMetricState
    from goals.models import Alert, AlertStatus

    cc = build_command_center(category)
    players = list(
        Player.objects.filter(category=category, is_active=True)
        .select_related("position")
        .order_by("last_name")
    )
    pids = [p.id for p in players]

    states = {
        s.player_id: (s.state or {})
        for s in PlayerMetricState.objects.filter(player_id__in=pids)
    }

    roster = []
    for p in players:
        st = states.get(p.id, {})
        load = (st.get("weekly_load") or {}).get("metrics") or []
        latest = st.get("latest") or []
        roster.append({
            "nombre": f"{p.first_name} {p.last_name}".strip(),
            "posicion": (
                (p.position.role or p.position.abbreviation) if p.position else None
            ),
            "estado": _STATUS_LABEL.get(p.status, p.status),
            "edad": p.age,
            "carga_semanal": [
                {"metrica": m.get("label"), "estado": m.get("status"),
                 "total": m.get("total"), "min": m.get("min"), "max": m.get("max"),
                 "unidad": m.get("unit")}
                for m in load
            ],
            "metricas": [
                {"area": m.get("template"), "metrica": m.get("field"),
                 "valor": m.get("value"), "unidad": m.get("unit"), "banda": m.get("band")}
                for m in latest[:_MAX_METRICS_PER_PLAYER]
            ],
        })

    alerts = list(
        Alert.objects.filter(player_id__in=pids, status=AlertStatus.ACTIVE)
        .select_related("player")
        .order_by("-severity", "-last_fired_at")[:_MAX_ALERTS]
    )
    alertas = [
        {
            "jugador": f"{a.player.first_name} {a.player.last_name}".strip(),
            "severidad": a.severity,
            "mensaje": a.message[:160],
        }
        for a in alerts
    ]

    return {
        "categoria": cc["category"],
        "fecha": cc["generated_at"],
        "kpis": cc["kpis"],
        "estado_plantel": cc["squad"]["counts"],
        "disponibilidad_por_linea": cc["squad"]["por_linea"],
        "proximo_partido": cc["context"]["next_match"],
        "riesgo_pre_partido": cc["context"]["pre_match_risk"],
        "jugadores_que_requieren_decision": cc["decisions"],
        "calidad_de_datos": cc["data_quality"],
        "alertas_activas": alertas,
        "plantel": roster,
    }


def build_team_overview(category) -> dict:
    """Light snapshot for the *tool-using* assistant: the Centro de mando
    aggregates + active alerts + a compact roster roll (name/position/status/
    age only). The heavy per-player metric detail is intentionally left OUT —
    the model pulls it on demand via `estado_jugador` / `historial_jugador` /
    `ranking_jugadores`, instead of us paying for the full dump every turn."""
    from api.command_center import build_command_center, _STATUS_LABEL
    from goals.models import Alert, AlertStatus

    cc = build_command_center(category)
    players = list(
        Player.objects.filter(category=category, is_active=True)
        .select_related("position")
        .order_by("last_name")
    )
    pids = [p.id for p in players]

    roster = [
        {
            "nombre": f"{p.first_name} {p.last_name}".strip(),
            "posicion": (p.position.role or p.position.abbreviation) if p.position else None,
            "estado": _STATUS_LABEL.get(p.status, p.status),
            "edad": p.age,
        }
        for p in players
    ]

    alerts = list(
        Alert.objects.filter(player_id__in=pids, status=AlertStatus.ACTIVE)
        .select_related("player")
        .order_by("-severity", "-last_fired_at")[:_MAX_ALERTS]
    )
    alertas = [
        {
            "jugador": f"{a.player.first_name} {a.player.last_name}".strip(),
            "severidad": a.severity,
            "mensaje": a.message[:160],
        }
        for a in alerts
    ]

    return {
        "categoria": cc["category"],
        "fecha": cc["generated_at"],
        "kpis": cc["kpis"],
        "estado_plantel": cc["squad"]["counts"],
        "disponibilidad_por_linea": cc["squad"]["por_linea"],
        "proximo_partido": cc["context"]["next_match"],
        "riesgo_pre_partido": cc["context"]["pre_match_risk"],
        "jugadores_que_requieren_decision": cc["decisions"],
        "calidad_de_datos": cc["data_quality"],
        "alertas_activas": alertas,
        "plantel": roster,
    }


# ─── Model call ──────────────────────────────────────────────────────


def _chat(api_key: str, model: str, system: str, messages: list[dict], category) -> str:
    """Agentic loop: let the model call the DB-search tools, run them, feed the
    results back, and repeat until it answers (bounded by `_MAX_TOOL_ROUNDS`)."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK not installed; team assistant unavailable.")
        return "El asistente no está disponible en este entorno."

    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
    convo = list(messages)

    def _create(with_tools: bool):
        kwargs = dict(
            model=model,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},  # room to reason over the tools
            system=system_blocks,
            messages=convo,
        )
        if with_tools:
            kwargs["tools"] = TOOLS
        return client.messages.create(**kwargs)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        for _ in range(_MAX_TOOL_ROUNDS):
            response = _create(with_tools=True)
            if response.stop_reason != "tool_use":
                return _extract_text(response) or _NO_ANSWER

            # Run every tool the model asked for, then feed the results back.
            convo.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                out, is_error = run_tool(category, block.name, block.input)
                result = {"type": "tool_result", "tool_use_id": block.id, "content": out}
                if is_error:
                    result["is_error"] = True
                tool_results.append(result)
            convo.append({"role": "user", "content": tool_results})

        # Hit the round cap — ask once more without tools so it must answer.
        final = _create(with_tools=False)
        return _extract_text(final) or _NO_ANSWER
    except Exception:  # noqa: BLE001 — chat must always reply, never 500
        logger.exception("Team assistant generation failed.")
        return "No pude consultar el asistente en este momento. Intentá nuevamente."


_NO_ANSWER = "No tengo una respuesta para eso con los datos actuales."


def _extract_text(response) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def _sanitize(messages: list[dict]) -> list[dict]:
    """Keep only well-formed user/assistant turns, capped in length + count,
    ending on a user turn (the API requires the last message be the user's)."""
    out: list[dict] = []
    for m in messages or []:
        role = (m.get("role") or "").strip()
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        out.append({"role": role, "content": content[:_MAX_CONTENT]})
    out = out[-_MAX_HISTORY:]
    while out and out[-1]["role"] != "user":
        out.pop()
    return out
