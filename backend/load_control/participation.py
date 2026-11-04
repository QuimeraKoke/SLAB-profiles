"""Minutos y asistencia — "¿Cuánto jugó y a cuántas sesiones fue?" (question 6).
It explains why someone carries little load: few minutes, or few sessions.

* Minutes: the COMET match sheets (`ficha_partido`) of the TEAM's matches in
  the period — a SUB-20 player who also plays for the U18 or the first team
  has sheets there too, and those are another team's minutes. % = minutes over
  `MATCH_MINUTES` per team match played.
* Entrenamientos (never "asistencia" — in football that is the pass for a
  goal): the team's sessions are the days with team training GPS for at least
  `session_min_players` players (a lone recovery run is not a team session;
  official matches and friendlies are not sessions). A player trained that day
  if any signal says so: training GPS from any source, or a check-in/out.
* Minutes: COMET sheet when the match has one, else the match's GPS duration
  (capped at 90) — the club's own dashboard reads minutes from GPS.
* Traffic light only where there is a problem: attendance under
  `attendance_low_pct`. OFF by default (None): GPS-based attendance runs ~60–70 %
  for most of U20's season (not everyone wears a unit every session), so any
  invented cut would paint the whole squad red. The PF sets it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from api.daily_report import _STATUS_LABEL
from core.localtime import local_date
from dashboards.team_scope import season_rows
from exams.models import ExamResult
from load_control.matches import _fixture_days
from load_control.models import LoadControlConfig, Microcycle
from load_control.wellness import _name, team_players

MATCH_MINUTES = 90
FORMS = ("checkin_formativo", "checkout_formativo")
MATCH_CODES = {"MD", "MD OFICIAL", "MD AMISTOSO"}


def _is_match_row(data: dict) -> bool:
    """A GPS row of an official match or a friendly (the club's code, or a
    session the ingest labelled as a friendly)."""
    return (str(data.get("origen_codigo") or "").upper() in MATCH_CODES
            or data.get("tipo_sesion") == "amistoso")


def _rival(title: str, club_name: str) -> str:
    """"UNIVERSIDAD DE CHILE vs COBRELOA" → "COBRELOA" (the side that is not us)."""
    from load_control.defaults import norm

    sides = [x.strip() for x in (title or "").split(" vs ")]
    others = [x for x in sides if norm(club_name) not in norm(x)]
    return others[0] if len(sides) == 2 and others else (title or "")


def participation(mc: Microcycle, *, scope: str = "microcycle") -> dict:
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    if scope == "season":
        start, end = date(mc.season, 1, 1), min(timezone.localdate(), date(mc.season, 12, 31))
    elif scope == "microcycle":
        start, end = mc.start_date, mc.end_date
    else:
        raise ValueError("Período desconocido.")
    players = team_players(mc)

    # The team's match days: what the club's GPS codes as a match (official or
    # friendly), plus fixtures COMET has sheets for. Minutes come from the
    # COMET sheet when there is one (the official record); otherwise from the
    # GPS duration of the match — what the club's own dashboard uses.
    fixtures = _fixture_days(mc.club, mc.season, mc.bracket, start, end)
    sheets = defaultdict(dict)          # event_id → {player_id: data}
    for event_id, pid, data in ExamResult.objects.filter(
        template__slug="ficha_partido", event_id__in=[e.id for _, e in fixtures],
    ).values_list("event_id", "player_id", "result_data"):
        sheets[event_id][pid] = data or {}
    played = {d: e for d, e in fixtures if sheets.get(e.id)}
    gps_minutes = defaultdict(dict)     # day → {player_id: minutes}
    gps_rival = {}
    for pid, rec, data in ExamResult.objects.filter(
        season_rows(mc.club_id, mc.season, mc.bracket), template__slug="gps_partido",
        recorded_at__date__gte=start, recorded_at__date__lte=end,
    ).values_list("player_id", "recorded_at", "result_data"):
        d = timezone.localtime(rec).date()
        dur = (data or {}).get("tot_dur")
        if isinstance(dur, (int, float)):
            gps_minutes[d][pid] = gps_minutes[d].get(pid, 0) + dur
        gps_rival.setdefault(d, (data or {}).get("opponent"))
    match_days = sorted(set(played) | set(gps_minutes))

    # Team sessions: days with team TRAINING GPS for enough players. "Anything
    # that is not an official match or a friendly is training" (the club,
    # 2026-11-03): match-coded session rows are match-day work, not a session.
    per_day = defaultdict(set)
    for pid, rec, data in ExamResult.objects.filter(
        season_rows(mc.club_id, mc.season, mc.bracket), template__slug="gps_sesion",
        recorded_at__date__gte=start, recorded_at__date__lte=end,
    ).values_list("player_id", "recorded_at", "result_data"):
        if not _is_match_row(data or {}):
            per_day[timezone.localtime(rec).date()].add(pid)
    min_players = int(cfg["session_min_players"])
    sessions = sorted(d for d, ps in per_day.items() if len(ps) >= min_players)
    session_set = set(sessions)

    # He trained that day if ANY signal says so: training GPS from any source
    # (his team's tab, SPARRING, the first team's Catapult…), or he answered
    # the check-in or the check-out. GPS alone undercounts — not everyone wears
    # a unit every session (U20: one player "missed" 104 sessions and answered
    # the check-in on 77 of them).
    by_gps, by_form = defaultdict(set), defaultdict(set)
    for pid, rec, data in ExamResult.objects.filter(
        template__slug="gps_sesion", player_id__in=list(players),
        recorded_at__date__gte=start, recorded_at__date__lte=end,
    ).values_list("player_id", "recorded_at", "result_data"):
        d = timezone.localtime(rec).date()
        if d in session_set and not _is_match_row(data or {}):
            by_gps[pid].add(d)
    for pid, rec in ExamResult.objects.filter(
        template__slug__in=FORMS, player_id__in=list(players),
        recorded_at__date__gte=start, recorded_at__date__lte=end + timedelta(days=1),
    ).values_list("player_id", "recorded_at"):
        d = local_date(rec)
        if d in session_set:
            by_form[pid].add(d)

    low = cfg["attendance_low_pct"]
    rows = []
    for pid, p in players.items():
        per_match = []
        for d in match_days:
            e = played.get(d)
            if e is not None:
                sheet = sheets[e.id].get(pid)
                per_match.append(None if sheet is None else {
                    "minutes": sheet.get("minutos") or 0, "starter": bool(sheet.get("titular"))})
            else:
                m = gps_minutes[d].get(pid)
                per_match.append(None if m is None else {
                    "minutes": round(min(m, MATCH_MINUTES)), "starter": None})
        minutes = sum(m["minutes"] for m in per_match if m)
        trained = by_gps[pid] | by_form[pid]
        attended = len(trained)
        att_pct = round(attended / len(sessions) * 100) if sessions else None
        if not minutes and not attended and p.status == "available":
            continue  # not in this team's football this period at all
        rows.append({
            "player_id": str(pid), "name": _name(p), "status": p.status,
            "status_label": _STATUS_LABEL.get(p.status, p.status),
            "matches": per_match,
            "minutes": minutes,
            "minutes_pct": round(minutes / (len(match_days) * MATCH_MINUTES) * 100) if match_days else None,
            "called_up": sum(1 for m in per_match if m), "starts": sum(1 for m in per_match if m and m["starter"]),
            "sessions_attended": attended, "attendance_pct": att_pct,
            # Which signal counted him: GPS, or only the form (no GPS that day).
            "sessions_gps": len(by_gps[pid]), "sessions_form_only": len(by_form[pid] - by_gps[pid]),
            "attendance_low": low is not None and att_pct is not None and att_pct < float(low),
        })
    rows.sort(key=lambda r: (-r["minutes"], -(r["attendance_pct"] or 0), r["name"]))
    return {
        "scope": scope, "start": start.isoformat(), "end": end.isoformat(),
        "match_minutes": MATCH_MINUTES,
        "matches": [{"date": d.isoformat(),
                     "event_id": str(played[d].id) if d in played else None,
                     "source": "comet" if d in played else "gps",
                     "opponent": ((str(played[d].opponent_team) if played[d].opponent_team_id
                                   else _rival(played[d].title, mc.club.name))
                                  if d in played else gps_rival.get(d))}
                    for d in match_days],
        "sessions": len(sessions), "session_min_players": min_players,
        "attendance_low_pct": low,
        "rows": rows,
    }
