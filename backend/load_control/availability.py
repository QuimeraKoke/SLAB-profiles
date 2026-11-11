"""Kinesia y lesiones of a microcycle — "¿Quién está en readaptación o clínica?"
(question 5 of the club's brief): the players NOT available, since when and how
long until they are back; then the season's injury history. "Una lista corta
con un color por estado y la fecha estimada de retorno. Sin informes largos."

The per-player injury card is the Daily's (`api.daily_report._lesionado` over
`_open_episodes`), so a player reads the same in the morning meeting and here.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from api.daily_report import _STAGE_RANK, _STATUS_LABEL, _lesionado, _open_episodes, _to_date
from core.models import Player
from exams.models import Episode, ExamResult
from load_control.week import days_of
from load_control.models import Microcycle
from load_control.wellness import _name, team_players

STATUS_ORDER = [Player.STATUS_INJURED, Player.STATUS_RECOVERY,
                Player.STATUS_REINTEGRATION, Player.STATUS_AVAILABLE]


def availability(mc: Microcycle, *, day: date | None = None) -> dict:
    """Status counts and the unavailable list as of `day` (default: today, or
    the microcycle's last day if it is over), plus the season's history."""
    days = [d.date for d in days_of(mc)]
    if day is not None and day not in days:
        raise ValueError("El día no pertenece al período seleccionado.")
    target = day or min(timezone.localdate(), mc.end_date)
    players = team_players(mc)

    counts = {s: 0 for s in STATUS_ORDER}
    for p in players.values():
        counts[p.status if p.status in counts else Player.STATUS_AVAILABLE] += 1

    out_ids = {pid for pid, p in players.items() if p.status != Player.STATUS_AVAILABLE}
    episodes = _open_episodes(out_ids)
    unavailable = [_lesionado(players[pid], episodes.get(pid), None, None, [], [], None, target)
                   for pid in out_ids]
    unavailable.sort(key=lambda r: (
        _STAGE_RANK.get(r["status"], 9),
        (r["episode"] or {}).get("days_to_return") if (r["episode"] or {}).get("days_to_return") is not None else 9999,
        r["name"]))

    history = []
    closed = (Episode.objects.filter(player_id__in=list(players), status=Episode.STATUS_CLOSED,
                                     template__slug="lesiones", started_at__year__gte=mc.season - 1)
              .select_related("template").order_by("-started_at"))
    latest: dict = {}
    for eid, data in (ExamResult.objects.filter(episode__in=closed).order_by("episode_id", "-recorded_at")
                      .values_list("episode_id", "result_data")):
        latest.setdefault(eid, data or {})
    for e in closed:
        if timezone.localtime(e.started_at).year != mc.season:
            # The season's injuries: started this year (last year only to keep
            # the query bounded around New Year).
            continue
        data = latest.get(e.id, {})
        started = _to_date(data.get("diagnosed_at")) or timezone.localtime(e.started_at).date()
        back_dt = e.available_at or e.ended_at
        back = timezone.localtime(back_dt).date() if back_dt else None
        history.append({
            "episode_id": str(e.id), "player_id": str(e.player_id), "name": _name(players[e.player_id]),
            "title": e.title or e.template.name, "body_part": data.get("body_part") or None,
            "severity": data.get("severity") or None,
            "started": started.isoformat(), "returned": back.isoformat() if back else None,
            "days_out": (back - started).days if back else None,
        })

    return {
        "date": target.isoformat(),
        "counts": [{"status": s, "label": _STATUS_LABEL.get(s, s), "n": counts[s]} for s in STATUS_ORDER],
        "players": len(players),
        "unavailable": unavailable,
        "history": history,
    }
