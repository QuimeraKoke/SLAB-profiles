"""Disponibilidad — "¿Cómo llega cada jugador a entrenar hoy?"

The staff's morning question before a session: not WHO trains (the coach
decides that, and at what intensity) but what each player brings to the day,
side by side:

* Estado      his medical status and open injury (`availability`, the Daily's card).
* Check-in    today's answer: wellness /25, the low items, pain zones,
              illness (`wellness.wellness` for the day).
* Partido     the last match before the day: minutes and how hard it hit
              him (jump drop, `fatigue.fatigue`), and whether he recovered.
* Carga       the week so far against the plan (`evaluation.evaluate`, the
              Carga GPS tab): each metric's real vs his position's target,
              with the club's bands — who strays from the plan beyond the
              range. An unplanned week has no target, so no reading.

Nothing is computed here that a tab or the roster does not already compute,
with the club's own bands, so a player reads the same everywhere. No verdict
column, by design.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from api.daily_report import _STATUS_LABEL, _lesionado, _open_episodes
from core.models import Player
from load_control.evaluation import evaluate
from load_control.fatigue import fatigue
from load_control.models import LoadControlConfig, Microcycle
from load_control.wellness import ITEMS, _name, _position, team_players, wellness
from load_control.week import days_of

_ITEM_LABEL = {i["key"]: i["label"] for i in ITEMS}
def day_status(mc: Microcycle, *, day: date | None = None) -> dict:
    days = [d.date for d in days_of(mc)]
    if day is not None and day not in days:
        raise ValueError("El día no pertenece al período seleccionado.")
    target = day or min(timezone.localdate(), mc.end_date)
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    roster = team_players(mc)

    # ── Check-in of the day ───────────────────────────────────────────────
    wl = wellness(mc, day=target)
    answers = {r["player_id"]: r for r in wl["rows"]}
    low = wl["low"]

    # ── Last match before the day ─────────────────────────────────────────
    fa = fatigue(mc, day=target)
    hits = {r["player_id"]: r for r in fa["rows"]}

    # This week's squad: who answered or trained this week (the Check-in
    # tab's squad), plus whoever is out injured, plus whoever played the last
    # match. Not the whole roster: SUB-20 lists 63 active players.
    squad_ids = ({w["player_id"] for w in wl["no_checkin"]} | set(answers) | set(hits)
                 | {str(pid) for pid, p in roster.items() if p.status != Player.STATUS_AVAILABLE})
    players = {pid: p for pid, p in roster.items() if str(pid) in squad_ids}

    # ── Load: the week so far vs the plan ─────────────────────────────────
    ev = evaluate(mc)
    planned = ev["provenance"].get("planned", True)
    metric_meta = {m["key"]: m for m in ev["metrics"]}
    loads = {}
    for p in ev["players"] if planned else []:
        cells = [{"key": k, "label": metric_meta[k]["label"], "short": metric_meta[k].get("short") or metric_meta[k]["label"],
                  "pct": c["pct"], "band": c["band"]}
                 for k, c in p["cells"].items() if c["pct"] is not None]
        if not cells:
            continue
        off = [c for c in cells if c["band"] != "ok"]
        loads[p["player_id"]] = {
            "metrics": cells, "off": off, "days": p["days"], "days_planned": p["days_planned"],
            "band": "grave" if any(c["band"] == "grave" for c in off) else "leve" if off else "ok",
            "over": any(c["pct"] > 0 for c in off), "under": any(c["pct"] < 0 for c in off),
        }

    # ── Status + open injury ──────────────────────────────────────────────
    out_ids = {pid for pid, p in players.items() if p.status != Player.STATUS_AVAILABLE}
    episodes = _open_episodes(out_ids)

    rows = []
    for pid, p in players.items():
        key = str(pid)
        status = p.status if p.status in _STATUS_LABEL else Player.STATUS_AVAILABLE
        injury = None
        if pid in out_ids:
            card = _lesionado(p, episodes.get(pid), None, None, [], [], None, target)
            ep = card["episode"] or {}
            injury = {k: ep.get(k) for k in ("title", "stage_label", "body_part", "days_out", "expected_return")} if ep else None

        a = answers.get(key)
        checkin = None
        if a and a["checkin"]:
            lows = [{"key": k, "label": _ITEM_LABEL[k], "value": v}
                    for k, v in a["scores"].items() if v is not None and v <= low]
            checkin = {
                "total": a["total_bienestar"], "lows": lows, "pain": a["pain"], "symptoms": a["symptoms"],
                "band": "grave" if a["pain"] else "leve" if (lows or a["symptoms"]) else "ok",
            }

        h = hits.get(key)
        match = None
        if h:
            match = {"minutes": h["minutes"], "golpe_pct": h["golpe_pct"], "golpe_band": h["golpe_band"],
                     "llega_pct": h["llega_pct"], "llega_band": h["llega_band"]}

        load = loads.get(key)
        signals = sum([
            bool(checkin and checkin["band"] != "ok"),
            bool(match and (match["golpe_band"] == "grave" or match["llega_band"] == "grave")),
            bool(load and load["off"]),
        ])
        rows.append({
            "player_id": key, "name": _name(p), "position": _position(p),
            "status": status, "status_label": _STATUS_LABEL.get(status, status), "injury": injury,
            "checkin": checkin, "match": match, "load": load, "signals": signals,
        })

    # Available first; within them, the one with the most to look at first.
    rows.sort(key=lambda r: (r["status"] != Player.STATUS_AVAILABLE, -r["signals"], r["name"]))
    available = [r for r in rows if r["status"] == Player.STATUS_AVAILABLE]

    counts = {
        "players": len(rows),
        "available": len(available),
        "pain": sum(1 for r in available if r["checkin"] and r["checkin"]["pain"]),
        "low": sum(1 for r in available if r["checkin"] and r["checkin"]["lows"]),
        "symptoms": sum(1 for r in available if r["checkin"] and r["checkin"]["symptoms"]),
        "no_checkin": sum(1 for r in available if not r["checkin"]),
        "hit": sum(1 for r in available if r["match"] and (r["match"]["golpe_band"] == "grave"
                                                           or r["match"]["llega_band"] == "grave")),
        "load_over": sum(1 for r in available if r["load"] and r["load"]["over"]),
        "load_under": sum(1 for r in available if r["load"] and r["load"]["under"]),
    }
    alert = cfg["rsi_alert"]
    return {
        "day": target.isoformat(),
        "match": fa["match"],
        "next_match": fa["next_match"],
        "counts": counts,
        "rows": rows,
        "rules": {
            "wellness_low": low,
            "jump": {"ok_from": alert["ok_from"], "grave_at": alert["grave_at"]},
            "load": {"planned": planned, "band_ok": cfg["band_ok_pct"], "band_mild": cfg["band_mild_pct"],
                     "days": len(ev["days"])},
        },
    }
