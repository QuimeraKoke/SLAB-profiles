"""Centro de mando AI Briefing — ranked recommendation cards.

One LLM call per department: each department's `InsightAgent` (its persona
+ research-grounded playbook KB) reads the squad's live snapshot and emits
0–4 actionable cards for its area. The cards are merged, ranked by priority
then confidence, numbered, and cached (`BriefingSnapshot`) keyed on the data
+ agents' config so the multi-call generation runs once per state.

The card output contract is code-owned (`_BRIEFING_CONTRACT`) so editing an
agent's playbook can never break parsing. Never raises — returns whatever
cards parsed (or the cached set), so the dashboard always renders.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_MAX_TOKENS = 3500
_RENDER_VERSION = 1
_PRIORITY_ORDER = {"alta": 0, "media": 1, "baja": 2}

# Department slug → display label shown on the card / used by the tabs.
_DEPT_LABEL = {
    "medico": "Médico",
    "fisico": "Físico",
    "nutricional": "Nutrición",
    "psicosocial": "Wellness",
    "tactico": "Táctico",
}

_BRIEFING_CONTRACT = (
    "Devuelve EXCLUSIVAMENTE un objeto JSON válido (sin texto ni ``` antes o "
    "después) con esta forma exacta:\n"
    "{\n"
    '  "items": [\n'
    "    {\n"
    '      "priority": "alta" | "media" | "baja",\n'
    '      "tags": ["1 a 3 etiquetas temáticas cortas, p. ej. Carga, Riesgo, Wellness"],\n'
    '      "title": "título accionable, < 70 caracteres",\n'
    '      "recommendation": "1 frase con la acción recomendada",\n'
    '      "evidence": ["2 a 4 evidencias concretas tomadas del snapshot (con números/nombres)"],\n'
    '      "confidence": 0-100,\n'
    '      "owner_role": "rol responsable (de tu playbook)",\n'
    '      "timing": "cuándo, p. ej. Hoy, Antes de MD-4",\n'
    '      "cta_label": "etiqueta corta de acción (de tu playbook)",\n'
    '      "players": ["jugadores afectados, si aplica"]\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Incluye entre 0 y 4 items, SOLO los realmente accionables hoy según tus "
    "señales prioritarias y el snapshot. Si no hay señales relevantes en tu "
    "área, devuelve {\"items\": []}. No inventes datos que no estén en el "
    "snapshot."
)


def generate_briefing(category) -> list[dict]:
    """Ranked briefing cards for the category — cached by data+agents
    signature. Never raises."""
    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()

    from dashboards.assistant import build_team_context
    from dashboards.models import BriefingSnapshot, InsightAgent

    try:
        context = build_team_context(category)
    except Exception:  # noqa: BLE001
        logger.exception("Briefing: failed to build team context.")
        return []

    agents = list(
        InsightAgent.objects.filter(is_active=True, key__in=_DEPT_LABEL.keys())
    )
    model = getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
    signature = _signature(context, agents, model)

    cached = (
        BriefingSnapshot.objects
        .filter(category=category, data_hash=signature)
        .first()
    )
    if cached is not None:
        items = cached.items or []
        _attach_player_ids(items, category)  # live — old snapshots lack ids
        return items

    if not api_key or not agents:
        return []

    context_json = json.dumps(
        {k: v for k, v in context.items() if k != "fecha"},
        ensure_ascii=False, default=str,
    )

    # One call per department. The shared squad snapshot is a cached prefix,
    # but concurrent requests can't read each other's cache — firing all five
    # at once makes each PAY a cache-write for the identical snapshot (a net
    # loss). So warm the cache with the first department serially, THEN fan out
    # the rest in parallel — they read the snapshot the first call wrote.
    items: list[dict] = []
    first, rest = agents[0], agents[1:]
    try:
        items.extend(_call_department(api_key, model, context_json, first))
    except Exception:  # noqa: BLE001 — one area failing must not sink the rest
        logger.exception("Briefing: department '%s' failed.", first.key)
    if rest:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(rest))) as pool:
            futures = {
                pool.submit(_call_department, api_key, model, context_json, a): a
                for a in rest
            }
            for fut in concurrent.futures.as_completed(futures):
                a = futures[fut]
                try:
                    items.extend(fut.result())
                except Exception:  # noqa: BLE001
                    logger.exception("Briefing: department '%s' failed.", a.key)

    items = _rank(items)
    _attach_player_ids(items, category)
    try:
        BriefingSnapshot.objects.update_or_create(
            category=category, data_hash=signature,
            defaults={"model": model, "items": items},
        )
    except Exception:  # noqa: BLE001 — caching is best-effort
        logger.exception("Briefing: failed to persist snapshot.")
    return items


# ─── Per-department generation ────────────────────────────────────────


def _call_department(api_key: str, model: str, context_json: str, agent) -> list[dict]:
    try:
        import anthropic
    except ImportError:
        return []

    label = _DEPT_LABEL.get(agent.key, agent.name)
    role = (
        f"Eres el analista del área {label} de un club de fútbol profesional. "
        "Generas las recomendaciones más accionables de tu área para el "
        "briefing diario del cuerpo técnico, en español (Chile), apoyándote en "
        "tu base de conocimiento y playbook."
    )
    knowledge = (agent.knowledge or "").strip()
    dept_system = role
    if knowledge:
        dept_system += "\n\n# Tu base de conocimiento y playbook\n" + knowledge
    dept_system += "\n\n" + _BRIEFING_CONTRACT

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=[
                # Shared squad snapshot — identical across departments, so the
                # prompt-cache prefix is reused for the parallel calls.
                {
                    "type": "text",
                    "text": "# Snapshot actual del equipo (JSON)\n" + context_json,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": dept_system},
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Genera el briefing del área {label}: identifica las 0 a 4 "
                        "recomendaciones más accionables para hoy según tus señales "
                        "prioritarias y el snapshot. Responde con el objeto JSON."
                    ),
                }
            ],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Briefing: model call failed for '%s'.", agent.key)
        return []

    from dashboards.llm_usage import log_usage
    log_usage(f"briefing:{agent.key}", model, response)

    text = _extract_text(response)
    return _parse_items(text, department=agent.key, label=label)


def _parse_items(text: str, *, department: str, label: str) -> list[dict]:
    raw = _extract_json_object(text)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out: list[dict] = []
    for it in (data.get("items") if isinstance(data, dict) else []) or []:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        priority = str(it.get("priority") or "media").strip().lower()
        if priority not in _PRIORITY_ORDER:
            priority = "media"
        out.append({
            "department": department,
            "department_label": label,
            "priority": priority,
            "tags": [str(t).strip() for t in (it.get("tags") or []) if str(t).strip()][:3],
            "title": title[:120],
            "recommendation": str(it.get("recommendation") or "").strip(),
            "evidence": [str(e).strip() for e in (it.get("evidence") or []) if str(e).strip()][:4],
            "confidence": _clamp_pct(it.get("confidence")),
            "owner_role": str(it.get("owner_role") or label).strip(),
            "timing": str(it.get("timing") or "").strip(),
            "cta_label": str(it.get("cta_label") or "").strip(),
            "players": [str(p).strip() for p in (it.get("players") or []) if str(p).strip()][:6],
        })
    return out


def _rank(items: list[dict]) -> list[dict]:
    items.sort(key=lambda i: (_PRIORITY_ORDER.get(i["priority"], 1), -(i["confidence"] or 0)))
    return items


# ─── Player-id resolution (§7.2 — deep-link the card to its jugador) ───

def _norm(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _resolve_player_ids(names: list[str], roster: list) -> list[str]:
    """Map free-text player names (LLM output, drawn from the snapshot) to
    roster ids. `roster` is [(id, first_name, last_name)]. Pure — matches on
    normalized full name, then unambiguous last name. Best-effort."""
    by_full: dict[str, str] = {}
    by_last: dict[str, list[str]] = {}
    for pid, fn, ln in roster:
        by_full[_norm(f"{fn} {ln}")] = str(pid)
        by_last.setdefault(_norm(ln), []).append(str(pid))
    out: list[str] = []
    for name in names or []:
        n = _norm(name)
        pid = by_full.get(n)
        if pid is None:
            parts = n.split()
            cand = by_last.get(n) or (by_last.get(parts[-1]) if parts else None)
            if cand and len(cand) == 1:
                pid = cand[0]
        if pid and pid not in out:
            out.append(pid)
    return out


def _attach_player_ids(items: list[dict], category) -> None:
    """Add `player_ids` to each item from its `players` names (in place)."""
    if not items:
        return
    from core.models import Player

    roster = list(
        Player.objects.filter(category=category, is_active=True)
        .values_list("id", "first_name", "last_name")
    )
    for it in items:
        it["player_ids"] = _resolve_player_ids(it.get("players") or [], roster)


# ─── Helpers ──────────────────────────────────────────────────────────


def _signature(context: dict, agents, model: str) -> str:
    stable = {k: v for k, v in context.items() if k != "fecha"}
    agents_fp = "|".join(sorted(a.config_fingerprint() for a in agents))
    basis = (
        f"briefing\n{_RENDER_VERSION}\n{model}\n{agents_fp}\n"
        + json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str)
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _clamp_pct(v) -> int:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 70
    if n <= 1.0:  # tolerate 0–1 floats
        n *= 100
    return max(0, min(100, round(n)))


def _extract_text(response) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def _extract_json_object(text: str) -> str | None:
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
