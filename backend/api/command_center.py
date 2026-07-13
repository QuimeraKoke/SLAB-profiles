"""Command-center ("Centro de mando") dashboard aggregation.

One read that assembles the whole screen from data SLAB already owns:
player state, alerts, events, GPS load, wellness. The expensive LLM
**briefing** is generated + cached separately (see
`dashboards/docx`/`pdf` narrative layer) and folded in by the endpoint.

Everything returned here is JSON-serializable (dates → isoformat).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from core.models import Player
from events.models import Event
from exams.models import ExamResult, ExamTemplate
from goals.models import Alert, AlertStatus
from dashboards.models import PlayerMetricState
from dashboards.player_state import _GPS_MATCH_SLUG, _GPS_TRAIN_SLUG


# Status → Spanish label + the rank used to order the squad list (worst first).
_STATUS_LABEL = {
    Player.STATUS_INJURED: "Lesionado",
    Player.STATUS_RECOVERY: "Recuperación",
    Player.STATUS_REINTEGRATION: "Return to Train",
    Player.STATUS_AVAILABLE: "Disponible",
}


def build_command_center(category) -> dict:
    now = timezone.now()
    players = list(
        Player.objects.filter(category=category, is_active=True)
        .select_related("position")
    )
    player_ids = [p.id for p in players]

    # Active alerts for the roster, fetched once and shared across sections.
    alerts = list(
        Alert.objects.filter(player_id__in=player_ids, status=AlertStatus.ACTIVE)
        .select_related("player")
        .order_by("-severity", "-last_fired_at")
    )
    alerts_by_player: dict[Any, list] = {}
    for a in alerts:
        alerts_by_player.setdefault(a.player_id, []).append(a)
    crit_player_ids = {
        a.player_id for a in alerts if a.severity == "critical"
    }

    # Materialized state per player (weekly load, latest bands).
    states = {
        s.player_id: (s.state or {})
        for s in PlayerMetricState.objects.filter(player_id__in=player_ids)
    }

    return {
        "category": category.name,
        "generated_at": now.isoformat(),
        "context": _context(category, players, states, crit_player_ids, now),
        "kpis": _kpis(category, players, states, alerts, crit_player_ids, now),
        "squad": _squad(players, crit_player_ids),
        "decisions": _decisions(players, alerts_by_player, states),
        "data_quality": _data_quality(category, player_ids, now),
        "checkin_adherence": _checkin_adherence(category, players, now),
        "recent": _recent(alerts),
    }


# ─── Context (next match + pre-match risk) ────────────────────────────

# A weekly-load "over ceiling" verdict is only trusted when its window is
# recent — otherwise a stale materialized state keeps flagging load after the
# player stopped training (the "5 días libres → sobreentrenamiento" bug).
_WEEKLY_LOAD_MAX_STALE_DAYS = 3


def _weekly_load_over_ceiling(state, now) -> bool:
    wl = (state or {}).get("weekly_load") or {}
    metrics = wl.get("metrics") or []
    if not any(c.get("status") == "over" for c in metrics):
        return False
    to = (wl.get("window") or {}).get("to")
    try:
        to_dt = datetime.fromisoformat(to) if to else None
    except (ValueError, TypeError):
        to_dt = None
    if to_dt is None:
        return False
    return (now.date() - to_dt.date()).days <= _WEEKLY_LOAD_MAX_STALE_DAYS


def _context(category, players, states, crit_player_ids, now) -> dict:
    nxt = (
        Event.objects.filter(
            category=category, event_type=Event.TYPE_MATCH, starts_at__gte=now,
        ).order_by("starts_at").first()
    )
    last = (
        Event.objects.filter(
            category=category, event_type=Event.TYPE_MATCH, starts_at__lt=now,
        ).order_by("-starts_at").first()
    )

    next_match = None
    if nxt is not None:
        meta = nxt.metadata or {}
        days_until = max(0, (nxt.starts_at.date() - now.date()).days)
        next_match = {
            "title": nxt.title,
            "competition": meta.get("competition") or meta.get("tournament"),
            "starts_at": nxt.starts_at.isoformat(),
            "location": nxt.location or "",
            "is_home": meta.get("is_home"),
            "days_until": days_until,
            "md_label": f"MD-{days_until}" if days_until > 0 else "MD",
        }

    last_result = None
    if last is not None:
        meta = last.metadata or {}
        last_result = {
            "title": last.title,
            "score": meta.get("score") or meta.get("result"),
            "starts_at": last.starts_at.isoformat(),
        }

    # Pre-match risk: players with any weekly-load concept over its ceiling
    # (only when the load window is recent — see _weekly_load_over_ceiling).
    over = [p for p in players if _weekly_load_over_ceiling(states.get(p.id), now)]
    risk = {
        "count": len(over),
        "headline": (
            f"{len(over)} jugador{'es' if len(over) != 1 else ''} sobre umbral de carga"
            if over else "Sin jugadores sobre umbral de carga"
        ),
        "players": [_short_name(p) for p in over[:5]],
    }

    return {"next_match": next_match, "last_result": last_result, "pre_match_risk": risk}


# ─── KPI strip ────────────────────────────────────────────────────────


def _kpis(category, players, states, alerts, crit_player_ids, now) -> dict:
    total = len(players)
    by_status = _status_counts(players)
    available = by_status.get(Player.STATUS_AVAILABLE, 0)

    return {
        "disponibilidad": {
            "value": f"{available}/{total}",
            "available": available,
            "total": total,
            "breakdown": [
                {"label": "lesionados", "n": by_status.get(Player.STATUS_INJURED, 0), "tone": "crit"},
                {"label": "recuperación", "n": by_status.get(Player.STATUS_RECOVERY, 0), "tone": "warn"},
                {"label": "return to train", "n": by_status.get(Player.STATUS_REINTEGRATION, 0), "tone": "info"},
            ],
        },
        "riesgo": _kpi_riesgo(players, alerts, crit_player_ids),
        "carga": _kpi_carga(category, players, now),
        "wellness": _kpi_wellness(category, players),
        "completitud": _kpi_completitud(category, [p.id for p in players], now),
    }


def _kpi_riesgo(players, alerts, crit_player_ids) -> dict:
    name_by_id = {p.id: _short_name(p) for p in players}
    names = [name_by_id[pid] for pid in crit_player_ids if pid in name_by_id]
    return {
        "value": len(crit_player_ids),
        "label": "altos",
        "status": "Revisar" if crit_player_ids else "OK",
        "tone": "crit" if crit_player_ids else "ok",
        "players": names[:4],
    }


def _kpi_carga(category, players, now) -> dict:
    """Team ACWR = mean of the per-player ratio for the category's primary
    configured load variable (default: total distance, 7d ÷ 28d; see
    `dashboards.acwr`). Defensive: None when GPS is sparse."""
    from dashboards.acwr import compute_acwr, gps_templates, resolve_specs

    templates = gps_templates(category)
    if not templates:
        return {"value": None, "status": "Sin datos", "tone": "muted",
                "detail": "Sin plantillas GPS para esta categoría."}

    spec = resolve_specs(category)[0]
    pids = [p.id for p in players if getattr(p, "is_active", True)]
    data = compute_acwr(pids, category, spec, now=now, templates=templates)
    ratios = [d["ratio"] for d in data.values()]
    over = sum(1 for d in data.values() if d["ratio"] > spec.sweet_high)
    if not ratios:
        return {"value": None, "status": "Sin datos", "tone": "muted",
                "detail": "Datos GPS insuficientes para ACWR."}

    team = sum(ratios) / len(ratios)
    # Team warns as the mean nears the ceiling (default sweet_high 1.3 → 1.2).
    tone = "crit" if over else ("warn" if team > spec.sweet_high - 0.1 else "ok")
    return {
        "value": round(team, 2),
        "status": (f"{over} sobre umbral" if over else "En rango"),
        "tone": tone,
        "over": over,
        "detail": (f"ACWR agudo:crónico ({spec.acute_days}d vs {spec.chronic_days}d). "
                   f"Rango objetivo {spec.sweet_low}–{spec.sweet_high}."),
    }


def _kpi_wellness(category, players) -> dict:
    """Team wellness from the real Check-IN data (`checkin_fisico`), each
    item normalized by its own scale (recuperación ÷10, the others ÷5) and
    averaged to 0–100. See `api/wellness.py`."""
    from api import wellness as w

    pids = [p.id for p in players]
    fmax = w.field_max(category)
    recent = w.recent_by_player(category, pids, limit=1)

    scores: list[float] = []
    dim_acc: dict[str, list[float]] = {k: [] for k, _ in w.DIMENSIONS}
    for datas in recent.values():
        latest = datas[0]
        s = w.score(latest, fmax)
        if s is not None:
            scores.append(s)
        for k, _ in w.DIMENSIONS:
            dv = w.dimension_pct(latest, k, fmax)
            if dv is not None:
                dim_acc[k].append(dv)

    if not scores:
        return {"value": None, "status": "Sin datos", "tone": "muted", "dimensions": []}
    team = round(sum(scores) / len(scores))
    return {
        "value": team,
        "status": "Bueno" if team >= 75 else ("Aceptable" if team >= 60 else "Bajo"),
        "tone": "ok" if team >= 75 else ("warn" if team >= 60 else "crit"),
        "responses": len(scores),
        "expected": len(players),
        "dimensions": [
            {"label": lbl, "value": round(sum(dim_acc[k]) / len(dim_acc[k]))}
            for k, lbl in w.DIMENSIONS if dim_acc[k]
        ],
    }


def _kpi_completitud(category, player_ids, now) -> dict:
    """Today's data completeness across the cheap-to-measure sources
    (GPS + Wellness). Other sources are surfaced in `data_quality`."""
    today = now.date()
    n = len(player_ids) or 1

    gps_templates = list(ExamTemplate.objects.filter(
        slug__in=[_GPS_MATCH_SLUG, _GPS_TRAIN_SLUG],
        applicable_categories=category,
    ).values_list("id", flat=True))
    well_templates = list(ExamTemplate.objects.filter(
        slug="checkin_fisico", applicable_categories=category,
    ).values_list("id", flat=True))

    gps_n = (
        ExamResult.objects.filter(
            player_id__in=player_ids, template_id__in=gps_templates,
            recorded_at__date=today,
        ).values("player_id").distinct().count()
        if gps_templates else 0
    )
    well_n = (
        ExamResult.objects.filter(
            player_id__in=player_ids, template_id__in=well_templates,
            recorded_at__date=today,
        ).values("player_id").distinct().count()
        if well_templates else 0
    )

    measured = []
    if gps_templates:
        measured.append(min(1.0, gps_n / n))
    if well_templates:
        measured.append(min(1.0, well_n / n))
    pct = round(sum(measured) / len(measured) * 100) if measured else None

    return {
        "value": pct,
        "status": ("Completo" if (pct or 0) >= 95 else "Incompleto"),
        "tone": "ok" if (pct or 0) >= 95 else "warn",
        "breakdown": [
            {"label": "GPS", "n": gps_n, "expected": len(player_ids)},
            {"label": "wellness", "n": well_n, "expected": len(player_ids)},
        ],
    }


def _checkin_adherence(category, players, now) -> dict:
    """Today's check-in adherence: BOTH the non-responders and the responders
    (each player deep-linkable to its ficha), so the card can label who's who.
    Informative — no alert. Feeds the Centro de mando adherence card."""
    from api.wellness import WELLNESS_SLUG

    today = timezone.localdate()
    tids = list(
        ExamTemplate.objects.filter(slug=WELLNESS_SLUG, applicable_categories=category)
        .values_list("id", flat=True)
    ) or list(ExamTemplate.objects.filter(slug=WELLNESS_SLUG).values_list("id", flat=True))
    responded_ids = set(
        ExamResult.objects.filter(
            player_id__in=[p.id for p in players],
            template_id__in=tids, recorded_at__date=today,
        ).values_list("player_id", flat=True)
    ) if tids else set()

    def _row(p):
        return {
            "player_id": str(p.id),
            "name": _short_name(p),
            "position": p.position.abbreviation if p.position else None,
            "injured": p.status != Player.STATUS_AVAILABLE,
        }

    no_resp = [_row(p) for p in players if p.id not in responded_ids]
    resp = [_row(p) for p in players if p.id in responded_ids]
    expected = len(players)
    return {
        "responded": len(resp),
        "expected": expected,
        "pct": round(len(resp) / expected * 100) if expected else None,
        "no_respondieron": no_resp,
        "respondieron": resp,
    }


# ─── Squad status (rail) ──────────────────────────────────────────────


def _squad(players, crit_player_ids) -> dict:
    by_status = _status_counts(players)
    counts = {
        "disponibles": by_status.get(Player.STATUS_AVAILABLE, 0),
        "riesgo_alto": len(crit_player_ids),
        "reintegracion": by_status.get(Player.STATUS_REINTEGRATION, 0),
        "lesionados": by_status.get(Player.STATUS_INJURED, 0),
        "recuperacion": by_status.get(Player.STATUS_RECOVERY, 0),
    }

    # Availability by line (position.role), available ÷ total in line.
    lines: dict[str, list] = {}
    for p in players:
        line = (p.position.role if p.position and p.position.role else "Sin línea")
        lines.setdefault(line, []).append(p)
    por_linea = [
        {
            "linea": line,
            "pct": round(
                sum(1 for p in ps if p.status == Player.STATUS_AVAILABLE) / len(ps) * 100
            ),
            "total": len(ps),
        }
        for line, ps in sorted(lines.items())
    ]

    # Player list — worst status first, then names; cap to a readable list.
    ordered = sorted(
        players,
        key=lambda p: (Player.STATUS_RANK.get(p.status, 9), p.last_name),
    )
    player_rows = [
        {
            "id": str(p.id),
            "initials": _initials(p),
            "name": f"{p.first_name} {p.last_name}".strip(),
            "status": p.status,
            "status_label": _STATUS_LABEL.get(p.status, p.status),
            "at_risk": p.id in crit_player_ids,
        }
        for p in ordered[:8]
    ]

    return {"counts": counts, "por_linea": por_linea, "players": player_rows}


# ─── Decisions table ──────────────────────────────────────────────────


def _decisions(players, alerts_by_player, states) -> list[dict]:
    name_by_id = {p.id: p for p in players}
    rows = []
    for pid, alerts in alerts_by_player.items():
        p = name_by_id.get(pid)
        if p is None:
            continue
        top = alerts[0]  # already severity-then-recency ordered
        rows.append({
            "player_id": str(pid),
            "initials": _initials(p),
            "player": f"{p.first_name} {p.last_name}".strip(),
            "status": p.status,
            "status_label": _STATUS_LABEL.get(p.status, p.status),
            "signal": top.message[:80],
            "priority": "alta" if top.severity == "critical" else (
                "media" if top.severity == "warning" else "baja"),
            "alerts": len(alerts),
        })
    order = {"alta": 0, "media": 1, "baja": 2}
    rows.sort(key=lambda r: order.get(r["priority"], 3))
    return rows[:8]


# ─── Data quality (rail) ──────────────────────────────────────────────


def _data_quality(category, player_ids, now) -> list[dict]:
    """Per-source freshness: how long since the last upload + how many
    players that last upload covered. `last_at` is the most recent
    `recorded_at`; `players` counts the distinct players uploaded on that
    last day (e.g. the squad in the last match / training session)."""
    from api import wellness as w  # WELLNESS_SLUG (real check-in template)

    n = len(player_ids)
    today = timezone.localdate(now)

    def freshness(slugs):
        tids = list(ExamTemplate.objects.filter(
            slug__in=slugs, applicable_categories=category,
        ).values_list("id", flat=True))
        if not tids:
            return None  # no template configured
        qs = ExamResult.objects.filter(player_id__in=player_ids, template_id__in=tids)
        last_at = qs.order_by("-recorded_at").values_list("recorded_at", flat=True).first()
        if last_at is None:
            return "empty"
        last_day = timezone.localtime(last_at).date()
        players = (
            qs.filter(recorded_at__date=last_day)
            .values("player_id").distinct().count()
        )
        return last_at, last_day, players

    def measured_row(label, slugs):
        base = {"source": label, "last_at": None, "players": None, "expected": n}
        f = freshness(slugs)
        if f is None:
            return {**base, "status": "muted", "detail": "Sin plantilla"}
        if f == "empty":
            return {**base, "status": "muted", "detail": "Sin datos cargados"}
        last_at, last_day, players = f
        days = (today - last_day).days
        # Fresh ≤3d, stale ≤14d, otherwise critical-old.
        status = "ok" if days <= 3 else ("warn" if days <= 14 else "crit")
        return {**base, "status": status, "detail": "",
                "last_at": last_at.isoformat(), "players": players}

    rows = [
        measured_row("GPS", [_GPS_MATCH_SLUG, _GPS_TRAIN_SLUG]),
        measured_row("Wellness", [w.WELLNESS_SLUG]),
    ]
    # Sources we don't measure automatically yet — surfaced so the operator
    # knows they exist (no freshness data to show).
    for label in ("Médico", "Nutrición", "Isocinético"):
        rows.append({"source": label, "status": "muted",
                     "detail": "Sin medición automática",
                     "last_at": None, "players": None, "expected": n})
    return rows


# ─── Recent activity (rail) ───────────────────────────────────────────


def _recent(alerts) -> list[dict]:
    """Lightweight activity feed derived from the most recent active alerts.
    A richer audit trail is a future addition (stubbed source for now)."""
    items = []
    for a in alerts[:6]:
        items.append({
            "kind": a.severity,
            "text": f"{a.player.first_name} {a.player.last_name}: {a.message[:70]}",
            "at": a.last_fired_at.isoformat() if a.last_fired_at else None,
        })
    return items


# ─── Helpers ──────────────────────────────────────────────────────────


def _status_counts(players) -> dict:
    out: dict[str, int] = {}
    for p in players:
        out[p.status] = out.get(p.status, 0) + 1
    return out


def _initials(p) -> str:
    a = (p.first_name or " ")[0]
    b = (p.last_name or " ")[0]
    return (a + b).upper()


def _short_name(p) -> str:
    parts = (p.last_name or p.first_name or "").split()
    return parts[0] if parts else "—"
