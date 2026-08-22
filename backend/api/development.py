"""Player development: who plays above their own age group, and since when.

The question the club actually asks — "which kids are ahead?" — and the two ways
of answering it that DON'T work, both learned by getting them wrong on real data
(PRD_EQUIPO_TEMPORADA.md §6.1, §7):

1. **Don't compare one season's level to the previous one.** That conflates the
   natural climb up the ladder with the player's standing inside his own cohort.
   Four 2008-born players looked like they were dropping from Sub 20 to Sub 18
   when they had simply returned to their own level after a year of playing up.

2. **Don't anchor on the team's bracket.** A mixed team makes its own players
   look wrong: SUB-15 holds 30 players born 2010 and a few born 2011, so its
   team bracket is Sub 16 and the 2011s read as playing "below their team" while
   being exactly where they belong. Measured both ways, the team anchor invents
   8.7% of false mismatches against 0.7% for the cohort anchor, and it is
   unstable across seasons (94.5% → 86.5%) where the cohort anchor holds
   (89.7% → 88.9%).

So: the yardstick is the player's own birth year, and distance is measured in
LADDER RUNGS (`Bracket.order`), never in years — the ANFP ladder skips Sub 17
and Sub 19, so Sub 16 → Sub 18 is one rung, not two.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.models import Bracket
from events.models import EventParticipant

# A season with fewer appearances than this says nothing. Without the floor, a
# single guest appearance reads as a "jump".
MIN_APPEARANCES = 3

# How far above his own bracket a player has to turn out before we call it
# remarkable rather than routine.
STANDOUT_RUNGS = 2


@dataclass
class Ladder:
    """The competition ladder, ordered, with the rung lookup callers need."""

    brackets: list[Bracket]
    _by_order: dict[int, Bracket] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.brackets = sorted(self.brackets, key=lambda b: b.order)
        self._by_order = {b.order: b for b in self.brackets}

    @classmethod
    def load(cls) -> "Ladder":
        return cls(list(Bracket.objects.all()))

    def natural(self, birth_year: int, season: int) -> Bracket | None:
        """The rung a player of that cohort belongs on, for `season`.

        The first bracket that still admits his age — brackets are a ceiling, so
        a 17-year-old lands on Sub 18 because Sub 17 doesn't exist.
        """
        if not birth_year:
            return None
        age = season - birth_year
        for b in self.brackets:
            if b.age is not None and b.age >= age:
                return b
        return self.brackets[-1] if self.brackets else None

    def by_order(self, order: int) -> Bracket | None:
        return self._by_order.get(order)


def classify(rungs: int | None) -> str:
    """A rung delta → the label the UI shows. `None` when it can't be judged."""
    if rungs is None:
        return "sin_datos"
    if rungs >= STANDOUT_RUNGS:
        return "muy_por_encima"
    if rungs == 1:
        return "por_encima"
    if rungs == 0:
        return "su_cohorte"
    return "por_debajo"


LABELS = {
    "muy_por_encima": "Muy por encima de su cohorte",
    "por_encima": "Por encima de su cohorte",
    "su_cohorte": "En su cohorte",
    "por_debajo": "Por debajo de su cohorte",
    "sin_datos": "Sin datos suficientes",
}


def player_seasons(
    *, club_id, season: int | None = None, category_id=None,
) -> list[dict[str, Any]]:
    """One row per (player, season): where he played vs where he belongs.

    `dominant` is the bracket he appeared in MOST that season, not merely one he
    appeared in — a cup guest appearance shouldn't redefine his season.
    """
    ladder = Ladder.load()
    if not ladder.brackets:
        return []

    qs = (
        EventParticipant.objects
        .filter(event__event_type="match", event__club_id=club_id,
                event__bracket__isnull=False)
        .select_related("event", "event__bracket", "player", "player__category")
    )
    if season is not None:
        qs = qs.filter(event__starts_at__year=season)
    if category_id is not None:
        qs = qs.filter(player__category_id=category_id)

    # (player, season) → Counter[bracket order]
    tally: dict[tuple, Counter] = defaultdict(Counter)
    players: dict[Any, Any] = {}
    for ep in qs.iterator(chunk_size=2000):
        yr = ep.event.starts_at.year
        tally[(ep.player_id, yr)][ep.event.bracket.order] += 1
        players[ep.player_id] = ep.player

    out: list[dict[str, Any]] = []
    for (player_id, yr), counts in tally.items():
        p = players[player_id]
        order, n = counts.most_common(1)[0]
        total = sum(counts.values())
        played = ladder.by_order(order)
        birth = p.date_of_birth.year if p.date_of_birth else None
        nat = ladder.natural(birth, yr) if birth else None
        # Below the sample floor we still return the row — hiding it would look
        # like the player didn't play — but refuse to judge it.
        judged = n >= MIN_APPEARANCES and nat is not None
        rungs = (played.order - nat.order) if judged else None
        out.append({
            "player_id": str(player_id),
            "player_name": f"{p.first_name} {p.last_name}".strip(),
            "birth_year": birth,
            "team": p.category.name if p.category else None,
            "season": yr,
            "played_bracket": played.name if played else None,
            "natural_bracket": nat.name if nat else None,
            "appearances": n,
            "appearances_total": total,
            "rungs_above": rungs,
            "status": classify(rungs),
            "status_label": LABELS[classify(rungs)],
        })
    out.sort(key=lambda r: (-(r["rungs_above"] or 0), -r["appearances"], r["player_name"]))
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts per status, plus the standouts, for one season's rows."""
    counts = Counter(r["status"] for r in rows)
    judged = [r for r in rows if r["rungs_above"] is not None]
    return {
        "total": len(rows),
        "judged": len(judged),
        "counts": [
            {"status": k, "label": LABELS[k], "players": counts.get(k, 0)}
            for k in ("muy_por_encima", "por_encima", "su_cohorte",
                      "por_debajo", "sin_datos")
            if counts.get(k, 0)
        ],
        "standouts": [
            r for r in rows
            if r["status"] in ("muy_por_encima", "por_encima")
        ],
    }


# ---------- physical context ----------

# Only duration-independent or per-minute metrics. Cumulative ones (tot_dist,
# hsr, sprint_dist) measure MINUTES, not ability: Jhon Cortés sat at the 13th
# percentile for total distance purely because he came on for 10 minutes.
RATE_METRICS: list[tuple[str, str, str]] = [
    ("max_vel", "Velocidad máxima", "km/h"),
    ("mpm", "Metros por minuto", "m/min"),
    ("hsr_min", "HSR por minuto", "m/min"),
    ("sprint_dist_min", "Sprint por minuto", "m/min"),
]

# Per-minute rates cut the other way: a 15-minute substitute out-runs a
# 90-minute starter on every rate. So peers are restricted to appearances of
# comparable length — ±35% of the player's own typical duration.
DURATION_BAND = 0.35

# Below this many comparable peers, a percentile is noise wearing a number's
# clothes. Measured on real data: banding correctly leaves Cortés with n=1,
# where "100th percentile" would be indefensible. Refusing to answer is the
# honest output.
MIN_PEERS = 8

_GPS_MATCH_SLUG = "gps_partido"


def _num(data: dict | None, key: str) -> float | None:
    v = (data or {}).get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def physical_context(player, *, season: int) -> dict[str, Any]:
    """How the player's physical output compares to the squad he played WITH.

    Same matches, so opponent and tempo are controlled for. This is the only
    comparison the data supports: raw GPS across ages is meaningless (a 2008
    outruns a 2014 by construction), and youth categories have no GPS at all —
    every one of this club's 6,331 GPS rows belongs to Primer Equipo or the
    national team.

    Returns `available: False` with a reason rather than a number it can't
    stand behind.
    """
    from exams.models import ExamResult

    mine = list(
        ExamResult.objects
        .filter(
            player=player, template__slug=_GPS_MATCH_SLUG,
            recorded_at__year=season, event__isnull=False,
        )
        .values_list("event_id", "result_data")
    )
    if not mine:
        return {
            "available": False,
            "reason": "Sin GPS de partido en la temporada.",
            "metrics": [],
        }

    own_durations = [d for d in (_num(r, "tot_dur") for _, r in mine) if d]
    typical = _median(own_durations) if own_durations else None
    event_ids = [e for e, _ in mine]

    peers: dict[str, list[float]] = {k: [] for k, _, _ in RATE_METRICS}
    for pid, data in (
        ExamResult.objects
        .filter(template__slug=_GPS_MATCH_SLUG, event_id__in=event_ids)
        .values_list("player_id", "result_data")
    ):
        if pid == player.id:
            continue
        dur = _num(data, "tot_dur")
        if typical is None or dur is None:
            continue
        if abs(dur - typical) > DURATION_BAND * typical:
            continue
        for key, _, _ in RATE_METRICS:
            v = _num(data, key)
            if v is not None:
                peers[key].append(v)

    metrics = []
    for key, label, unit in RATE_METRICS:
        own = [v for v in (_num(r, key) for _, r in mine) if v is not None]
        pool = peers[key]
        if not own:
            continue
        value = _median(own)
        if len(pool) < MIN_PEERS:
            metrics.append({
                "key": key, "label": label, "unit": unit,
                "value": round(value, 1), "squad_median": None,
                "percentile": None, "peers": len(pool),
            })
            continue
        metrics.append({
            "key": key, "label": label, "unit": unit,
            "value": round(value, 1),
            "squad_median": round(_median(pool), 1),
            "percentile": round(100.0 * sum(1 for v in pool if v < value) / len(pool)),
            "peers": len(pool),
        })

    judged = [m for m in metrics if m["percentile"] is not None]
    return {
        "available": bool(judged),
        "reason": (
            None if judged
            else f"Menos de {MIN_PEERS} compañeros con minutos comparables "
                 f"({'; '.join(str(m['peers']) for m in metrics) or '0'})."
        ),
        "matches": len(mine),
        "typical_minutes": round(typical) if typical else None,
        "metrics": metrics,
    }
