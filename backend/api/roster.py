"""Roster view metrics for the Plantel/Equipo screen.

One read that returns, per active player: status, a **readiness** composite,
**wellness** (latest check-in, 0–100), **ACWR** (acute:chronic load), and a
**forma** sparkline (recent wellness trend) — plus status counts for the
filter tabs. Reuses the same data the Centro de mando draws on.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core.models import Player
from dashboards.acwr import compute_acwr, resolve_specs

_STATUS_LABEL = {
    Player.STATUS_INJURED: "Lesionado",
    Player.STATUS_RECOVERY: "Recuperación",
    Player.STATUS_REINTEGRATION: "Return to Train",
    Player.STATUS_AVAILABLE: "Disponible",
}
# How much each availability state discounts readiness.
_STATUS_FACTOR = {
    Player.STATUS_INJURED: 0.45,
    Player.STATUS_RECOVERY: 0.80,
    Player.STATUS_REINTEGRATION: 0.90,
    Player.STATUS_AVAILABLE: 1.0,
}


def build_roster(category) -> dict:
    players = list(
        Player.objects.filter(category=category, is_active=True)
        .select_related("position").order_by("last_name", "first_name")
    )
    pids = [p.id for p in players]

    wellness, forma = _wellness_and_forma(category, pids)
    acwr = _player_acwr(category, pids, with_detail=True)

    # Cached agent-refined readiness (computed off-request); deterministic
    # fallback until a player's first agent value lands. See dashboards/readiness.py.
    from dashboards.models import PlayerReadiness
    readiness = {
        r.player_id: (r.score, r.source, r.rationale)
        for r in PlayerReadiness.objects.filter(player_id__in=pids)
    }

    rows = []
    counts = {"all": len(players), "available": 0, "reintegration": 0,
              "recovery": 0, "injured": 0}
    for p in players:
        counts[p.status] = counts.get(p.status, 0) + 1
        w = wellness.get(p.id)
        a_meta = acwr.get(p.id)                       # dict or None
        a = a_meta["ratio"] if a_meta else None       # ratio float for readiness/tone
        cached = readiness.get(p.id)
        if cached and cached[0] is not None:
            score, source, rationale = cached
        else:
            score, source, rationale = _readiness(w, a, p.status), "deterministic", ""
        rows.append({
            "id": str(p.id),
            "initials": _initials(p),
            "photo": p.photo_url or None,
            "name": f"{p.first_name} {p.last_name}".strip(),
            "position": (p.position.name or p.position.abbreviation) if p.position else "—",
            "status": p.status,
            "status_label": _STATUS_LABEL.get(p.status, p.status),
            "readiness": score,
            "readiness_source": source,
            "readiness_note": rationale,
            "wellness": w,
            "acwr": a,
            "acwr_meta": a_meta,
            "forma": forma.get(p.id, []),
        })
    return {"category": category.name, "counts": counts, "players": rows}


# ─── Metrics ──────────────────────────────────────────────────────────


def _wellness_and_forma(category, pids: list) -> tuple[dict, dict]:
    """Latest wellness (0–100, real `checkin_fisico` data, per-item-scale
    normalized) + the "Tendencia wellness" sparkline. The sparkline shows the
    **past 7 days** of check-ins (oldest→newest); the wellness value is the
    most recent check-in regardless of date."""
    from api import wellness as w

    fmax = w.field_max(category)
    # Wellness value = the latest check-in (any date).
    latest = w.recent_by_player(category, pids, limit=1)
    # Tendencia sparkline = check-ins from the past 7 days only (with dates so
    # each bar can show value + date in a tooltip).
    window = w.recent_by_player(
        category, pids, since=timezone.now() - timedelta(days=7), with_dates=True,
    )

    wellness, forma = {}, {}
    for pid, datas in latest.items():
        s = w.score(datas[0], fmax) if datas else None
        if s is not None:
            wellness[pid] = s

    today = timezone.localdate()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]  # 7 days, oldest→newest
    for pid, items in window.items():
        # Latest valid score per local day (items are newest-first).
        by_day: dict = {}
        for rec, data in items:
            d = timezone.localtime(rec).date()
            if d in by_day:
                continue
            s = w.score(data, fmax)
            if s is not None:
                by_day[d] = s
        if not by_day:
            continue  # no valid check-ins this week → forma stays [] → single "—"
        # One slot per day; days without a check-in are empty (rendered as "—").
        bars = []
        for d in days:
            s = by_day.get(d)
            if s is not None:
                bars.append({"value": s, "tone": _score_tone(s), "date": d.isoformat()})
            else:
                bars.append({"value": None, "date": d.isoformat()})
        forma[pid] = bars
    return wellness, forma


def _player_acwr(category, pids: list, with_detail: bool = False) -> dict:
    """Per-player ACWR for the category's primary configured load variable
    (default: total distance, 7d acute ÷ 28d chronic; see `dashboards.acwr`).
    None when GPS is too sparse. With `with_detail=True` each value is a dict
    {ratio, acute_km, chronic_week_km, last} for tooltips; otherwise just the
    ratio float (what `_readiness` / player_analysis expect)."""
    spec = resolve_specs(category)[0]
    data = compute_acwr(pids, category, spec)
    if not with_detail:
        return {pid: d["ratio"] for pid, d in data.items()}
    return {
        pid: {
            "ratio": d["ratio"],
            "acute_km": round(d["acute"] / 1000, 1),
            "chronic_week_km": round(d["chronic_week"] / 1000, 1),
            "last": d["last"],
        }
        for pid, d in data.items()
    }


def _readiness(wellness, acwr, status) -> int | None:
    """Composite 0–100: wellness, discounted when ACWR leaves the 0.8–1.3
    sweet spot and by availability status. None when there's no signal at
    all (no wellness)."""
    if wellness is None:
        return None
    base = float(wellness)
    if acwr is not None:
        if acwr > 1.5 or acwr < 0.7:
            base *= 0.85
        elif acwr > 1.3 or acwr < 0.8:
            base *= 0.93
    base *= _STATUS_FACTOR.get(status, 1.0)
    return max(0, min(100, round(base)))


# ─── Helpers ──────────────────────────────────────────────────────────


def _score_tone(score_100: float) -> str:
    if score_100 >= 75:
        return "ok"
    if score_100 >= 60:
        return "warn"
    return "crit"


def _initials(p) -> str:
    return ((p.first_name or " ")[0] + (p.last_name or " ")[0]).upper()
