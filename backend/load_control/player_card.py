"""Jugador — "¿Cómo viene esta persona en todo?" (question 7 of the club's
brief): one player in the selected week, every panel at once.

Nothing is computed here that a tab does not already compute: each section
is the tab's own service filtered to him, so a number reads the same in his
card and in the squad view (Carga GPS = `evaluation.evaluate`, check-in/out =
`wellness.wellness`, fatiga = `fatigue.fatigue`, minutos = `participation`,
estado = `availability`'s injury card, evaluaciones = the Centro de mando
grid, composición = `composition`).
"""
from __future__ import annotations

from load_control.week import days_of
from load_control.availability import availability
from load_control.composition import composition
from load_control.evaluation import evaluate
from load_control.fatigue import fatigue
from load_control.models import Microcycle, MicrocycleDay
from load_control.participation import participation
from load_control.wellness import _name, team_players, wellness


def roster(mc: Microcycle) -> list[dict]:
    """Who can be picked: the week's team, by name."""
    return sorted(({"player_id": str(pid), "name": _name(p)} for pid, p in team_players(mc).items()),
                  key=lambda r: r["name"])


def _pick(rows: list[dict], pid: str) -> dict | None:
    return next((r for r in rows if r.get("player_id") == pid), None)


def player_card(mc: Microcycle, player_id) -> dict:
    players = team_players(mc)
    player = next((p for k, p in players.items() if str(k) == str(player_id)), None)
    if player is None:
        raise ValueError("El jugador no es del equipo de esta semana.")
    pid = str(player.id)

    # Carga GPS — each planned day, then the week so far (same as the tab).
    load_days = []
    for d in days_of(mc):
        if d.kind == MicrocycleDay.KIND_REST:
            load_days.append({"date": d.date.isoformat(), "md_label": d.md_label, "kind": d.kind, "row": None})
            continue
        ev = evaluate(mc, day=d.date)
        load_days.append({"date": d.date.isoformat(), "md_label": d.md_label, "kind": d.kind,
                          "row": _pick(ev["players"], pid)})
    acc = evaluate(mc)
    load = {"metrics": acc["metrics"], "days": load_days, "accumulated": _pick(acc["players"], pid)}

    # Check-in / out — his answers each day of the week. A player with no GPS
    # and no answer this week is not in the tab's squad: nothing to show.
    try:
        w = wellness(mc, player_id=pid)
        well = {"items": w["items"], "low": w["low"], "days": w["answers"]}
    except ValueError:
        well = {"items": [], "low": None, "days": []}

    # Fatiga post-partido — his line of the latest match, and his season.
    fa = fatigue(mc, player_id=pid)
    fat = {"match": fa["match"], "next_match": fa["next_match"], "row": _pick(fa["rows"], pid),
           "trend": fa["trend"], "params": fa["params"]}

    # Minutos y entrenamientos — the week and the season.
    week, season = participation(mc), participation(mc, scope="season")
    minutes = {"week": _pick(week["rows"], pid) | {"sessions": week["sessions"], "matches": week["matches"]}
               if _pick(week["rows"], pid) else {"sessions": week["sessions"], "matches": week["matches"]},
               "season": (_pick(season["rows"], pid) or {}) | {"sessions": season["sessions"],
                                                                 "match_count": len(season["matches"])}}

    # Estado — the Kinesia tab's card when he is not available.
    av = availability(mc)
    status = {"status": player.status, "card": _pick(av["unavailable"], pid),
              "history": [h for h in av["history"] if h["player_id"] == pid]}

    # Evaluaciones — his row of the category's grid (the Centro de mando's).
    from api.evaluation_grid import build_evaluation_grid
    grid = build_evaluation_grid(player.category) if player.category_id else {"groups": [], "rows": []}
    evals = {"groups": grid["groups"], "row": _pick(grid["rows"], pid), "legend": grid.get("legend", [])}

    # Composición corporal.
    comp = composition(player.category, player_id=pid) if player.category_id else None

    return {
        "player": {"player_id": pid, "name": _name(player),
                   "position": player.position.name if player.position_id else "",
                   "category": player.category.name if player.category_id else "",
                   "age": player.age if hasattr(player, "age") else None,
                   "photo_url": getattr(player, "photo_src", None), "status": player.status},
        "load": load, "wellness": well, "fatigue": fat, "minutes": minutes, "status": status,
        "evaluations": evals,
        "composition": ({"metrics": comp["metrics"], "player": comp["player"], "mean": comp["mean"]}
                        if comp else None),
    }
