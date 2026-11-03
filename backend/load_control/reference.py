"""The match reference a microcycle's targets are a % of (PLAN_CONTROL_CARGA.md §4.0).

    reference[group][metric] = mean of `metric` over the team's MATCH GPS rows
                               (`gps_partido`) of the last `ref_window_days`
                               before the microcycle starts, counting only
                               rows with more than `ref_min_minutes` of GPS
                               (`tot_dur`) and, by default, official matches.

Per POSITION GROUP, as the staff works. A group with no qualifying row in the
window (two centre-backs rarely both finish a match) falls back to the whole
team's mean, and says so (`fallback: true`) — the "datos usados" footer shows
it. Different from `dashboards.player_state.match_load_refs`, which is
per-PLAYER and takes the MAX: same 75-minute cut, different question.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from dashboards.team_scope import season_rows
from exams.models import ExamResult
from load_control.defaults import GroupResolver

SLUG_MATCH = "gps_partido"
TEAM = "team"


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def team_match_rows(club, bracket, start: date, end: date) -> Q:
    """The team's match rows in [start, end): one `season_rows` per calendar
    year the window touches (a January window reaches December)."""
    q = Q()
    for year in range(start.year, end.year + 1):
        q |= season_rows(club.id, year, bracket)
    return q & Q(template__slug=SLUG_MATCH,
                 recorded_at__date__gte=start, recorded_at__date__lt=end)


def compute_reference(*, club, bracket, anchor: date, cfg: dict) -> dict:
    """The reference as of `anchor` (exclusive). JSON-ready."""
    start = anchor - timedelta(days=cfg["ref_window_days"])
    metrics = [m["key"] for m in cfg["metrics"]]
    resolver = GroupResolver(cfg)
    min_minutes = float(cfg["ref_min_minutes"])

    rows = (ExamResult.objects
            .filter(team_match_rows(club, bracket, start, anchor))
            .values_list("player_id", "recorded_at", "result_data", "player__position__name"))

    sums: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    players: dict[str, set] = defaultdict(set)
    matches: dict[str, set] = defaultdict(set)
    skipped = {"short": 0, "friendly": 0, "no_group": 0, "excluded_group": 0}
    for player_id, recorded_at, data, position_name in rows:
        data = data or {}
        if (_num(data.get("tot_dur")) or 0.0) <= min_minutes:
            skipped["short"] += 1
            continue
        if cfg["ref_official_only"] and data.get("match_type") == "friendly":
            skipped["friendly"] += 1
            continue
        group = resolver.group(data, position_name)
        if group is None:
            skipped["no_group"] += 1
            continue
        if group in resolver.excluded:
            skipped["excluded_group"] += 1
            continue
        day = timezone.localtime(recorded_at).date()
        for bucket in (group, TEAM):
            players[bucket].add(str(player_id))
            matches[bucket].add(day.isoformat())
            for m in metrics:
                v = _num(data.get(m))
                if v is not None:
                    sums[bucket][m].append(v)

    def summary(bucket: str) -> dict:
        out = {m: {"value": round(sum(v) / len(v), 1), "n_rows": len(v)}
               for m in metrics if (v := sums[bucket].get(m))}
        out.update(n_players=len(players[bucket]), n_matches=len(matches[bucket]))
        return out

    team = summary(TEAM)
    groups = {}
    for code in resolver.active_codes:
        if len(players.get(code, ())) >= max(1, int(cfg["ref_min_players"])):
            groups[code] = {**summary(code), "fallback": False}
        else:
            # Keep the group's own sample size visible: "1 jugador → equipo".
            groups[code] = {**team, "fallback": True,
                            "own_players": len(players.get(code, ()))}
    return {
        "window": {"start": start.isoformat(), "end": anchor.isoformat()},
        "params": {"ref_window_days": cfg["ref_window_days"],
                   "ref_min_minutes": cfg["ref_min_minutes"],
                   "ref_official_only": cfg["ref_official_only"],
                   "ref_min_players": cfg["ref_min_players"],
                   "metrics": metrics},
        "team": team,
        "groups": groups,
        "skipped": skipped,
    }


def day_targets(microcycle, day) -> dict[str, dict[str, float | None]]:
    """{group: {metric: target}} for one planned day, from the frozen
    reference. A match day is 100% of it; a rest day, or a metric the staff
    left blank, has no target (None) — "sin objetivo", never zero."""
    groups = (microcycle.ref_snapshot or {}).get("groups") or {}
    metrics = (microcycle.ref_snapshot or {}).get("params", {}).get("metrics") or []
    out: dict[str, dict[str, float | None]] = {}
    for code, ref in groups.items():
        row: dict[str, float | None] = {}
        for m in metrics:
            base = (ref.get(m) or {}).get("value")
            if day.is_match:
                pct = 100.0
            else:
                pct = _num((day.targets_pct or {}).get(m))
            row[m] = round(base * pct / 100.0, 1) if base is not None and pct is not None else None
        out[code] = row
    return out
