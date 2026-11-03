"""Plan vs real: each player's GPS against the microcycle's targets (§8.3).

    real    = the player's GPS that day: sessions + match + compensación, and
              sparring (on the SPARRING tab) when `include_sparring`
    target  = reference[group][metric] × the day's %   (match day = 100%)
    Δ%      = (real − target) / target × 100
    band    = |Δ| ≤ band_ok → "ok" · ≤ band_mild → "leve" · else "grave"

The group is the POSICIÓN the club wrote on the player's row THAT day (a
centre-back who played full-back counts as LAT), else his roster position.

"Sin dato ≠ cero" (the club's brief): a player with no GPS that day is listed
as such, never as −100%; a metric with no target is "sin objetivo".

Duplicates. When the club re-codes a row already imported (blank → NO MD,
session → MD OFICIAL) the ingest keeps both copies: in U20's 2026 data every
player-day with two rows (45) was an exact copy, 16 of them the 22-oct match.
Rows of one player-day with the same minutes and distance are therefore
counted once; a real double session differs and still adds up.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from django.db.models import Q
from django.utils import timezone

from dashboards.team_scope import season_rows
from exams.models import ExamResult
from load_control.defaults import GroupResolver
from load_control.models import LoadControlConfig, Microcycle, MicrocycleDay
from load_control.reference import compute_reference, day_targets

GPS_SLUGS = ("gps_sesion", "gps_partido")
SLUG_RANK = {"gps_partido": 0, "gps_sesion": 1}


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def band(pct: float | None, cfg: dict) -> str | None:
    if pct is None:
        return None
    a = abs(pct)
    return "ok" if a <= cfg["band_ok_pct"] else "leve" if a <= cfg["band_mild_pct"] else "grave"


def _player_name(p) -> str:
    return " ".join(x for x in (p.first_name, p.last_name) if x).strip() or str(p.pk)


def _rows(mc: Microcycle, start: date, end: date, include_sparring: bool):
    team_q = season_rows(mc.club_id, mc.season, mc.bracket)
    q = team_q
    if include_sparring:
        # A team player's sparring lives on the SPARRING tab, outside the team
        # sheet: take it for the players who appear in the team's own rows.
        team_players = ExamResult.objects.filter(
            team_q, template__slug__in=GPS_SLUGS,
            recorded_at__date__gte=start, recorded_at__date__lte=end,
        ).values("player_id")
        q = q | Q(result_data__origen_hoja="SPARRING", player_id__in=team_players,
                  player__category__club_id=mc.club_id)
    return (ExamResult.objects.filter(q, template__slug__in=GPS_SLUGS,
                                      recorded_at__date__gte=start, recorded_at__date__lte=end)
            .select_related("player__position", "template"))


def _collect(mc: Microcycle, start: date, end: date, include_sparring: bool, metrics, resolver):
    """{(player_id, date): {"player", "group", "real": {m: v}, "sparring": bool, ...}}"""
    by: dict[tuple, list] = defaultdict(list)
    for r in _rows(mc, start, end, include_sparring):
        by[(r.player_id, timezone.localtime(r.recorded_at).date())].append(r)
    out, dropped = {}, 0
    for key, rows in by.items():
        rows.sort(key=lambda r: SLUG_RANK.get(r.template.slug, 9))
        kept, seen = [], set()
        for r in rows:
            d = r.result_data or {}
            ident = (_num(d.get("tot_dur")), _num(d.get("tot_dist")))
            if ident in seen and ident != (None, None):
                dropped += 1
                continue
            seen.add(ident)
            kept.append(r)
        own = [r for r in kept if not (r.result_data or {}).get("es_sparring")] or kept
        first = own[0]
        group = resolver.group(first.result_data or {}, getattr(first.player.position, "name", None))
        real = {}
        for m in metrics:
            vals = [_num((r.result_data or {}).get(m)) for r in kept]
            vals = [v for v in vals if v is not None]
            real[m] = sum(vals) if vals else None
        out[key] = {
            "player": first.player, "group": group, "real": real,
            "minutes": sum(_num((r.result_data or {}).get("tot_dur")) or 0 for r in kept),
            "sparring": any((r.result_data or {}).get("es_sparring") for r in kept),
            "compensacion": any((r.result_data or {}).get("es_compensacion") for r in kept),
            "match": any(r.template.slug == "gps_partido" for r in kept),
        }
    return out, dropped


def evaluate(mc: Microcycle, *, day: date | None = None, include_sparring: bool | None = None,
             include_matches: bool = True) -> dict:
    """One day (`day`) or the microcycle so far (`day=None`, accumulated).

    Accumulated compares each player only over the days he has GPS for — the
    sum of his targets on THOSE days — and says how many of the planned days
    that is, so a player who missed two sessions reads "3 de 5 días", not
    "−40%"."""
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    include_sparring = cfg["include_sparring"] if include_sparring is None else include_sparring
    metrics = [m["key"] for m in cfg["metrics"]]
    resolver = GroupResolver(cfg)
    days = {d.date: d for d in mc.days.all()}
    if day is not None and day not in days:
        raise ValueError("El día no pertenece al microciclo.")

    def counted(d: MicrocycleDay) -> bool:
        if d.kind == MicrocycleDay.KIND_REST:
            return False
        return include_matches or not d.is_match

    today = timezone.localdate()
    window = [day] if day else [d for d, x in sorted(days.items()) if counted(x) and d <= today]
    start, end = (window[0], window[-1]) if window else (mc.start_date, mc.start_date)
    data, dropped = _collect(mc, start, end, include_sparring, metrics, resolver)
    # A draft is evaluated against the reference it WOULD freeze.
    holder = mc if mc.is_frozen else Microcycle(ref_snapshot=compute_reference(
        club=mc.club, bracket=mc.bracket, anchor=mc.start_date, cfg=cfg))
    targets = {d: day_targets(holder, days[d]) for d in window}

    players: dict = {}
    for (pid, d), row in data.items():
        if d not in targets:
            continue
        group = row["group"]
        if group is None or group in resolver.excluded:
            continue
        p = players.setdefault(pid, {
            "player_id": str(pid), "name": _player_name(row["player"]), "group": group,
            "real": {m: None for m in metrics}, "target": {m: None for m in metrics},
            "days": 0, "minutes": 0.0, "sparring": False, "compensacion": False,
        })
        p["days"] += 1
        p["minutes"] += row["minutes"]
        p["sparring"] |= row["sparring"]
        p["compensacion"] |= row["compensacion"]
        tg = targets[d].get(group) or {}
        for m in metrics:
            if row["real"][m] is not None:
                p["real"][m] = (p["real"][m] or 0) + row["real"][m]
            if tg.get(m) is not None:
                p["target"][m] = (p["target"][m] or 0) + tg[m]

    out_players, alerts = [], []
    for p in players.values():
        cells = {}
        for m in metrics:
            t, r = p["target"][m], p["real"][m]
            pct = round((r - t) / t * 100, 1) if t and r is not None else None
            cells[m] = {"target": None if t is None else round(t, 1),
                        "real": None if r is None else round(r, 1),
                        "pct": pct, "band": band(pct, cfg)}
            if cells[m]["band"] in ("leve", "grave"):
                alerts.append({"player_id": p["player_id"], "name": p["name"], "group": p["group"],
                               "metric": m, **cells[m], "diff": round(r - t, 1)})
        out_players.append({k: v for k, v in p.items() if k not in ("real", "target")} | {
            "cells": cells, "minutes": round(p["minutes"], 1),
            "days_planned": len(window)})
    out_players.sort(key=lambda x: -(x["cells"][metrics[0]]["real"] or 0))
    # Graves first, then by how far off; a tie by name, so the list never reshuffles.
    alerts.sort(key=lambda a: (0 if a["band"] == "grave" else 1, -abs(a["pct"]), a["name"]))

    summary = {}
    for m in metrics:
        both = [x["cells"][m] for x in out_players
                if x["cells"][m]["target"] is not None and x["cells"][m]["real"] is not None]
        counts = {"ok": 0, "leve": 0, "grave": 0}
        for c in both:
            counts[c["band"]] += 1
        if both:
            t = sum(c["target"] for c in both) / len(both)
            r = sum(c["real"] for c in both) / len(both)
            pct = round((r - t) / t * 100, 1) if t else None
        else:
            t = r = pct = None
        summary[m] = {"target": None if t is None else round(t, 1),
                      "real": None if r is None else round(r, 1),
                      "pct": pct, "band": band(pct, cfg), "counts": counts, "n": len(both)}

    return {
        "mode": "day" if day else "accumulated",
        "day": day.isoformat() if day else None,
        "days": [{"date": d.isoformat(), "md_label": days[d].md_label, "kind": days[d].kind}
                 for d in window],
        "metrics": cfg["metrics"],
        "bands": {"ok": cfg["band_ok_pct"], "mild": cfg["band_mild_pct"]},
        "summary": summary,
        "players": out_players,
        "alerts": alerts,
        "provenance": {
            "microcycle": mc.number, "include_sparring": include_sparring,
            "include_matches": include_matches,
            "players": len(out_players),
            "players_with_sparring": sum(1 for x in out_players if x["sparring"]),
            "duplicates_dropped": dropped,
            "reference_frozen": mc.is_frozen,
            "reference_window": (holder.ref_snapshot or {}).get("window"),
            "fallback_groups": sorted(c for c, g in ((holder.ref_snapshot or {}).get("groups") or {}).items()
                                      if g.get("fallback")),
        },
    }
