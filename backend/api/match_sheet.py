"""Pitch placement for the match view.

Two sides, two different amounts of truth — and the API is explicit about which
is which, so the UI can label them honestly:

  * OUR side is placed from SLAB's own `Player.position`. The club's taxonomy
    already distinguishes side ("Lateral derecho", "Volante izquierdo",
    "Extremo derecho"), so a player with a specific position lands in a specific
    slot; one with a generic position ("Defensor", "Mediocampista") is spread
    across its line. The drawing therefore gets more accurate on its own as the
    staff fills in specific positions — nothing here needs to change.

  * THE RIVAL has no position data anywhere. COMET reports `position` for
    goalkeepers only ("G") and its `/formation` endpoint returns `{}` for this
    tenant, so the outfield ten are laid out on a generic 4-4-2 ordered by shirt
    number. That is an approximation and the payload says so
    (`placement="generic"`), because low-to-high numbering is only a loose
    convention — this squad has a goalkeeper wearing 25.

The goalkeeper is never guessed: COMET states it, so the single most jarring
error (a keeper standing in midfield) can't happen on either side.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# line: 0 = goal, 1 = defence, 2 = midfield, 3 = attack
GK, DEF, MID, FWD = 0, 1, 2, 3
# lane: -1 left, 0 centre, +1 right, None = unspecified (spread within the line)
LEFT, CENTRE, RIGHT = -1, 0, 1

# Keyed on the club's position ABBREVIATION (stable; the display name is
# free-text per club). Falls back to a name match below.
ABBREV_MAP: dict[str, tuple[int, int | None]] = {
    "POR": (GK, CENTRE),
    "LD": (DEF, RIGHT), "LVD": (DEF, RIGHT),
    "LI": (DEF, LEFT), "LVI": (DEF, LEFT),
    "DC": (DEF, CENTRE),
    "L": (DEF, None), "D": (DEF, None), "DF": (DEF, None),
    "VD": (MID, RIGHT), "VI": (MID, LEFT),
    "VC": (MID, CENTRE), "VI2": (MID, CENTRE), "VO": (MID, CENTRE),
    "MC": (MID, None),
    "ED": (FWD, RIGHT), "EI": (FWD, LEFT),
    "DC2": (FWD, CENTRE), "DEL": (FWD, None),
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return s.lower().strip()


def line_for_position(name: str | None, abbreviation: str | None) -> tuple[int | None, int | None]:
    """(line, lane) for a SLAB position, or (None, None) when unknown."""
    if abbreviation:
        hit = ABBREV_MAP.get(abbreviation.strip().upper())
        if hit:
            return hit
    n = _norm(name)
    if not n:
        return (None, None)
    lane = RIGHT if "derech" in n else (LEFT if "izquierd" in n else None)
    if any(k in n for k in ("arquero", "portero", "golero")):
        return (GK, CENTRE)
    if any(k in n for k in ("defens", "central", "lateral", "zaguero", "marcador")):
        return (DEF, lane)
    if any(k in n for k in ("volante", "medio", "pivote", "contencion")):
        return (MID, lane)
    if any(k in n for k in ("delanter", "extremo", "punta", "atacante", "wing")):
        return (FWD, lane)
    return (None, None)


# Generic 4-4-2 used for a side with no position data at all: how many outfield
# slots each line gets.
GENERIC_SHAPE = [(DEF, 4), (MID, 4), (FWD, 2)]

# Classic 2–11 numbering, applied only where a player actually wears one of those
# numbers. Plain low-to-high ordering is worse than this: it put a #9 who scored
# twice into the back four. Squad numbers above 11 carry no convention at all and
# are dealt into whatever slots remain.
CLASSIC_NUMBERS: dict[int, int] = {
    2: DEF, 3: DEF, 4: DEF, 5: DEF, 6: DEF,
    8: MID, 7: MID, 10: MID, 14: MID,
    9: FWD, 11: FWD,
}

_LINE_Y = {GK: 8, DEF: 30, MID: 55, FWD: 80}   # % from own goal
_LINE_LABEL = {GK: "Arquero", DEF: "Defensa", MID: "Mediocampo", FWD: "Ataque"}


def _spread(n: int) -> list[float]:
    """Evenly spaced x positions (%) for `n` players in one line.

    The span GROWS with the count instead of always filling the width: two
    forwards belong near the middle, not pinned to both touchlines. Four across
    still reaches the flanks.
    """
    if n <= 0:
        return []
    if n == 1:
        return [50.0]
    span = min(84.0, 24.0 * (n - 1))   # n=2 → 24, n=3 → 48, n=4 → 72, n≥5 → 84
    start = (100.0 - span) / 2
    step = span / (n - 1)
    return [round(start + i * step, 1) for i in range(n)]


def _order_lane(players: list[dict]) -> list[dict]:
    """Left → centre → right; players with no lane keep their relative order and
    fill the middle, so a line of four generic defenders still reads as a line."""
    lanes = {LEFT: [], CENTRE: [], RIGHT: [], None: []}
    for p in players:
        lanes[p.get("lane")].append(p)
    return lanes[LEFT] + lanes[None] + lanes[CENTRE] + lanes[RIGHT]


def place(players: list[dict]) -> list[dict]:
    """Assign x/y (%) to each player already carrying a `line`."""
    out: list[dict] = []
    for line in (GK, DEF, MID, FWD):
        row = _order_lane([p for p in players if p.get("line") == line])
        xs = _spread(len(row))
        for p, x in zip(row, xs):
            out.append({**p, "x": x, "y": _LINE_Y[line], "line_label": _LINE_LABEL[line]})
    return out


def _events_for(name: str | None, tally: dict[str, dict]) -> dict:
    return tally.get(_norm(name), {"goals": 0, "yellow": 0, "red": 0,
                                   "minute_in": None, "minute_out": None})


def tally_from_timeline(events: list[dict], *, home: bool) -> dict[str, dict]:
    """Per-player goals / cards / substitution minutes for ONE side, keyed on the
    normalized COMET name. Used for the rival, who has no SLAB records — their
    only source of per-player events is the shared timeline.
    """
    out: dict[str, dict] = {}

    def slot(nm: str | None) -> dict | None:
        k = _norm(nm)
        if not k:
            return None
        return out.setdefault(k, {"goals": 0, "yellow": 0, "red": 0,
                                  "minute_in": None, "minute_out": None})

    for e in events:
        if bool(e.get("homeTeam")) != home:
            continue
        et = e.get("eventType") or {}
        fcd = (et.get("fcdName") or "").upper()
        # `minuteFull` is the match minute; `minute` restarts each half.
        minute = e.get("minuteFull")
        main = slot((e.get("player") or {}).get("name"))
        second = slot((e.get("player2") or {}).get("name"))
        if fcd == "SUBSTITUTION":
            if main is not None:
                main["minute_in"] = minute
            if second is not None:
                second["minute_out"] = minute
        elif main is not None:
            if fcd in ("GOAL", "PENALTY_GOAL"):
                main["goals"] += 1
            elif "YELLOW" in fcd:
                main["yellow"] += 1
            elif fcd == "RED":
                main["red"] += 1
    return out


def build_side(
    comet_players: list[dict],
    events: list[dict],
    *,
    home: bool,
    team: str | None,
    slab_positions: dict[int, tuple[str | None, str | None]] | None = None,
) -> dict:
    """One pitch side.

    `slab_positions` maps a COMET personId → (position_name, abbreviation) and is
    only supplied for OUR side; without it the outfield falls back to the generic
    shape and `placement` reports "generic" so the UI can say so.
    """
    tally = tally_from_timeline(events, home=home)
    starters, bench = [], []
    for p in comet_players:
        is_gk = (p.get("position") or "").strip().upper() == "G"
        row = {
            "person_id": p.get("personId"),
            "name": p.get("name"),
            "short_name": p.get("shortName") or p.get("name"),
            "shirt_number": p.get("shirtNumber"),
            "captain": bool(p.get("captain")),
            "is_gk": is_gk,
            **_events_for(p.get("name"), tally),
        }
        (starters if p.get("starting") else bench).append(row)

    resolved = lanes = 0
    for p in starters:
        # The keeper is stated by COMET — never inferred.
        if p["is_gk"]:
            p["line"], p["lane"] = GK, CENTRE
            continue
        line = lane = None
        if slab_positions:
            name, abbrev = slab_positions.get(p["person_id"], (None, None))
            line, lane = line_for_position(name, abbrev)
            if line is not None:
                resolved += 1
            if lane is not None:
                lanes += 1
        p["line"], p["lane"] = line, lane

    # Anyone still without a line — the whole rival XI, or one of ours whose
    # position isn't registered. Seed from the classic 2–11 numbering, then deal
    # the rest into whatever slots the 4-4-2 has left.
    unplaced = [p for p in starters if p.get("line") is None]
    if unplaced:
        taken: dict[int, int] = {}
        for p in starters:
            if p.get("line") is not None:
                taken[p["line"]] = taken.get(p["line"], 0) + 1

        still: list[dict] = []
        for p in sorted(unplaced, key=lambda p: (p["shirt_number"] is None,
                                                 p["shirt_number"] or 0)):
            guess = CLASSIC_NUMBERS.get(p["shirt_number"] or 0)
            cap = dict(GENERIC_SHAPE).get(guess) if guess is not None else None
            if guess is not None and taken.get(guess, 0) < (cap or 0):
                p["line"], p["lane"] = guess, None
                taken[guess] = taken.get(guess, 0) + 1
            else:
                still.append(p)

        cursor = 0
        for line, capacity in GENERIC_SHAPE:
            free = max(0, capacity - taken.get(line, 0))
            for p in still[cursor:cursor + free]:
                p["line"], p["lane"] = line, None
            cursor += free
        # More players than the template holds → park the remainder in midfield
        # rather than dropping them off the pitch.
        for p in still[cursor:]:
            p["line"], p["lane"] = MID, None

    return {
        "team": team,
        # "slab_positions" = the LINES come from registered positions. Lanes are
        # only real for the `lanes_resolved` players whose position names a side
        # ("Lateral derecho"); the rest are spread evenly, so the UI should call
        # left/right approximate even here.
        "placement": "slab_positions" if resolved else "generic",
        "positions_resolved": resolved,
        "lanes_resolved": lanes,
        "starters": place(starters),
        "bench": sorted(bench, key=lambda p: (p["shirt_number"] is None,
                                              p["shirt_number"] or 0)),
    }


# ---------- real elapsed time (regulation + added time) ----------
# COMET's official minutes cap at 90 — that's what the federation publishes and
# what /player/{id}/stats reports, so the ficha keeps them. But the END /
# FULL_TIME markers carry `stoppageTime` per period, which lets us rebuild the
# REAL clock. Verified against GPS on two matches: Limache +4/+6 → 100 real vs
# 100.1 measured; Wanderers +3/+7 → 100 vs 100.0. Substitutions line up too — a
# 79' change in the second half is real minute 79 + 4 = 83, and those players'
# GPS read 83.0.

REGULATION_HALF = 45
REGULATION_FULL = 90


def period_stoppage(events: list[dict]) -> tuple[int, int]:
    """(added time 1st half, added time 2nd half) in minutes; 0 when absent."""
    s1 = s2 = 0
    for e in events:
        fcd = ((e.get("eventType") or {}).get("fcdName") or "").upper()
        if fcd not in ("END", "FULL_TIME"):
            continue
        phase = ((e.get("matchPhase") or {}).get("fcdName") or "").upper()
        try:
            added = int(e.get("stoppageTime") or 0)
        except (TypeError, ValueError):
            added = 0
        if phase == "FIRST_HALF":
            s1 = max(s1, added)
        elif phase == "SECOND_HALF":
            s2 = max(s2, added)
    return s1, s2


def real_total_minutes(s1: int, s2: int) -> int:
    return REGULATION_FULL + s1 + s2


def to_real_minute(minute_full: int | None, s1: int) -> int | None:
    """Official match minute → real elapsed minute.

    Anything after the interval is shifted by the first half's added time, since
    COMET keeps counting from 45 regardless of how long the first half actually
    ran.
    """
    if minute_full is None:
        return None
    return minute_full + s1 if minute_full > REGULATION_HALF else minute_full


def real_minutes_played(
    minute_in: int | None, minute_out: int | None, *, s1: int, s2: int,
) -> int | None:
    """Minutes actually on the pitch, added time included.

    `minute_in` is 0 for a starter and None for an unused substitute.
    """
    if minute_in is None:
        return 0
    total = real_total_minutes(s1, s2)
    start = to_real_minute(minute_in, s1) or 0
    end = to_real_minute(minute_out, s1) if minute_out is not None else total
    return max(0, (end or total) - start)
