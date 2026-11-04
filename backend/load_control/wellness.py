"""Check-in / out of a microcycle — "¿Cómo llega el jugador, cómo se siente,
qué le molesta, cómo se va?" (question 4 of the club's brief).

Check-in (`checkin_formativo`, before training): sueño, fatiga, estrés, ánimo
and daño muscular, 1–5 where 5 is best; total bienestar = their sum (/25);
total muscular = fatiga + daño muscular (/10) — the two lines of the club's
chart. Check-out (`checkout_formativo`, after): duration, RPE and UA = min × RPE.

Days are LOCAL (`core.localtime`): a form is an instant, and a 07:04 answer in
Santiago is 10:04 UTC. A player who answered twice the same day counts once,
with his latest answer.

The team is the microcycle's: its cohorts' active players plus whoever appears
in the team's GPS that week (a call-up trains with the team and answers too).
"""
from __future__ import annotations

from datetime import date, timedelta

from core.localtime import local_date
from core.models import Player
from exams.models import ExamResult
from load_control.week import days_of
from load_control.models import LoadControlConfig, Microcycle
from load_control.planning import _gps_rows, team_of

CHECKIN = "checkin_formativo"
CHECKOUT = "checkout_formativo"
ITEMS = [
    {"key": "calidad_sueno", "label": "Sueño"},
    {"key": "nivel_fatiga", "label": "Fatiga"},
    {"key": "nivel_estres", "label": "Estrés"},
    {"key": "estado_animo", "label": "Ánimo"},
    {"key": "dano_muscular", "label": "Daño muscular"},
]
ITEM_KEYS = [i["key"] for i in ITEMS]
# What a player wrote about pain, in either form (a body zone: "Tobillo",
# "Rodilla Izq."). `sintomas` is NOT pain: players write illness there (fiebre,
# resfriado, jaqueca) — kept apart as SYMPTOMS so it never reads "Molestia: Fiebre".
PAIN_IN = ("dolor_muscular",)
SYMPTOMS = ("sintomas",)
PAIN_OUT = ("molestia_post", "molestia_isquiotibiales", "molestia_aductores",
            "molestia_cuadriceps", "molestia_gemelos", "observaciones")
_ONE_DAY = timedelta(days=1)  # a late-evening answer is already tomorrow in UTC
NO_PAIN = {"", "no", "ninguna", "ninguno", "nada", "sin molestias", "sin dolor", "-", "0"}


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pain(data: dict, keys) -> list[str]:
    out = []
    for k in keys:
        txt = str(data.get(k) or "").strip()
        if txt and txt.lower() not in NO_PAIN:
            out.append(txt)
    return out


def _mean(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _name(p: Player) -> str:
    return " ".join(x for x in (p.first_name, p.last_name) if x).strip()


def team_players(mc: Microcycle) -> dict:
    team = team_of(mc)
    players = {p.id: p for p in Player.objects.filter(
        category__in=team.categories(), is_active=True).select_related("position")}
    extra = set(_gps_rows(team, mc.start_date, mc.end_date).values_list("player_id", flat=True)) - set(players)
    players.update({p.id: p for p in Player.objects.filter(pk__in=extra).select_related("position")})
    return players


def _latest_by_player_day(slug: str, player_ids, start: date, end: date) -> dict:
    """{(player_id, local day): result_data} — the day's latest answer."""
    out: dict = {}
    for pid, rec, data in (ExamResult.objects
                           .filter(template__slug=slug, player_id__in=list(player_ids),
                                   recorded_at__date__gte=start, recorded_at__date__lte=end + _ONE_DAY)
                           .order_by("recorded_at")
                           .values_list("player_id", "recorded_at", "result_data")):
        d = local_date(rec)
        if start <= d <= end:
            out[(pid, d)] = data or {}
    return out


def _answer_row(pid, p, i: dict | None, o: dict | None) -> dict:
    """One player's check-in + check-out of a day, as the screen shows it."""
    i, o = i or {}, o or {}
    scores = {k: _num(i.get(k)) for k in ITEM_KEYS}
    total = (sum(scores.values()) if all(v is not None for v in scores.values()) else None)
    dur, rpe = _num(o.get("duracion_min")), _num(o.get("rpe"))
    row = {
        "player_id": str(pid), "name": _name(p), "checkin": bool(i), "checkout": bool(o),
        "scores": scores, "total_bienestar": total,
        "duracion_min": dur, "rpe": rpe, "ua": dur * rpe if dur is not None and rpe is not None else None,
        "peso": _num(i.get("peso")),
        "pain_in": _pain(i, PAIN_IN), "pain_out": _pain(o, PAIN_OUT),
    }
    # One list for the screen: what he wrote, once (the same zone often goes
    # in both forms).
    row["pain"] = list(dict.fromkeys(row["pain_in"] + row["pain_out"]))
    row["symptoms"] = _pain(i, SYMPTOMS)
    return row


def wellness(mc: Microcycle, *, day: date | None = None, player_id=None) -> dict:
    """The microcycle day by day (group, or one player) and, for `day`, who
    reported low wellness or pain, everyone's answers and who did not answer."""
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    low = cfg["wellness_low"]
    days = [d.date for d in days_of(mc)]
    if day is not None and day not in days:
        raise ValueError("El día no pertenece a la semana.")
    # This week's squad: of the team's players, those who trained (GPS) or
    # answered a form in the microcycle — not the whole roster (SUB-20 lists
    # 63 active players; ~22 trained), or "sin responder" means nothing.
    candidates = team_players(mc)
    ins = _latest_by_player_day(CHECKIN, candidates, mc.start_date, mc.end_date)
    outs = _latest_by_player_day(CHECKOUT, candidates, mc.start_date, mc.end_date)
    active = {pid for pid, _ in ins} | {pid for pid, _ in outs} | set(
        _gps_rows(team_of(mc), mc.start_date, mc.end_date).values_list("player_id", flat=True))
    players = {k: v for k, v in candidates.items() if k in active}
    if player_id is not None:
        players = {k: v for k, v in players.items() if str(k) == str(player_id)}
        if not players:
            raise ValueError("El jugador no es del equipo de esta semana.")
    ins = {k: v for k, v in ins.items() if k[0] in players}
    outs = {k: v for k, v in outs.items() if k[0] in players}

    series = []
    for d in days:
        day_in = [data for (pid, dd), data in ins.items() if dd == d]
        day_out = [data for (pid, dd), data in outs.items() if dd == d]
        row = {"date": d.isoformat(), "checkin_n": len(day_in), "checkout_n": len(day_out),
               "players": len(players)}
        for k in ITEM_KEYS:
            row[k] = _mean(_num(x.get(k)) for x in day_in)
        totals = [sum(_num(x.get(k)) for k in ITEM_KEYS) for x in day_in
                  if all(_num(x.get(k)) is not None for k in ITEM_KEYS)]
        row["total_bienestar"] = _mean(totals)
        musc = [_num(x.get("nivel_fatiga")) + _num(x.get("dano_muscular")) for x in day_in
                if _num(x.get("nivel_fatiga")) is not None and _num(x.get("dano_muscular")) is not None]
        row["total_muscular"] = _mean(musc)
        row["duracion_min"] = _mean(_num(x.get("duracion_min")) for x in day_out)
        row["rpe"] = _mean(_num(x.get("rpe")) for x in day_out)
        ua = [_num(x.get("duracion_min")) * _num(x.get("rpe")) for x in day_out
              if _num(x.get("duracion_min")) is not None and _num(x.get("rpe")) is not None]
        row["ua"] = _mean(ua)
        series.append(row)

    out = {"items": ITEMS, "low": low, "series": series, "players": len(players),
           "day": day.isoformat() if day else None}
    if day is None:
        if player_id is not None:
            # One player's week: his answers each day (the Jugador card).
            (pid, p), = players.items()
            out["answers"] = [{"date": d.isoformat(),
                               "row": (_answer_row(pid, p, ins.get((pid, d)), outs.get((pid, d)))
                                       if (pid, d) in ins or (pid, d) in outs else None)} for d in days]
        return out

    # "Sin responder" = trained that day (GPS) and answered nothing. A player
    # with neither GPS nor an answer was not there (injured, resting, with
    # another team): listing him would only bury the ones to chase.
    trained = set(_gps_rows(team_of(mc), day, day).values_list("player_id", flat=True))
    rows, flagged, missing = [], [], []
    for pid, p in sorted(players.items(), key=lambda kv: _name(kv[1])):
        i = ins.get((pid, day))
        o = outs.get((pid, day))
        if i is None and o is None:
            if pid in trained:
                missing.append({"player_id": str(pid), "name": _name(p)})
            continue
        row = _answer_row(pid, p, i, o)
        scores = row["scores"]
        rows.append(row)
        lows = [{"key": k, "value": v} for k, v in scores.items() if v is not None and v <= low]
        if lows or row["pain"] or row["symptoms"]:
            # Pain first (3), then illness (2), then each low item (1).
            severity = 3 * bool(row["pain"]) + 2 * bool(row["symptoms"]) + len(lows)
            flagged.append({**row, "lows": lows, "severity": severity})
    flagged.sort(key=lambda r: (-r["severity"], r["total_bienestar"] or 99, r["name"]))
    out.update(rows=rows, flagged=flagged, missing=missing,
               answered={"checkin": sum(r["checkin"] for r in rows),
                         "checkout": sum(r["checkout"] for r in rows)})
    return out
