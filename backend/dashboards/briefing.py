"""Centro de mando AI Briefing — ranked recommendation cards.

One LLM call per department: each department's `InsightAgent` (its persona
+ research-grounded playbook KB) reads the squad's live snapshot and emits
0–4 actionable cards for its area. The cards are merged, ranked by priority
then confidence, and cached (`BriefingSnapshot`) PER DEPARTMENT — each keyed
on the slice of the snapshot that department materially depends on, so a
change regenerates only the affected area(s) rather than all five.

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


# ─── Per-department change-detection (only rebuild what changed) ───────
#
# Each department's cards are cached against the SLICE of the snapshot that
# department materially depends on, so a GPS upload rebuilds only Físico, a
# wellness sync only Wellness, etc. — not all five. The model still receives
# the WHOLE snapshot on every (re)generation, so a rebuilt card is exactly
# what it is today; only the *when-to-rebuild* decision changes. The bias is
# toward over-waking (an unresolved metric wakes everyone), so a card is
# never stale — at worst it rebuilds as often as before.

# Cross-cutting framing hashed into EVERY department's key: squad status,
# next match, pre-match risk, active alerts (which carry no per-department
# attribution), data quality. A change here reframes all areas → all rebuild.
_GLOBAL_KEYS = (
    "categoria", "kpis", "estado_plantel", "disponibilidad_por_linea",
    "proximo_partido", "riesgo_pre_partido", "jugadores_que_requieren_decision",
    "calidad_de_datos", "alertas_activas",
)
# Per-player identity/status is framing too (an injury flips availability for
# everyone) → in every department's key. Weekly GPS load is routed, not framing.
_ROSTER_IDENTITY = ("nombre", "posicion", "estado", "edad")
# Weekly GPS load wakes Físico + Médico (load ↔ injury risk).
_LOAD_DEPTS = ("fisico", "medico")
# A metric's home department (from its template) also wakes these — wellness/
# psicosocial signals are clinically relevant (molestia ↔ Médico).
_METRIC_EXTRA_LINKS = {"psicosocial": ("medico",)}


def generate_briefing(category) -> list[dict]:
    """Ranked briefing cards for the category. Each department's cards are
    cached independently, keyed on the slice of the snapshot that department
    materially depends on — so a change rebuilds only the affected area(s),
    not all five. Never raises."""
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
    if not agents:
        return []
    model = getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")

    # One cache key per department, over only that department's material slice.
    tpl_to_dept = _template_department_map()
    per_dept_sig = {
        a.key: _dept_signature(_material_view(context, a.key, tpl_to_dept), a, model)
        for a in agents
    }
    cached = {
        r.data_hash: (r.items or [])
        for r in BriefingSnapshot.objects.filter(
            category=category, data_hash__in=list(per_dept_sig.values())
        )
    }

    items: list[dict] = []
    stale = []  # departments whose slice changed → must regenerate
    for a in agents:
        hit = cached.get(per_dept_sig[a.key])
        if hit is not None:
            items.extend(hit)
        else:
            stale.append(a)

    if stale and api_key:
        context_json = json.dumps(
            {k: v for k, v in context.items() if k != "fecha"},
            ensure_ascii=False, default=str,
        )
        # The shared squad snapshot is a cached prefix, but concurrent calls
        # can't read each other's cache. So warm it with the first stale
        # department serially, THEN fan out the rest — they read the prefix
        # the first call wrote instead of each paying to re-write it.
        first, rest = stale[0], stale[1:]
        items.extend(_generate_and_store(
            category, per_dept_sig[first.key], api_key, model, context_json, first
        ))
        if rest:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(rest))) as pool:
                futures = {
                    pool.submit(_call_department, api_key, model, context_json, a): a
                    for a in rest
                }
                for fut in concurrent.futures.as_completed(futures):
                    a = futures[fut]
                    try:
                        a_items = fut.result()
                    except Exception:  # noqa: BLE001 — one area failing must not sink the rest
                        logger.exception("Briefing: department '%s' failed.", a.key)
                        a_items = []
                    _persist_dept(category, per_dept_sig[a.key], model, a_items)
                    items.extend(a_items)

    items = _rank(items)
    _attach_player_ids(items, category)
    return items


def _generate_and_store(
    category, data_hash: str, api_key: str, model: str, context_json: str, agent
) -> list[dict]:
    """Serial warm call for one department + persist its cards. Never raises."""
    try:
        dept_items = _call_department(api_key, model, context_json, agent)
    except Exception:  # noqa: BLE001 — one area failing must not sink the rest
        logger.exception("Briefing: department '%s' failed.", agent.key)
        dept_items = []
    _persist_dept(category, data_hash, model, dept_items)
    return dept_items


def _persist_dept(category, data_hash: str, model: str, dept_items: list[dict]) -> None:
    """Best-effort cache of one department's cards, keyed on its slice hash."""
    from dashboards.models import BriefingSnapshot

    try:
        BriefingSnapshot.objects.update_or_create(
            category=category, data_hash=data_hash,
            defaults={"model": model, "items": dept_items},
        )
    except Exception:  # noqa: BLE001 — caching is best-effort
        logger.exception("Briefing: failed to persist department snapshot.")


def _template_department_map() -> dict:
    """Template display-name → department slug, from ExamTemplate — routes each
    per-player metric to its home department for change-detection. A name that
    resolves to >1 department is dropped (treated as global). Never raises; an
    empty map just means every metric is global (safe: more rebuilds, never a
    stale card)."""
    try:
        from exams.models import ExamTemplate

        pairs = list(ExamTemplate.objects.values_list("name", "department__slug"))
    except Exception:  # noqa: BLE001
        return {}
    mapping: dict = {}
    ambiguous: set = set()
    for name, dept in pairs:
        if not name or not dept:
            continue
        if name in mapping and mapping[name] != dept:
            ambiguous.add(name)
        mapping[name] = dept
    for name in ambiguous:
        mapping.pop(name, None)
    return mapping


def _metric_owner_depts(area, tpl_to_dept: dict):
    """Department keys a metric with template-name `area` wakes, or None if it
    can't be resolved to a known department → treated as global (wakes all)."""
    home = tpl_to_dept.get(area)
    if home is None or home not in _DEPT_LABEL:
        return None
    return {home, *_METRIC_EXTRA_LINKS.get(home, ())}


def _material_view(context: dict, dept_key: str, tpl_to_dept: dict) -> dict:
    """The slice of the snapshot department `dept_key` materially depends on:
    the global framing block + its own per-player metric detail. Drives the
    cache key ONLY — the full snapshot is still sent to the model — so a card
    rebuilds exactly when its own inputs move."""
    view = {k: context[k] for k in _GLOBAL_KEYS if k in context}
    roster_view = []
    for p in context.get("plantel") or []:
        entry = {k: p.get(k) for k in _ROSTER_IDENTITY}
        if dept_key in _LOAD_DEPTS and p.get("carga_semanal"):
            entry["carga_semanal"] = p["carga_semanal"]
        mine = []
        for met in p.get("metricas") or []:
            owners = _metric_owner_depts(met.get("area"), tpl_to_dept)
            if owners is None or dept_key in owners:
                mine.append(met)
        if mine:
            entry["metricas"] = mine
        roster_view.append(entry)
    view["plantel"] = roster_view
    return view


def _dept_signature(view: dict, agent, model: str) -> str:
    basis = (
        f"briefing-dept\n{_RENDER_VERSION}\n{model}\n{agent.key}\n"
        f"{agent.config_fingerprint()}\n"
        + json.dumps(view, ensure_ascii=False, sort_keys=True, default=str)
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


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
