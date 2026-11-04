"""Fatiga post-partido — what the coach plans the week with (the staff,
2026-11-03): "¿qué tan duro le pegó el último partido?" and "¿cómo llega al
que viene?".

Three jumps in a row per player, each a `control_salto` result (one per
measured match: PRE the day before, POST the day after —
`exams.formativo_saltos_ingest`):

    PRE (MD-1)  ──golpe──▶  POST (MD+1)  ──recuperación──▶  next PRE (MD-1)

* golpe  = POST vs PRE of the match.
* llega  = next match's PRE vs this match's PRE — back to where he was
           before the match, or not.
Both use the club's own traffic light (`rsi_alert`: ≥ 0 green, 0…−5 % amber,
≤ −5 % red) — the one their sheets paint.

Context, not verdicts: minutes played (COMET sheet, else match GPS), his
basal (mean of his last `jump_baseline_n` PRE, the MD+2 screen's rule) so a
PRE that was already low shows, and the season drift (current vs
season-start basal). Values only compare within one method: R-CMJ RSI and
CMJ RSI mod are different scales.

Matches are THIS team's sheet's (a U18 player in the U20 pool brings his U18
jumps: they count for his basal, not as a U20 match).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from django.utils import timezone

from exams.models import ExamResult
from load_control.models import LoadControlConfig, Microcycle
from load_control.wellness import _name, team_players

SLUG = "control_salto"
MATCH_MINUTES = 90
RECENT_MATCHES = 4


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pct(a, b) -> float | None:
    return round((a - b) / b * 100, 1) if a is not None and b else None


def delta_band(pct: float | None, cfg: dict) -> str | None:
    if pct is None:
        return None
    alert = cfg["rsi_alert"]
    return "ok" if pct >= alert["ok_from"] else "grave" if pct <= alert["grave_at"] else "leve"


def level_band(value: float | None, method: str, cfg: dict) -> str | None:
    """The club's RSI levels — defined for R-CMJ rebote / contacto only."""
    if value is None or method != "rebote / contacto":
        return None
    for b in cfg["rsi_levels"]:
        if b.get("max") is None or value < b["max"]:
            return b["label"]
    return None


def _history(players: dict, season: int, key: str) -> dict:
    """{player_id: [measurement…]} in date order, the season's jumps."""
    out = defaultdict(list)
    for r in (ExamResult.objects.filter(template__slug=SLUG, player_id__in=list(players),
                                        recorded_at__year=season)
              .order_by("recorded_at").values("player_id", "recorded_at", "event_id", "result_data")):
        d = r["result_data"] or {}
        out[r["player_id"]].append({
            "date": timezone.localtime(r["recorded_at"]).date(),
            "method": d.get("rsi_metodo"),
            "pre": _num(d.get(f"rsi_pre_{key}")), "post": _num(d.get(f"rsi_post_{key}")),
            "rival": d.get("rival"), "source": d.get("fecha_fuente"), "tab": d.get("hoja"),
            "team": d.get("equipo_hoja"),
            "event_id": str(r["event_id"]) if r["event_id"] else None,
        })
    return out


def _basal(history: list, before: date, method: str, n: int) -> tuple[float | None, int]:
    pres = [m["pre"] for m in history if m["date"] < before and m["method"] == method and m["pre"] is not None]
    last = pres[-n:]
    return (round(sum(last) / len(last), 3), len(last)) if last else (None, 0)


def _season_basal(history: list, method: str, n: int) -> tuple[float | None, int]:
    pres = [m["pre"] for m in history if m["method"] == method and m["pre"] is not None]
    first = pres[:n]
    return (round(sum(first) / len(first), 3), len(first)) if first else (None, 0)


def _minutes(match_date: date, event_ids: set, player_ids) -> dict:
    """{player_id: minutes} — the COMET sheet when the match has one, else the
    match GPS duration capped at 90 (what the club's dashboard uses)."""
    out = {}
    if event_ids:
        for pid, data in ExamResult.objects.filter(
            template__slug="ficha_partido", event_id__in=event_ids, player_id__in=list(player_ids),
        ).values_list("player_id", "result_data"):
            out[pid] = (data or {}).get("minutos") or 0
    if not out:
        gps = defaultdict(float)
        for pid, data in ExamResult.objects.filter(
            template__slug="gps_partido", player_id__in=list(player_ids), recorded_at__date=match_date,
        ).values_list("player_id", "result_data"):
            dur = (data or {}).get("tot_dur")
            if isinstance(dur, (int, float)):
                gps[pid] += dur
        out = {pid: round(min(v, MATCH_MINUTES)) for pid, v in gps.items()}
    return out


def _match_info(history: dict, d: date | None, own) -> dict | None:
    if d is None:
        return None
    m = next((m for ms in history.values() for m in ms if m["date"] == d and own(m)), None)
    return {"date": d.isoformat(), "rival": m["rival"], "source": m["source"], "tab": m["tab"],
            "event_id": m["event_id"]} if m else None


def fatigue(mc: Microcycle, *, match_date: date | None = None, player_id=None) -> dict:
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    n = int(cfg["jump_baseline_n"])
    key = "mean" if cfg["attempt_value"] == "mean" else "best"
    players = team_players(mc)
    history = _history(players, mc.season, key)
    label = "U" + mc.bracket.name.split()[-1]

    def own(m):
        return m["team"] == label

    season_matches = sorted({m["date"] for ms in history.values() for m in ms if own(m)})
    if match_date is not None and match_date not in season_matches:
        raise ValueError("No hay saltos de ese partido.")
    # Default: the week's last measured match, else the last one before it —
    # "el último partido" as seen from this week.
    upto = [d for d in season_matches if d <= mc.end_date]
    target = match_date or (upto[-1] if upto else None)
    i = season_matches.index(target) if target else -1
    prev_m = season_matches[i - 1] if i > 0 else None
    next_m = season_matches[i + 1] if target and i + 1 < len(season_matches) else None

    rows = []
    if target is not None:
        anchors = {pid: next((x for x in ms if x["date"] == target and own(x)), None) for pid, ms in history.items()}
        anchors = {pid: m for pid, m in anchors.items() if m is not None}
        minutes = _minutes(target, {m["event_id"] for m in anchors.values() if m["event_id"]}, anchors)
        for pid, m in anchors.items():
            ms = history[pid]
            nxt = next((x for x in ms if x["date"] == next_m and own(x)), None) if next_m else None
            next_pre = nxt["pre"] if nxt and nxt["method"] == m["method"] else None
            basal, basal_n = _basal(ms, target, m["method"], n)
            start, start_n = _season_basal(ms, m["method"], n)
            current, _ = _basal(ms, date.max, m["method"], n)
            golpe = _pct(m["post"], m["pre"])
            llega = _pct(next_pre, m["pre"])
            drift = _pct(current, start) if start_n >= n and current is not None else None
            rows.append({
                "player_id": str(pid), "name": _name(players[pid]), "method": m["method"],
                "minutes": minutes.get(pid),
                "pre": m["pre"], "post": m["post"], "next_pre": next_pre,
                "golpe_pct": golpe, "golpe_band": delta_band(golpe, cfg),
                "llega_pct": llega, "llega_band": delta_band(llega, cfg),
                # Why there is no "llega" yet: the next match is not measured,
                # or he did not jump it (or jumped another test).
                "llega_state": ("measured" if next_pre is not None else "pending" if next_m is None
                                else "missing"),
                "pre_level": level_band(m["pre"], m["method"], cfg),
                "next_pre_level": level_band(next_pre, m["method"], cfg),
                "basal": basal, "basal_n": basal_n,
                "pre_vs_basal": _pct(m["pre"], basal),
                "season_drift_pct": drift, "season_drift_band": delta_band(drift, cfg),
                # His last RECENT_MATCHES matches up to this one, same method
                # (any sheet: a U18 match also loads him), for the sawtooth.
                "recent": [{"date": x["date"].isoformat(), "pre": x["pre"], "post": x["post"],
                            "golpe_band": delta_band(_pct(x["post"], x["pre"]), cfg)}
                           for x in [x for x in ms if x["date"] <= target and x["method"] == m["method"]][-RECENT_MATCHES:]],
            })
        # Who to look at first: arrives worst to the next match, then the
        # hardest hit, then whoever still has no next jump.
        rank = {"grave": 0, "leve": 1, None: 2, "ok": 3}
        rows.sort(key=lambda r: (rank[r["llega_band"]], rank[r["golpe_band"]],
                                 r["golpe_pct"] if r["golpe_pct"] is not None else 99, r["name"]))

    counts = {k: {"ok": 0, "leve": 0, "grave": 0} for k in ("golpe", "llega")}
    for r in rows:
        for k in counts:
            if r[f"{k}_band"]:
                counts[k][r[f"{k}_band"]] += 1

    trend = None
    pid_match = next((p for p in players if str(p) == str(player_id)), None) if player_id is not None else None
    if pid_match is not None and history.get(pid_match):
        ms = history[pid_match]
        method = ms[-1]["method"]
        trend = {"player_id": str(pid_match), "name": _name(players[pid_match]), "method": method,
                 "points": [{"date": m["date"].isoformat(), "pre": m["pre"], "post": m["post"],
                             "basal": _basal(ms, m["date"], method, n)[0], "rival": m["rival"]}
                            for m in ms if m["method"] == method]}

    return {
        "match": _match_info(history, target, own),
        "prev_match": _match_info(history, prev_m, own),
        "next_match": _match_info(history, next_m, own),
        "rows": rows,
        "summary": {"players": len(rows), "counts": counts,
                    "golpe_n": sum(1 for r in rows if r["golpe_pct"] is not None),
                    "llega_n": sum(1 for r in rows if r["llega_pct"] is not None)},
        "trend": trend,
        "params": {"baseline_n": n, "attempt_value": key, "rsi_alert": cfg["rsi_alert"]},
    }
