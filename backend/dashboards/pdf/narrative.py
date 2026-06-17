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
- **Cached by content.** Keyed on a hash of the payload + model, so
  re-downloading an unchanged Resumen is instant and costs nothing.

Single `messages.create` call (Claude API summarization tier): adaptive
thinking, no streaming (one-page output), no sampling params / no prefill
(removed on Opus 4.7). Output is requested as a plain JSON object and
parsed defensively rather than via structured-output APIs, so the module
works unchanged across model versions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# Output cap covers adaptive-thinking tokens + the small JSON body. Roomy
# so medium-effort thinking can't truncate the JSON (cap, not actual spend).
_MAX_TOKENS = 6000

_SYSTEM_PROMPT = (
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
    "- Sé conciso: el cuerpo técnico lee esto de un vistazo.\n\n"
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


def generate_player_narrative(payload: dict) -> dict | None:
    """Return ``{"resumen", "hallazgos", "objetivos"}`` for the triage
    ``payload``, or ``None`` if the narrative can't be produced (no key,
    API/parse failure). Callers must treat ``None`` as "render without a
    narrative" — this function never raises."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key.strip():
        return None

    model = getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-7")
    prompt_json = _serialize_payload(payload)

    cache_key = _cache_key(prompt_json, model)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None  # cached "" sentinel == known failure, don't retry hot

    narrative = _call_model(api_key, model, prompt_json)

    # Cache successes for the configured TTL; cache failures briefly with a
    # falsy sentinel so a broken key / outage doesn't hammer the API on every
    # download, while still recovering within a few minutes.
    if narrative is not None:
        ttl = getattr(settings, "ANTHROPIC_NARRATIVE_TTL", 7 * 24 * 3600)
        cache.set(cache_key, narrative, ttl)
    else:
        cache.set(cache_key, "", 300)
    return narrative


# ─── Model call ──────────────────────────────────────────────────────


def _call_model(api_key: str, model: str, prompt_json: str) -> dict | None:
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
            system=_SYSTEM_PROMPT,
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
    return _parse_narrative(text)


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


# ─── Serialization ───────────────────────────────────────────────────


def _serialize_payload(payload: dict) -> str:
    """Stable JSON for both the prompt and the cache key. Sorted keys so an
    unchanged payload always hashes identically."""
    return json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,  # keep Spanish accents (fewer tokens, readable)
        sort_keys=True,
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _cache_key(prompt_json: str, model: str) -> str:
    digest = hashlib.sha256(f"{model}\n{prompt_json}".encode("utf-8")).hexdigest()
    return f"triage_narrative:{digest}"
