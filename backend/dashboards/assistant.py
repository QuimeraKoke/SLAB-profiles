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


# ─── Embedded Dashboard assistant (view-scoped: answers + PROPOSES CHARTS) ──
# Kept separate from the floating chat above — only this surface visualizes
# and can promote charts to the current department panel.

_DASHBOARD_PROMPT = (
    "Sos el asistente del panel de {department} de {category}, una plataforma "
    "de ciencias del deporte de un club de fútbol profesional. Respondés "
    "preguntas del cuerpo técnico y, cuando una visualización ayude, PROPONÉS "
    "UN GRÁFICO con la herramienta `proponer_grafico` para que el usuario lo "
    "vea y pueda fijarlo al panel. Español (Chile), breve y accionable.\n\n"
    "Herramientas de datos (read-only, alcance: la categoría): listar_examenes "
    "(descubrir exámenes con su `slug` y `campo`, y su última fecha con datos), "
    "ranking_jugadores, historial_jugador, estado_jugador. Más `proponer_grafico` "
    "para graficar.\n\n"
    "Cómo trabajar:\n"
    "- Enfocate en el área {department}, pero podés cruzar otras áreas si la "
    "pregunta lo pide.\n"
    "- Si no conocés el `slug`/`campo` exactos, llamá primero a listar_examenes y "
    "recién después proponé el gráfico con valores REALES (no inventes slugs, "
    "campos ni datos).\n"
    "- SÓLO podés graficar CAMPOS QUE EXISTEN (incluidos los calculados). Si piden "
    "una métrica que NO es un campo —un ratio o división A÷B, una resta, un cálculo "
    "entre campos— NO la sustituyas por un solo campo ni la etiquetes como si "
    "existiera (p. ej. titular «Acc vs Dec» y mostrar solo Acc está MAL). Si es una "
    "comparación «A vs B», graficá AMBOS campos juntos (team_roster_matrix con los "
    "dos campos, o team_stacked_bars). Si es un ratio/cálculo sin campo propio, "
    "decilo y mostrá los COMPONENTES en un team_roster_matrix (jugador × métrica), "
    "aclarando que el ratio exacto necesitaría un campo calculado — no inventes una "
    "columna de ratio ni el gráfico.\n"
    "- Si piden los DATOS EN TABLA, un «resumen por jugador», o varias métricas "
    "exactas por jugador, proponé un team_roster_matrix (la tabla jugador × "
    "métrica). Es un gráfico válido y se puede FIJAR al panel; NO devuelvas la "
    "tabla como texto ni digas «avisame» — proponé el widget directamente.\n"
    "- Elegí el `chart_type` según el CATÁLOGO de gráficos (más abajo) y la "
    "forma de la pregunta. NO uses siempre el mismo tipo: un ranking va como "
    "leaderboard, una evolución como línea de tendencia, varias métricas como "
    "matriz, una composición como barras apiladas. Configurá la agregación y el "
    "display_config que indica el catálogo para cada tipo.\n"
    "- Acompañá el gráfico con 1–3 frases que lo interpreten, citando los números "
    "que devuelva la herramienta.\n"
    "- Si no hay datos suficientes, decilo en vez de proponer un gráfico vacío."
)

# Tool the Dashboard assistant uses to propose a chart. Resolved server-side
# via `dashboards.chart_spec.resolve_chart_spec` (same vocabulary + resolver as
# a saved TeamReportWidget, so a proposed chart and a promoted one match).
_CHART_TOOL = {
    "name": "proponer_grafico",
    "description": (
        "Propone un gráfico de equipo para visualizar la respuesta en el panel. "
        "Se renderiza y el usuario puede fijarlo. Elegí el `chart_type` y su forma "
        "de datos (cuántos campos, qué agregación, qué display_config) según el "
        "CATÁLOGO de gráficos del prompt del sistema — no uses siempre el mismo "
        "tipo. Usá slug/campo REALES (descubrilos con listar_examenes). Podés "
        "proponer más de uno si aporta."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": [
                    "team_distribution", "team_leaderboard",
                    "team_horizontal_comparison", "team_trend_line",
                    "team_roster_matrix", "team_stacked_bars",
                    "team_status_counts", "team_activity_coverage",
                ],
            },
            "title": {"type": "string", "description": "Título corto del gráfico (español)."},
            "sources": {
                "type": "array",
                "description": "Fuentes de datos (normalmente una).",
                "items": {
                    "type": "object",
                    "properties": {
                        "template_slug": {"type": "string", "description": "slug del examen (ver listar_examenes)."},
                        "field_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "claves de campo a graficar.",
                        },
                        "aggregation": {
                            "type": "string",
                            "enum": ["latest", "last_n", "all"],
                            "description": "latest = último valor (default); last_n = últimos N; all = todos.",
                        },
                        "aggregation_param": {"type": "integer", "description": "N para last_n (default 3)."},
                    },
                    "required": ["template_slug", "field_keys"],
                    "additionalProperties": False,
                },
            },
            "display_config": {
                "type": "object",
                "description": "Opcional: knobs del gráfico (p. ej. {\"bin_count\": 8} para distribución).",
                "additionalProperties": True,
            },
        },
        "required": ["chart_type", "sources"],
        "additionalProperties": False,
    },
}

# Per-chart-type guidance so the Dashboard assistant picks the RIGHT
# visualization (not just a histogram) and configures the data shape correctly.
# Mirrors DASHBOARDS.md §3/§4/§5.
_CHART_CATALOG = (
    "# Catálogo de gráficos de equipo (elegí el que mejor responde la pregunta; "
    "NO uses siempre el mismo). Formato — tipo: cuándo · campos · cómo se reduce "
    "por jugador · display_config (con sus DEFAULTS).\n\n"
    "- team_distribution: distribución/dispersión de UNA métrica en el plantel "
    "(histograma). 1 campo (usa el primero). Reduce: ÚLTIMO valor por jugador. "
    "display_config: {\"bin_count\": 8 (3–30), \"coloring\": \"auto\"|\"none\"}.\n"
    "- team_leaderboard: ranking por UNA métrica (top/bottom o todo el plantel en "
    "barras). 1 campo. Reduce: display_config.aggregator "
    "(\"latest\"|\"sum\"|\"avg\"|\"max\"; DEFAULT \"sum\"). IGNORA la agregación de "
    "la fuente. Para «último/actual/último partido» poné aggregator=\"latest\" "
    "(\"sum\" acumula TODO el período e infla). display_config: {\"aggregator\":"
    "\"latest\", \"style\":\"vertical_bars\"|\"list\", \"limit\":30 (list 3–20; alto "
    "= más jugadores), \"order\":\"desc\"|\"asc\", \"show_team_avg_line\":true, "
    "\"reference_lines\":[{\"value\":100,\"label\":\"Objetivo\"}], \"reference_bands\":"
    "[{\"min\":0,\"max\":50,\"label\":\"…\"}], \"decimals\":1} (metas = "
    "reference_lines, NO \"target\").\n"
    "- team_horizontal_comparison: comparar jugadores con sus N lecturas recientes "
    "por barra (mode \"by_reading\") o varios campos por fila (mode \"multi_field\"). "
    "1+ campos. Reduce: USA la agregación de la FUENTE → poné aggregation=last_n + "
    "aggregation_param=N. display_config: {\"mode\":\"by_reading\"|\"multi_field\", "
    "\"group_by\":\"none\"|\"position\"}.\n"
    "- team_trend_line: evolución/tendencia del PROMEDIO del equipo en el tiempo. "
    "1+ campos (selector). Reduce: usa TODA la historia → poné aggregation=all. "
    "display_config: {\"bucket_size\":\"week\"|\"month\", \"group_by\":\"none\"|"
    "\"position\"}.\n"
    "- team_roster_matrix: LA tabla de datos — jugadores × VARIAS métricas, valor "
    "ACTUAL por celda, con sombreado opcional. Es la forma de DEVOLVER DATOS EN "
    "TABLA: usalo para «los datos en tabla», «resumen por jugador», «varias "
    "métricas exactas por jugador». VARIOS campos. Reduce: último valor por celda. "
    "display_config: {\"coloring\":\"vs_team_range\"|\"none\", \"variation\":\"off\"|"
    "\"absolute\"|\"percent\"}.\n"
    "- team_stacked_bars: composición por jugador apilando VARIOS campos (p. ej. "
    "Acc + Dec). VARIOS campos. Reduce: display_config.aggregator (igual que "
    "leaderboard; DEFAULT \"sum\" → para «último» poné \"latest\"). IGNORA la "
    "agregación de la fuente. display_config: {\"aggregator\":\"latest\", "
    "\"order\":\"desc\", \"limit\":30, \"field_colors\":{\"campo\":\"#hex\"}}.\n"
    "- team_status_counts: disponibilidad del plantel (lesionados/disponibles/etc). "
    "Fuente = plantilla EPISÓDICA (lesiones); field_keys=[] (sin métrica numérica). "
    "Para «¿quiénes están lesionados/disponibles?».\n"
    "- team_activity_coverage: cobertura — días desde el ÚLTIMO registro por jugador "
    "(«¿a quién le falta evaluación?»). 1 fuente (la plantilla a vigilar). "
    "display_config: {\"green_max\":30, \"yellow_max\":60} (umbrales en DÍAS).\n\n"
    "REGLA CLAVE — la reducción por jugador define los NÚMEROS, y varía por tipo:\n"
    "- Valor ACTUAL / «último» / «último partido» → reducción 'latest'. En "
    "leaderboard y stacked_bars eso es display_config.aggregator=\"latest\" (su "
    "DEFAULT \"sum\" SUMA todo el período e infla). En distribution y roster_matrix "
    "ya es el último por jugador.\n"
    "- aggregation=all (en la fuente) SÓLO para tendencias en el tiempo "
    "(team_trend_line) o un acumulado pedido explícitamente.\n"
    "- aggregation=last_n + aggregation_param (en la fuente) para "
    "team_horizontal_comparison.\n"
    "- Un campo *_total (p. ej. hiaa_total) YA es el total de ESA sesión/partido; "
    "no lo vuelvas a sumar para mostrar «el último».\n"
    "Coherencia: el gráfico y tu texto deben mostrar los MISMOS números."
)


# ─── Player-profile assistant (per-player: answers + PROPOSES per-player CHARTS) ──
# Same loop as the dashboard assistant, scoped to ONE player and using the
# per-player chart vocabulary + resolver (resolve_player_chart_spec).

_PLAYER_DASHBOARD_PROMPT = (
    "Sos el asistente del perfil de {player} ({category}) en el área "
    "{department}, en una plataforma de ciencias del deporte de un club de "
    "fútbol profesional. Respondés preguntas sobre ESTE jugador y, cuando una "
    "visualización ayude, PROPONÉS UN GRÁFICO con `proponer_grafico_jugador` "
    "para que el cuerpo técnico lo vea y pueda fijarlo al panel del perfil. "
    "Español (Chile), breve y accionable.\n\n"
    "Los gráficos son POR JUGADOR: muestran la evolución y los registros de "
    "{player} (no del plantel). Herramientas de datos (read-only): "
    "listar_examenes (slug/campo y última fecha), historial_jugador, "
    "estado_jugador, ranking_jugadores. Más proponer_grafico_jugador para "
    "graficar.\n\n"
    "Cómo trabajar:\n"
    "- Si no conocés el slug/campo exactos, llamá primero a listar_examenes y "
    "recién después proponé con valores REALES (no inventes slugs/campos/datos).\n"
    "- SÓLO graficá campos que EXISTEN. Para un ratio/cálculo sin campo propio, "
    "decilo y mostrá los componentes; no inventes una métrica ni una columna.\n"
    "- Elegí el chart_type según el CATÁLOGO (abajo) y la pregunta; NO uses "
    "siempre el mismo tipo.\n"
    "- Acompañá el gráfico con 1–3 frases que lo interpreten, citando valores y "
    "fechas reales.\n"
    "- Si {player} no tiene datos suficientes, decilo en vez de un gráfico vacío."
)

_PLAYER_CHART_CATALOG = (
    "# Catálogo de gráficos del PERFIL (por jugador; elegí el que mejor "
    "responde). Formato — tipo: cuándo · campos · agregación · display_config.\n\n"
    "- multi_line: evolución en el tiempo de 1+ métricas (todas las series "
    "visibles a la vez). 1 fuente · VARIOS campos · aggregation=all (o last_n). "
    "display_config: {\"colors\":[\"#hex\"], \"x_axis_title\":\"Fecha\", "
    "\"y_axis_title\":\"…\"}.\n"
    "- line_with_selector: evolución de UNA variable por vez, con dropdown para "
    "cambiar de campo. 1+ fuentes · VARIOS campos · aggregation=all.\n"
    "- comparison_table: últimas N tomas lado a lado con deltas (una fila por "
    "campo). 1 fuente · VARIOS campos · aggregation=last_n + aggregation_param=N.\n"
    "- grouped_bar: comparar 2–5 campos a través de las últimas tomas. 1 fuente · "
    "2–5 campos · aggregation=last_n. display_config: {\"colors\":[\"#hex\"]}.\n"
    "- donut_per_result: fracciones de un total, una dona por toma (p. ej. "
    "composición corporal). 1 fuente · campos que SUMAN un todo · "
    "aggregation=last_n.\n\n"
    "Agregación: all = toda la historia (tendencias); last_n = últimas N tomas "
    "(con aggregation_param); latest = sólo la última. El widget guardado se "
    "renderiza por jugador en el panel del perfil del departamento."
)

_PLAYER_CHART_TOOL = {
    "name": "proponer_grafico_jugador",
    "description": (
        "Propone un gráfico del PERFIL del jugador (su evolución/registros) para "
        "visualizar la respuesta. Se renderiza para el jugador actual y se puede "
        "fijar al panel del perfil del departamento (se mostrará por jugador). "
        "Elegí chart_type y su forma de datos según el CATÁLOGO del sistema. Usá "
        "slug/campo REALES (listar_examenes). Tipos: multi_line, "
        "line_with_selector, comparison_table, grouped_bar, donut_per_result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": [
                    "multi_line", "line_with_selector", "comparison_table",
                    "grouped_bar", "donut_per_result",
                ],
            },
            "title": {"type": "string", "description": "Título corto (español)."},
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "template_slug": {"type": "string"},
                        "field_keys": {"type": "array", "items": {"type": "string"}},
                        "aggregation": {"type": "string", "enum": ["latest", "last_n", "all"]},
                        "aggregation_param": {"type": "integer"},
                    },
                    "required": ["template_slug", "field_keys"],
                    "additionalProperties": False,
                },
            },
            "display_config": {"type": "object", "additionalProperties": True},
        },
        "required": ["chart_type", "sources"],
        "additionalProperties": False,
    },
}


_PLAYER_RESUMEN_PROMPT = (
    "Sos el asistente del perfil de {player} ({category}) en una plataforma de "
    "ciencias del deporte de un club de fútbol profesional. Estás en la vista "
    "RESUMEN del jugador: cruzás TODAS las áreas (médico, físico, nutricional, "
    "táctico, etc.), no una sola. Respondés preguntas sobre ESTE jugador y, "
    "cuando una visualización ayude, PROPONÉS UN GRÁFICO con "
    "`proponer_grafico_jugador` para que el cuerpo técnico lo revise en el "
    "momento. Español (Chile), breve y accionable.\n\n"
    "Los gráficos son POR JUGADOR: muestran la evolución y los registros de "
    "{player} (no del plantel). Herramientas de datos (read-only): "
    "listar_examenes (slug/campo y última fecha, de CUALQUIER área), "
    "historial_jugador, estado_jugador, ranking_jugadores. Más "
    "proponer_grafico_jugador para graficar.\n\n"
    "Cómo trabajar:\n"
    "- Si no conocés el slug/campo exactos, llamá primero a listar_examenes y "
    "recién después proponé con valores REALES (no inventes slugs/campos/datos).\n"
    "- SÓLO graficá campos que EXISTEN. Para un ratio/cálculo sin campo propio, "
    "decilo y mostrá los componentes; no inventes una métrica ni una columna.\n"
    "- Elegí el chart_type según el CATÁLOGO (abajo) y la pregunta; NO uses "
    "siempre el mismo tipo.\n"
    "- Acompañá el gráfico con 1–3 frases que lo interpreten, citando valores y "
    "fechas reales.\n"
    "- Estos gráficos son para REVISAR en el momento; esta vista no es "
    "configurable, así que NO se fijan a ningún panel.\n"
    "- Si {player} no tiene datos suficientes, decilo en vez de un gráfico vacío."
)


def answer_player_resumen_question(
    player,
    messages: list[dict],
    *,
    date_from=None,
    date_to=None,
) -> dict:
    """Cross-department per-player assistant for the RESUMEN tab: answers about
    ONE player across ALL areas and proposes per-player charts to REVIEW inline.
    Transient by design — the Resumen view is NOT a configurable layout, so the
    charts are not promotable (the caller omits the promote action). Returns
    ``{"reply": str, "charts": [...]}``. Never raises."""
    from dashboards.pdf.narrative import resolve_insight_agent
    from dashboards.chart_spec import resolve_player_chart_spec

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()
    if not api_key:
        return {
            "reply": (
                "El asistente de IA no está configurado en este entorno "
                "(falta ANTHROPIC_API_KEY)."
            ),
            "charts": [],
        }

    convo = _sanitize(messages)
    if not convo:
        return {"reply": "¿Qué querés analizar de este jugador?", "charts": []}

    category = player.category
    # Cross-department → use the orchestrator persona (multidisciplinary), like
    # the floating team chat, NOT a single department's agent.
    agent = resolve_insight_agent("assistant")
    model = (
        ((agent.model or "").strip() if agent else "")
        or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
    )
    player_name = f"{player.first_name} {player.last_name}".strip()
    system = _PLAYER_RESUMEN_PROMPT.format(
        player=player_name,
        category=getattr(category, "name", ""),
    )
    system += "\n\n" + _PLAYER_CHART_CATALOG
    # All specialists' knowledge so the resumen assistant reasons across areas.
    specialists = _specialist_knowledge()
    if specialists:
        system += "\n\n" + specialists

    # `resolve_player_chart_spec` needs a department ONLY as the throwaway-layout
    # container for the rollback preview — the chart itself resolves by
    # template-slug + category + player (department-agnostic). Any of the
    # category's departments works; None degrades to "no chart" gracefully.
    container_dept = category.departments.first() if category else None

    def _resolve(spec):
        return resolve_player_chart_spec(
            player=player, department=container_dept, spec=spec,
            date_from=date_from, date_to=date_to,
        )

    return _chat_with_charts(
        api_key, model, system, convo, category, _PLAYER_CHART_TOOL, _resolve,
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
        or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
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


def answer_dashboard_question(
    category,
    department,
    messages: list[dict],
    *,
    position_id=None,
    player_ids=None,
    date_from=None,
    date_to=None,
) -> dict:
    """Embedded, department-scoped assistant for the Dashboard view: answers
    questions AND can propose charts (`proponer_grafico` → `resolve_chart_spec`).
    Returns ``{"reply": str, "charts": [payload, ...]}`` — the charts carry the
    resolved data (rendered transiently) plus the echoed `spec` (for promote).
    Separate from `answer_team_question` (floating chat). Never raises."""
    from dashboards.pdf.narrative import resolve_insight_agent

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()
    if not api_key:
        return {
            "reply": (
                "El asistente de IA no está configurado en este entorno "
                "(falta ANTHROPIC_API_KEY)."
            ),
            "charts": [],
        }

    convo = _sanitize(messages)
    if not convo:
        return {"reply": "¿Qué querés analizar de este panel?", "charts": []}

    # Department persona (InsightAgent key = department slug) supplies the model
    # override + KB; the role/contract is code-owned (_DASHBOARD_PROMPT).
    agent = resolve_insight_agent(getattr(department, "slug", ""))
    model = (
        ((agent.model or "").strip() if agent else "")
        or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
    )
    system = _DASHBOARD_PROMPT.format(
        department=getattr(department, "name", ""),
        category=getattr(category, "name", ""),
    )
    system += "\n\n" + _CHART_CATALOG
    if agent and (agent.knowledge or "").strip():
        system += "\n\n# Base de conocimiento del área\n" + agent.knowledge.strip()
    system += (
        "\n\n# Snapshot del equipo (JSON; el detalle por jugador se obtiene "
        "con las herramientas)\n"
        + json.dumps(build_team_overview(category), ensure_ascii=False, default=str)
    )

    from dashboards.chart_spec import resolve_chart_spec

    def _resolve(spec):
        return resolve_chart_spec(
            category=category, department=department, spec=spec,
            position_id=position_id, player_ids=player_ids,
            date_from=date_from, date_to=date_to,
        )

    return _chat_with_charts(api_key, model, system, convo, category, _CHART_TOOL, _resolve)


def answer_player_question(
    player,
    department,
    messages: list[dict],
    *,
    date_from=None,
    date_to=None,
) -> dict:
    """Per-player profile assistant: answers about ONE player and can propose
    per-player charts (`proponer_grafico_jugador` → `resolve_player_chart_spec`).
    Returns ``{"reply": str, "charts": [...]}``. Never raises."""
    from dashboards.pdf.narrative import resolve_insight_agent
    from dashboards.chart_spec import resolve_player_chart_spec

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()
    if not api_key:
        return {
            "reply": (
                "El asistente de IA no está configurado en este entorno "
                "(falta ANTHROPIC_API_KEY)."
            ),
            "charts": [],
        }

    convo = _sanitize(messages)
    if not convo:
        return {"reply": "¿Qué querés analizar de este jugador?", "charts": []}

    category = player.category
    agent = resolve_insight_agent(getattr(department, "slug", ""))
    model = (
        ((agent.model or "").strip() if agent else "")
        or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
    )
    player_name = f"{player.first_name} {player.last_name}".strip()
    system = _PLAYER_DASHBOARD_PROMPT.format(
        player=player_name,
        department=getattr(department, "name", ""),
        category=getattr(category, "name", ""),
    )
    system += "\n\n" + _PLAYER_CHART_CATALOG
    if agent and (agent.knowledge or "").strip():
        system += "\n\n# Base de conocimiento del área\n" + agent.knowledge.strip()

    def _resolve(spec):
        return resolve_player_chart_spec(
            player=player, department=department, spec=spec,
            date_from=date_from, date_to=date_to,
        )

    return _chat_with_charts(api_key, model, system, convo, category, _PLAYER_CHART_TOOL, _resolve)


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
        resp = client.messages.create(**kwargs)
        from dashboards.llm_usage import log_usage
        log_usage("assistant", model, resp)
        return resp

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


# ─── Dashboard assistant loop (data tools + proponer_grafico) ─────────


def _chat_with_charts(api_key, model, system, messages, category, chart_tool, resolve_spec) -> dict:
    """Agentic loop shared by the team-dashboard and player-profile assistants:
    the data tools (run_tool) plus a chart tool whose spec is resolved by
    `resolve_spec(spec) -> payload`. Collects every resolved chart and returns
    ``{"reply": text, "charts": [...]}``. Never raises."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK not installed; chart assistant unavailable.")
        return {"reply": "El asistente no está disponible en este entorno.", "charts": []}

    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
    convo = list(messages)
    tools = TOOLS + [chart_tool]
    chart_tool_name = chart_tool["name"]
    charts: list[dict] = []

    def _create(with_tools: bool):
        kwargs = dict(
            model=model,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=system_blocks,
            messages=convo,
        )
        if with_tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
        from dashboards.llm_usage import log_usage
        log_usage("assistant_charts", model, resp)
        return resp

    try:
        client = anthropic.Anthropic(api_key=api_key)
        for _ in range(_MAX_TOOL_ROUNDS):
            response = _create(with_tools=True)
            if response.stop_reason != "tool_use":
                return {"reply": _extract_text(response) or _NO_ANSWER, "charts": charts}

            convo.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == chart_tool_name:
                    out, is_error = _run_chart(resolve_spec, block.input, charts)
                else:
                    out, is_error = run_tool(category, block.name, block.input)
                result = {"type": "tool_result", "tool_use_id": block.id, "content": out}
                if is_error:
                    result["is_error"] = True
                tool_results.append(result)
            convo.append({"role": "user", "content": tool_results})

        final = _create(with_tools=False)
        return {"reply": _extract_text(final) or _NO_ANSWER, "charts": charts}
    except Exception:  # noqa: BLE001 — chat must always reply, never 500
        logger.exception("Chart assistant generation failed.")
        return {
            "reply": "No pude consultar el asistente en este momento. Intentá nuevamente.",
            "charts": charts,
        }


def _run_chart(resolve_spec, spec, charts) -> tuple[str, bool]:
    """Resolve a chart spec via `resolve_spec(spec)`, collect the chart for the
    client, and return a compact tool-result for the model. Empty/error specs are
    reported back so the model can correct (and aren't shown to the user)."""
    try:
        payload = resolve_spec(spec or {})
    except Exception:  # noqa: BLE001
        logger.exception("chart spec resolution failed")
        return json.dumps({"error": "No se pudo resolver el gráfico."}, ensure_ascii=False), True

    if payload.get("error"):
        return json.dumps({"error": payload["error"]}, ensure_ascii=False), True
    if payload.get("empty"):
        return (
            json.dumps(
                {"ok": False, "empty": True, "note": "Sin datos en el alcance/período."},
                ensure_ascii=False,
            ),
            False,
        )

    charts.append(payload)
    summary = {
        "ok": True,
        "chart_type": payload.get("chart_type"),
        "title": payload.get("title"),
        "stats": payload.get("stats"),
    }
    return json.dumps(summary, ensure_ascii=False, default=str), False
