"""Command-center ("Centro de mando") dashboard aggregation.

One read that assembles the whole screen from data SLAB already owns:
player state, alerts, events, GPS load, wellness. The expensive LLM
**briefing** is generated + cached separately (see
`dashboards/docx`/`pdf` narrative layer) and folded in by the endpoint.

Everything returned here is JSON-serializable (dates → isoformat).
"""

from __future__ import annotations

from datetime import timedelta
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
    Player.STATUS_REINTEGRATION: "Reintegración",
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
        "recent": _recent(alerts),
    }


# ─── Context (next match + pre-match risk) ────────────────────────────


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

    # Pre-match risk: players with any weekly-load concept over its ceiling.
    over = [
        p for p in players
        if any(
            c.get("status") == "over"
            for c in (((states.get(p.id) or {}).get("weekly_load") or {}).get("metrics") or [])
        )
    ]
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
                {"label": "reintegración", "n": by_status.get(Player.STATUS_REINTEGRATION, 0), "tone": "info"},
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
    """Team ACWR = mean of per-player (acute 7d ÷ chronic 28d-weekly) total
    distance, over matches + trainings. Defensive: None when GPS is sparse."""
    templates = list(
        ExamTemplate.objects.filter(
            slug__in=[_GPS_MATCH_SLUG, _GPS_TRAIN_SLUG],
            applicable_categories=category, is_active_version=True,
        ).distinct()
    )
    if not templates:
        return {"value": None, "status": "Sin datos", "tone": "muted",
                "detail": "Sin plantillas GPS para esta categoría."}

    field_by_template = {
        t.id: ("tot_dist_total" if t.slug == _GPS_MATCH_SLUG else "tot_dist")
        for t in templates
    }
    since = now - timedelta(days=28)
    acute_cut = now - timedelta(days=7)
    rows = ExamResult.objects.filter(
        player__category=category, player__is_active=True,
        template__in=templates, recorded_at__gte=since,
    ).values_list("player_id", "template_id", "recorded_at", "result_data")

    acute: dict[Any, float] = {}
    chronic: dict[Any, float] = {}
    for player_id, template_id, recorded_at, data in rows:
        v = _coerce((data or {}).get(field_by_template.get(template_id)))
        if v is None:
            continue
        chronic[player_id] = chronic.get(player_id, 0.0) + v
        if recorded_at >= acute_cut:
            acute[player_id] = acute.get(player_id, 0.0) + v

    ratios = []
    over = 0
    for pid, ch in chronic.items():
        weekly_chronic = ch / 4.0
        if weekly_chronic <= 0:
            continue
        r = acute.get(pid, 0.0) / weekly_chronic
        ratios.append(r)
        if r > 1.3:
            over += 1
    if not ratios:
        return {"value": None, "status": "Sin datos", "tone": "muted",
                "detail": "Datos GPS insuficientes para ACWR."}

    team = sum(ratios) / len(ratios)
    tone = "crit" if over else ("warn" if team > 1.2 else "ok")
    return {
        "value": round(team, 2),
        "status": (f"{over} sobre umbral" if over else "En rango"),
        "tone": tone,
        "over": over,
        "detail": "ACWR agudo:crónico (7d vs 28d). Rango objetivo 0.8–1.3.",
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
    well_templates = list(ExamTemplate.objects.filter(slug="check_in").values_list("id", flat=True))

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
    today = now.date()
    n = len(player_ids)

    def coverage(slugs):
        tids = list(ExamTemplate.objects.filter(
            slug__in=slugs, applicable_categories=category,
        ).values_list("id", flat=True))
        if not tids:
            return None
        return ExamResult.objects.filter(
            player_id__in=player_ids, template_id__in=tids, recorded_at__date=today,
        ).values("player_id").distinct().count()

    def row(label, slugs):
        c = coverage(slugs)
        if c is None:
            return {"source": label, "status": "muted", "detail": "Sin plantilla"}
        ok = c >= n
        return {
            "source": label,
            "status": "ok" if ok else "warn",
            "detail": f"{c}/{n} jugadores hoy" if not ok else f"Actualizado · {c}/{n}",
        }

    rows = [
        row("GPS", [_GPS_MATCH_SLUG, _GPS_TRAIN_SLUG]),
        row("Wellness", ["check_in"]),
    ]
    # Sources we don't measure yet — surfaced so the operator knows they exist.
    for label in ("Médico", "Nutrición", "Isocinético"):
        rows.append({"source": label, "status": "muted", "detail": "Sin medición automática"})
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


def _coerce(raw) -> float | None:
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
