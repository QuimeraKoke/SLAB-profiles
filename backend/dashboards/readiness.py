"""Player readiness — a cached, agent-refined "ready to train/play today?"
score (0–100, higher = more ready).

A deterministic base blends the real signals (wellness + its trend vs the
player's own baseline, ACWR load risk, self-reported daily estado, reported
molestias, and medical status). An agent (LLM) then reviews the player's
cross-area snapshot + the specialists' knowledge and adjusts that base
(within ±15, to stay grounded) with a one-line rationale + flags.

Cached in `PlayerReadiness` keyed by a `signature` of the inputs, so it's
recomputed only when the player's values change — not on every roster load.
Never raises.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_RENDER_VERSION = 1
_ANCHOR = 15  # max the agent may move the deterministic base
_STATUS_FACTOR = {
    "injured": 0.45, "recovery": 0.80, "reintegration": 0.90, "available": 1.0,
}
_WELLNESS_ITEMS = ("recuperacion", "cuerpo", "energia", "animo", "sueno")

_ROLE = (
    "Eres el equipo de ciencias del deporte de un club de fútbol profesional. "
    "Evalúa la disponibilidad/readiness del jugador para entrenar o competir HOY "
    "en una escala 0–100 (mayor = más listo), a partir ÚNICAMENTE de sus datos: "
    "wellness y su tendencia vs su propia línea base, carga (ACWR), estado "
    "auto-reportado del día, molestias/dolor reportados, lesiones abiertas y "
    "alertas activas. Se te entrega una base calculada; ajústala con criterio "
    "clínico dentro de ±15 puntos y no inventes datos."
)
_CONTRACT = (
    "Responde SOLO con un objeto JSON: "
    '{"score": <int 0-100>, "rationale": "<una frase>", '
    '"flags": ["<señales clave, 0-3>"]}.'
)


def build_inputs(player) -> dict:
    """Gather the player's cross-area readiness signals."""
    from api import wellness as w
    from api.roster import _player_acwr
    from exams.models import Episode
    from goals.models import Alert, AlertStatus

    cat = player.category
    fmax = w.field_max(cat) if cat else {}
    recent = (w.recent_by_player(cat, [player.id], limit=8).get(player.id, []) if cat else [])
    scores = [s for s in (w.score(d, fmax) for d in recent) if s is not None]
    wellness = scores[0] if scores else None
    baseline = round(sum(scores[1:]) / len(scores[1:])) if len(scores) >= 3 else None
    trend = (wellness - baseline) if (wellness is not None and baseline is not None) else None

    latest = recent[0] if recent else {}
    zones = [z.strip() for z in str(latest.get("molestia") or "").replace(";", ",").split(",") if z.strip()]
    acwr = _player_acwr(cat, [player.id]).get(player.id) if cat else None
    open_inj = list(
        Episode.objects.filter(player=player, template__slug="lesiones",
                               status=Episode.STATUS_OPEN).values_list("title", flat=True)
    )
    alerts = list(
        Alert.objects.filter(player=player, status=AlertStatus.ACTIVE)
        .order_by("-severity").values_list("severity", "message")[:8]
    )
    return {
        "jugador": f"{player.first_name} {player.last_name}".strip(),
        "status": player.status,
        "wellness": wellness,
        "wellness_baseline": baseline,
        "wellness_trend": trend,
        "wellness_items": {k: latest.get(k) for k in _WELLNESS_ITEMS},
        "estado_checkin": latest.get("estado"),
        "molestias": zones,
        "acwr": acwr,
        "lesiones_abiertas": list(open_inj),
        "alertas": [{"sev": s, "msg": str(m)[:80]} for s, m in alerts],
    }


def deterministic(inp: dict) -> int | None:
    """0–100 base score from the signals (None when there's no wellness)."""
    wellness = inp.get("wellness")
    if wellness is None:
        return None
    base = float(wellness)

    acwr = inp.get("acwr")
    if acwr is not None:
        if acwr > 1.5 or acwr < 0.7:
            base *= 0.85
        elif acwr > 1.3 or acwr < 0.8:
            base *= 0.93

    base -= min(len(inp.get("molestias") or []) * 6, 25)  # discomfort

    est = inp.get("estado_checkin")  # today's self-report
    if est == "lesion":
        base *= 0.40
    elif est == "parcial":
        base *= 0.75

    tr = inp.get("wellness_trend")
    if tr is not None and tr < 0:
        base += max(tr, -_ANCHOR)  # declining vs own baseline

    base *= _STATUS_FACTOR.get(inp.get("status"), 1.0)  # medical status
    return max(0, min(100, round(base)))


def compute_readiness(player, *, force: bool = False):
    """Recompute + cache the player's readiness, unless the inputs are
    unchanged (same signature) and not forced. Returns the PlayerReadiness."""
    from dashboards.models import PlayerReadiness

    inp = build_inputs(player)
    det = deterministic(inp)
    model = getattr(settings, "READINESS_MODEL", "claude-haiku-4-5-20251001")
    sig = _signature(inp, det, model)

    existing = PlayerReadiness.objects.filter(player=player).first()
    if existing is not None and existing.signature == sig and not force:
        return existing  # inputs unchanged → keep cached value

    score, source, rationale, flags = det, "deterministic", "", []
    agent = _agent_readiness(inp, det, model) if det is not None else None
    if agent is not None:
        score, source = agent["score"], "agent"
        rationale, flags = agent["rationale"], agent["flags"]

    obj, _ = PlayerReadiness.objects.update_or_create(
        player=player,
        defaults={
            "score": score, "deterministic": det, "source": source,
            "rationale": rationale, "flags": flags, "factors": inp,
            "signature": sig, "model": model,
        },
    )
    return obj


# ─── Agent call ───────────────────────────────────────────────────────


def _agent_readiness(inp: dict, det: int, model: str) -> dict | None:
    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()
    if not api_key:
        return None
    try:
        import anthropic
        from dashboards.assistant import _specialist_knowledge
    except Exception:  # noqa: BLE001
        return None

    system = _ROLE
    kb = _specialist_knowledge()
    if kb:
        system += "\n\n" + kb
    system += "\n\n" + _CONTRACT

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            # Bounded JSON contract → no thinking/effort (also required: the
            # default READINESS_MODEL is Haiku 4.5, which rejects both params).
            model=model,
            max_tokens=900,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{
                "role": "user",
                "content": (
                    f"Datos del jugador (JSON):\n{json.dumps(inp, ensure_ascii=False, default=str)}\n\n"
                    f"Base calculada de readiness: {det}. Devuelve el JSON."
                ),
            }],
        )
        from dashboards.llm_usage import log_usage
        log_usage("readiness", model, resp)
    except Exception:  # noqa: BLE001 — readiness must fall back to deterministic
        logger.exception("Agent readiness failed for %s.", inp.get("jugador"))
        return None

    text = "".join(
        getattr(b, "text", "") for b in (getattr(resp, "content", []) or [])
        if getattr(b, "type", None) == "text"
    ).strip()
    data = _parse(text)
    if data is None:
        return None
    # Anchor the agent's number to the deterministic base (±_ANCHOR), 0–100.
    score = max(det - _ANCHOR, min(det + _ANCHOR, data["score"]))
    return {"score": max(0, min(100, score)), "rationale": data["rationale"], "flags": data["flags"]}


def _parse(text: str) -> dict | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                text = text[start:i + 1]
                break
    try:
        d = json.loads(text)
        return {
            "score": int(round(float(d["score"]))),
            "rationale": str(d.get("rationale") or "").strip(),
            "flags": [str(f).strip() for f in (d.get("flags") or []) if str(f).strip()][:3],
        }
    except (ValueError, KeyError, TypeError):
        return None


def _signature(inp: dict, det, model: str) -> str:
    key = {k: inp.get(k) for k in (
        "status", "wellness", "wellness_trend", "estado_checkin",
        "molestias", "acwr", "lesiones_abiertas",
    )}
    key["alertas_n"] = len(inp.get("alertas") or [])
    basis = f"{_RENDER_VERSION}\n{model}\n{det}\n" + json.dumps(key, sort_keys=True, default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
