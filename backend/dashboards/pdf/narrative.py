"""LLM-generated narrative for the player Resumen PDF.

The triage payload (alerts + metrics + last match) is rich but tabular.
This module turns it into the ficha's "telling a story" prose — a short
``resumen``, the ``hallazgos`` that stand out, and concrete ``objetivos``
(focus · current state · strategy) — by handing the data to Claude.

Design constraints:

- **Grounded only.** The model is told to use *only* the supplied data —
  never invent metrics, dates, or diagnoses. The deterministic tables
  below the narrative remain the source of truth.
- **Never blocks a download.** No API key, an API error, a timeout, a
  malformed response — every failure path returns ``None`` and the PDF
  renders tables-only. The narrative is additive, never load-bearing.
- **Deduplicated upstream.** The whole PDF is content-addressed at the
  report level (`report_cache`), so this runs only when the data or the
  agent's config changed — never twice for the same report.
- **Stage-configurable.** The role prompt + knowledge base come from an
  editable `InsightAgent` (per stage); the JSON output contract stays
  code-owned so admin edits can't break parsing.

Single `messages.create` call (Claude API summarization tier): adaptive
thinking, no streaming (one-page output), no sampling params / no prefill
(removed on Opus 4.7). Output is requested as a plain JSON object and
parsed defensively rather than via structured-output APIs, so the module
works unchanged across model versions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from .report_cache import stable_json

logger = logging.getLogger(__name__)


# Output cap covers adaptive-thinking tokens + the small JSON body. Roomy
# so medium-effort thinking can't truncate the JSON (cap, not actual spend).
_MAX_TOKENS = 6000

# Built-in DEFAULT role prompt — used as the fallback when no InsightAgent
# row is configured for the stage. Once an InsightAgent exists, its
# (editable) `system_prompt` + `knowledge` replace this. NOTE: the JSON
# output contract is intentionally NOT here — it's `_OUTPUT_CONTRACT`,
# appended by code, so an admin editing a prompt can't break parsing.
_DEFAULT_ROLE_PROMPT = (
    "Eres un analista de ciencias del deporte y del área médica de un club "
    "de fútbol profesional. Redactas fichas individuales para el cuerpo "
    "técnico y médico, en español (Chile), con un tono clínico, claro y "
    "accionable.\n\n"
    "Se te entregan los datos de seguimiento de un jugador (alertas activas, "
    "métricas alertadas, otras métricas con su evolución reciente y el último "
    "partido). A partir de SOLO esos datos, redacta una ficha narrativa.\n\n"
    "Reglas estrictas:\n"
    "- Usa únicamente la información provista. NO inventes métricas, valores, "
    "fechas, diagnósticos ni lesiones que no aparezcan en los datos.\n"
    "- Si no hay datos suficientes para una sección, dilo explícitamente en "
    "lugar de rellenar.\n"
    "- Interpreta las variaciones según 'direction_of_good' cuando esté "
    "presente (qué dirección es buena para cada métrica).\n"
    "- Sé conciso: el cuerpo técnico lee esto de un vistazo."
)

# Code-owned guidance on the peer-comparison data, always appended so the
# narrative contextualizes the player against the squad and his position even
# when an admin edits the role prompt.
_COMPARISON_GUIDE = (
    "Comparación con pares: cada métrica puede traer `references.peer` con el "
    "promedio y percentil del jugador respecto del EQUIPO (`team`) y de su "
    "MISMA POSICIÓN (`position`, con `label` y tamaño de muestra `n`). Cuando "
    "aporte valor, contextualizá los datos del jugador frente a esos promedios "
    "(p. ej. «por encima del promedio del equipo», «bajo para su posición»), "
    "citando el número. No compares cuando el bloque falte o `n` sea muy chico."
)

# Code-owned output contract. Always appended last, never editable, so the
# parsed JSON shape stays stable no matter how the role/knowledge is edited.
_OUTPUT_CONTRACT = (
    "Responde EXCLUSIVAMENTE con un objeto JSON válido (sin texto antes ni "
    "después, sin ```), con esta forma exacta:\n"
    "{\n"
    '  "resumen": "2 a 4 frases que cuenten el estado actual del jugador",\n'
    '  "hallazgos": ["2 a 5 hallazgos destacados, una frase cada uno"],\n'
    '  "objetivos": [\n'
    '    {"foco": "variable o área", "estado_actual": "dato actual", '
    '"estrategia": "acción concreta"}\n'
    "  ]\n"
    "}\n"
    "Incluye entre 1 y 4 objetivos. No agregues otras claves."
)


def resolve_insight_agent(key: str):
    """Return the active `InsightAgent` for a stage key, or None to fall back
    to the built-in default prompt (so the system works before any agent is
    seeded). Never raises."""
    try:
        from dashboards.models import InsightAgent

        return InsightAgent.objects.filter(key=key, is_active=True).first()
    except Exception:  # noqa: BLE001 — DB hiccup must not break report generation
        logger.exception("Failed to resolve InsightAgent '%s'.", key)
        return None


def _build_system(role_prompt: str, knowledge: str) -> str:
    """Assemble the effective system prompt: role + (editable knowledge base)
    + the code-owned output contract."""
    parts = [role_prompt.strip()]
    if knowledge and knowledge.strip():
        parts.append("# Base de conocimiento del club\n" + knowledge.strip())
    parts.append(_COMPARISON_GUIDE)
    parts.append(_OUTPUT_CONTRACT)
    return "\n\n".join(parts)


def generate_player_narrative(payload: dict, *, agent=None) -> dict | None:
    """Return ``{"resumen", "hallazgos", "objetivos"}`` for the triage
    ``payload``, or ``None`` if the narrative can't be produced (no key,
    API/parse failure). Callers must treat ``None`` as "render without a
    narrative" — this function never raises.

    `agent` is an optional `InsightAgent` supplying the editable role prompt,
    knowledge base, and model override; when omitted, the built-in default
    role prompt is used. No caching here — dedup happens one layer up at the
    report level (`report_cache`), so this is only called when the data (or
    the agent's config) actually changed. The prompt uses `stable_json`
    (volatile fields like generated_at stripped) for reproducibility."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key.strip():
        return None

    if agent is not None:
        model = (agent.model or "").strip() or getattr(
            settings, "ANTHROPIC_MODEL", "claude-opus-4-8"
        )
        system = _build_system(agent.system_prompt, agent.knowledge)
    else:
        model = getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
        system = _build_system(_DEFAULT_ROLE_PROMPT, "")

    return _call_model(api_key, model, system, stable_json(payload))


# ─── Analytical narrative (Resumen / Análisis / Conclusiones) ──────────

_ANALYSIS_ROLE_PROMPT = (
    "Eres un analista de ciencias del deporte de un club de fútbol profesional. "
    "Redactas el informe analítico individual de un jugador para el cuerpo "
    "técnico, en español (Chile), tono clínico y accionable. El objetivo es "
    "entender si el rendimiento del jugador va bien o mal, ponerlo en contexto "
    "frente a sus pares de la MISMA POSICIÓN, y detectar tendencias antes de que "
    "se transformen en problemas.\n\n"
    "Recibes un JSON con dos bloques:\n"
    "- `triage`: alertas activas, métricas alertadas y su evolución, último "
    "partido.\n"
    "- `analysis`:\n"
    "  • `match_load`: por cada métrica de GPS de partido, su `trend` "
    "(direction up/down/flat + pct_change) y `correlations` = pares de variables "
    "que CO-MUEVEN (coeficiente de Pearson `r`; |r|≥0,6 es fuerte). `primary` es "
    "la carga (distancia total) con sus `comovers` (variables que siguen su "
    "tendencia).\n"
    "  • `training`: `acwr` (agudo 7d ÷ crónico 28d-semanal; rango óptimo "
    "0,8–1,3; ≥1,5 = pico de riesgo) con su `band`/`label`; `microcycle` = carga "
    "del microciclo actual vs. el promedio de los previos (`pct_change`).\n"
    "  • `position`: el jugador vs. el promedio de su posición (`position_avg`) "
    "y su `percentile` (con tamaño de muestra `n`).\n\n"
    "Reglas estrictas:\n"
    "- Usa SÓLO los datos provistos. NO inventes métricas, valores, r, "
    "percentiles ni diagnósticos.\n"
    "- Correlación NO implica causalidad: describe co-movimientos ('X tiende a "
    "subir junto con Y, r=0,82'), no causas.\n"
    "- Cita números reales (r, percentil, ACWR, % de cambio).\n"
    "- Interpreta el ACWR según su banda; marca riesgo si ≥1,5 o descarga si "
    "<0,8.\n"
    "- Si un bloque no tiene datos suficientes (`n` chico, pocas tomas), dilo en "
    "vez de rellenar.\n"
    "- Sé conciso; el cuerpo técnico lo lee de un vistazo."
)

_ANALYSIS_OUTPUT_CONTRACT = (
    "Responde EXCLUSIVAMENTE con un objeto JSON válido (sin texto antes ni "
    "después, sin ```), con esta forma exacta:\n"
    "{\n"
    '  "resumen": "2 a 4 frases: estado general del jugador y si la tendencia '
    'es positiva o preocupante",\n'
    '  "analisis": ["3 a 6 puntos que INTERPRETAN los datos: tendencia de carga '
    'de partido y qué variables la acompañan (citá r); ACWR y microciclo; '
    'contexto por posición (citá percentil/promedio). Una frase cada uno"],\n'
    '  "conclusiones": ["2 a 4 conclusiones o acciones concretas: qué vigilar y '
    'qué hacer. Una frase cada una"]\n'
    "}\n"
    "No agregues otras claves."
)


def generate_player_analysis_narrative(payload: dict, *, agent=None) -> dict | None:
    """Return ``{"resumen", "analisis": [...], "conclusiones": [...]}`` for the
    analytical Resumen report — interprets the deterministic `analysis` payload
    (trends, correlations, ACWR, microcycle, position). ``None`` on no key /
    API / parse failure; never raises. Caching happens one layer up."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key.strip():
        return None

    if agent is not None:
        model = (agent.model or "").strip() or getattr(
            settings, "ANTHROPIC_MODEL", "claude-opus-4-8"
        )
        knowledge = agent.knowledge
    else:
        model = getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
        knowledge = ""

    parts = [_ANALYSIS_ROLE_PROMPT.strip()]
    if knowledge and knowledge.strip():
        parts.append("# Base de conocimiento del club\n" + knowledge.strip())
    parts.append(_ANALYSIS_OUTPUT_CONTRACT)
    system = "\n\n".join(parts)

    return _call_model(api_key, model, system, stable_json(payload), parser=_parse_analysis)


def _parse_analysis(text: str) -> dict | None:
    """Parse the analytical narrative JSON into ``{resumen, analisis[],
    conclusiones[]}``. Returns None on anything unusable."""
    raw = _extract_json_object(text)
    if raw is None:
        logger.warning("Analysis narrative: no JSON object in model output.")
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Analysis narrative: JSON parse failed.")
        return None
    if not isinstance(data, dict):
        return None

    resumen = str(data.get("resumen") or "").strip()

    def _strlist(key: str) -> list[str]:
        out: list[str] = []
        for item in data.get(key) or []:
            s = str(item).strip()
            if s:
                out.append(s)
        return out

    analisis = _strlist("analisis")
    conclusiones = _strlist("conclusiones")
    if not (resumen or analisis or conclusiones):
        return None
    return {"resumen": resumen, "analisis": analisis, "conclusiones": conclusiones}


# ─── Model call ──────────────────────────────────────────────────────


def _call_model(api_key: str, model: str, system: str, prompt_json: str, parser=None) -> dict | None:
    parser = parser or _parse_narrative
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK not installed; skipping Resumen narrative.")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            # System (role + knowledge base) is stable across players, so cache
            # the prefix — cheap when generating many reports in a window.
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Datos de seguimiento del jugador (JSON):\n\n"
                        f"{prompt_json}\n\n"
                        "Genera la ficha narrativa como objeto JSON."
                    ),
                }
            ],
        )
    except Exception:  # noqa: BLE001 — never let the LLM break a PDF download
        logger.exception("Anthropic narrative generation failed.")
        return None

    text = _extract_text(response)
    if not text:
        return None
    return parser(text)


def _extract_text(response: Any) -> str:
    """Join the text blocks of a Messages response. Skips thinking blocks
    (empty text under the default 'omitted' display on Opus 4.7)."""
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


# ─── Parsing ─────────────────────────────────────────────────────────


def _parse_narrative(text: str) -> dict | None:
    """Parse the model's JSON, tolerating stray prose or ``` fences, and
    coerce it into the strict shape the PDF expects. Returns ``None`` on
    anything unusable."""
    raw = _extract_json_object(text)
    if raw is None:
        logger.warning("Resumen narrative: no JSON object in model output.")
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Resumen narrative: JSON parse failed.")
        return None
    if not isinstance(data, dict):
        return None

    resumen = str(data.get("resumen") or "").strip()

    hallazgos: list[str] = []
    for h in data.get("hallazgos") or []:
        s = str(h).strip()
        if s:
            hallazgos.append(s)

    objetivos: list[dict[str, str]] = []
    for o in data.get("objetivos") or []:
        if not isinstance(o, dict):
            continue
        foco = str(o.get("foco") or "").strip()
        estado = str(o.get("estado_actual") or "").strip()
        estrategia = str(o.get("estrategia") or "").strip()
        if foco or estado or estrategia:
            objetivos.append(
                {"foco": foco, "estado_actual": estado, "estrategia": estrategia}
            )

    if not (resumen or hallazgos or objetivos):
        return None
    return {"resumen": resumen, "hallazgos": hallazgos, "objetivos": objetivos}


def _extract_json_object(text: str) -> str | None:
    """Return the substring from the first ``{`` to its matching ``}``,
    respecting string literals so braces inside values don't confuse the
    scan. Handles models that wrap the object in prose or code fences."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
