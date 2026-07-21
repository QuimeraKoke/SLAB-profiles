"""AI recap of a day's Daily (morning meeting), cached per (category, date).

Mirrors the briefing's signature-gated LLM cache (`dashboards/briefing.py`):
one cheap Haiku call per data-state, persisted in `DailySummary`, so the
/daily view never recomputes it on each request. Generated at 00:00 for the
day that just ended (Celery beat) or lazily on first view. Never raises.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_MAX_TOKENS = 900
_RENDER_VERSION = 1

_SYSTEM = (
    "Sos el asistente del cuerpo técnico de un club de fútbol profesional. "
    "Escribís el resumen del 'daily' (reunión de la mañana) de un día puntual, "
    "en español de Chile, claro y conciso. Basate ÚNICAMENTE en los datos "
    "entregados; no inventes nombres, cifras ni hechos. Redactá 4 a 7 viñetas "
    "cortas (cada una con '- ') que cubran, cuando haya datos: estado de "
    "lesionados y retornos estimados; decisiones clave de la pauta y planes de "
    "trabajo; alertas relevantes en jugadores disponibles; y adherencia al "
    "check-in de wellness. Sin títulos, sin markdown de código, sin preámbulo."
)


def _build_context(category, target_date) -> dict:
    """Compact JSON of the day's Daily, reusing the report builder."""
    from api.daily_report import build_daily_report

    d = build_daily_report(category, target_date, None)
    k = d["kpis"]

    plan_trabajo = []
    for rows in (d.get("plans") or {}).values():
        for n in rows:
            plan_trabajo.append({
                "jugador": n["player_name"],
                "area": (n.get("department") or {}).get("name"),
                "texto": n["text"],
            })

    return {
        "fecha": d["date"],
        "categoria": d["category"],
        "disponibles": k["disponibles"],
        "no_disponibles": k["no_disponibles"]["n"],
        "alertas_kpi": k["alertas"],
        "wellness": {
            "respondieron": k["wellness_hoy"]["n"],
            "esperados": k["wellness_hoy"]["expected"],
            "no_respondieron": [p["name"] for p in k["wellness_hoy"]["no_respondieron"]],
        },
        "lesionados": [
            {
                "jugador": l["name"],
                "etapa": (l["episode"] or {}).get("stage_label"),
                "dias_fuera": (l["episode"] or {}).get("days_out"),
                "retorno_estimado": (l["episode"] or {}).get("expected_return"),
            }
            for l in d["lesionados"]
        ],
        "alertas": [
            {"jugador": a["name"], "mensajes": [m["message"] for m in a["alerts"]]}
            for a in d["alertas"]
        ],
        "pauta": [
            {
                "jugador": n["player_name"],
                "area": (n.get("department") or {}).get("name"),
                "texto": n["text"],
            }
            for n in d["notes"]
        ],
        "plan_trabajo": plan_trabajo,
        "plan_kinesico": [
            {
                "jugador": e["player_name"],
                "objetivo": e.get("objetivo"),
                "gimnasio": e.get("gimnasio"),
                "cancha": e.get("cancha"),
            }
            for e in d["kine"]
        ],
    }


def _has_content(ctx: dict) -> bool:
    """True only if the DAY itself had a daily — i.e. a date-scoped signal
    (pauta note, kine entry, or a wellness check-in that day). Lesionados /
    alertas reflect CURRENT state in the report (not historical), so they don't
    count — otherwise every date would look non-empty and burn a model call."""
    return bool(
        ctx["pauta"] or ctx["plan_kinesico"] or ctx["wellness"]["respondieron"]
    )


def _signature(context: dict, model: str) -> str:
    blob = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{_RENDER_VERSION}|{model}|{blob}".encode()).hexdigest()


def _call_llm(context: dict, model: str) -> str | None:
    key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    "Datos del día (JSON):\n"
                    + json.dumps(context, ensure_ascii=False, default=str)
                    + "\n\nEscribí el resumen del daily."
                ),
            }],
        )
        parts = [
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
        ]
        return "".join(parts).strip() or None
    except Exception:  # noqa: BLE001 — never break the daily on a model hiccup
        logger.exception("Daily summary: model call failed (%s).", model)
        return None


def get_or_build(category, target_date, *, force: bool = False):
    """Return the cached `DailySummary` for (category, date), regenerating only
    when the day's data (or model) changed. Returns None if there is nothing to
    summarize or the model call fails and no prior summary exists."""
    from dashboards.models import DailySummary

    model = getattr(settings, "DAILY_SUMMARY_MODEL", "claude-haiku-4-5-20251001")
    context = _build_context(category, target_date)
    existing = DailySummary.objects.filter(category=category, date=target_date).first()

    if not _has_content(context):
        return existing  # empty day → don't spend a call

    sig = _signature(context, model)
    if existing and existing.data_hash == sig and not force:
        return existing

    text = _call_llm(context, model)
    if not text:
        return existing  # keep any prior summary on failure

    obj, _ = DailySummary.objects.update_or_create(
        category=category, date=target_date,
        defaults={"text": text, "model": model, "data_hash": sig},
    )
    return obj
