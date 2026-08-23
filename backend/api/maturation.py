"""Biological maturity: maturity offset (Mirwald) and height velocity.

Why this matters next to `api.development`: that module answers "does he play
above his age group?", and the strongest objection to it is that a boy playing up
may simply be **maturing earlier**, not be better. The mirror case is the one
nobody currently sees — a late maturer holding his own in his own age group may
be the most talented player in the group, and the system reads him as average.

Both calculations here are deliberately conservative about saying "I don't know".
The inputs are real measurements of real children and the outputs get used to
decide who trains where, so a number that looks precise and isn't is the worst
possible output. Every function returns `None` (with a reason from the callers'
side) rather than extrapolating.

Data note: this club's anthropometry carries `talla`, `talla_sentado` and `peso`
at 100% completeness across 1,185 youth assessments, which is exactly the input
Mirwald needs — so unlike the GPS work in `api.development`, nothing has to be
collected first. What is NOT available is parental stature, so Khamis-Roche
(predicted adult height, and therefore %PAH banding) is out of reach.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Mirwald et al. (2002), "An assessment of maturity from anthropometric
# measurements", Med Sci Sports Exerc 34(4):689-694. Sex-specific regressions
# predicting YEARS FROM peak height velocity.
#
# Inputs: age in decimal years, stature and sitting height in cm, weight in kg.
# Leg length is stature − sitting height.
_BOYS = dict(
    intercept=-9.236,
    leg_x_sitting=0.0002708,
    age_x_leg=-0.001663,
    age_x_sitting=0.007216,
    weight_over_height=0.02292,
    age_x_weight=0.0,
)
_GIRLS = dict(
    intercept=-9.376,
    leg_x_sitting=0.0001882,
    age_x_leg=0.0022,
    age_x_sitting=0.005841,
    weight_over_height=0.07693,
    age_x_weight=-0.002658,
)

# The regressions were fitted on 8–16 year-olds and are reported as unreliable
# outside roughly 9–17. Beyond that the equation still returns a number, which is
# precisely the danger.
VALID_AGE = (8.0, 18.0)

# Mirwald's own standard error is ~±1 year, and accuracy degrades the further the
# child is from PHV. Past this distance the estimate is directional at best.
CONFIDENT_OFFSET = 1.0

# Plausible human ranges — these double as a corruption check. See
# `exams.penta_ingest`: 20 youth assessments in this database hold a `talla` of
# 30–68 cm because of a column shift in the club's legacy system, and one of them
# produced a NEGATIVE bone mass that sat unnoticed for a year.
TALLA_RANGE = (100.0, 220.0)
SITTING_RATIO_RANGE = (0.40, 0.62)   # sitting height / stature
PESO_RANGE = (20.0, 150.0)

# Height velocity needs a real interval. Annualising a 4-month delta multiplies
# the measurement error by three, and two ISAK measurements differ by a few mm
# even when nothing changed.
MIN_VELOCITY_DAYS = 180
CONFIDENT_VELOCITY_DAYS = 365
# Above this, the reading is an error, not a growth spurt: the fastest recorded
# adolescent growth is ~12 cm/year.
MAX_PLAUSIBLE_VELOCITY = 15.0


def decimal_age(born: date, on: date) -> float:
    return (on - born).days / 365.25


def plausible_measurement(
    *, talla: float | None, talla_sentado: float | None, peso: float | None,
) -> bool:
    """Whether the three inputs can belong to the same human being.

    A ratio check on sitting height catches the shifted rows that a range check
    on each field alone would let through: 146.9 cm is a fine stature and 76.6 cm
    a fine sitting height, but 146.9 as the SITTING height of a 45 cm person is
    not, and that is the exact shape of this club's corrupted rows.
    """
    if talla is None or talla_sentado is None or peso is None:
        return False
    if not TALLA_RANGE[0] <= talla <= TALLA_RANGE[1]:
        return False
    if not PESO_RANGE[0] <= peso <= PESO_RANGE[1]:
        return False
    ratio = talla_sentado / talla
    return SITTING_RATIO_RANGE[0] <= ratio <= SITTING_RATIO_RANGE[1]


@dataclass(frozen=True)
class Maturity:
    """Years from peak height velocity, and how much to trust it."""

    offset_years: float          # negative = before PHV, positive = after
    aphv_years: float            # estimated age at PHV
    age_years: float
    confident: bool              # within Mirwald's usable distance from PHV
    stage: str                   # pre_phv | circa_phv | post_phv

    @property
    def label(self) -> str:
        return {
            "pre_phv": "Antes del pico de crecimiento",
            "circa_phv": "En el pico de crecimiento",
            "post_phv": "Después del pico de crecimiento",
        }[self.stage]


def maturity_offset(
    *, age_years: float, talla: float, talla_sentado: float, peso: float,
    female: bool = False,
) -> Maturity | None:
    """Mirwald maturity offset. `None` when the inputs can't support an estimate.

    Returns years from PHV: −1.5 means "about eighteen months before the growth
    spurt", +0.5 means "just past it".
    """
    if not plausible_measurement(
        talla=talla, talla_sentado=talla_sentado, peso=peso,
    ):
        return None
    if not VALID_AGE[0] <= age_years <= VALID_AGE[1]:
        return None

    c = _GIRLS if female else _BOYS
    leg = talla - talla_sentado
    if leg <= 0:
        return None
    offset = (
        c["intercept"]
        + c["leg_x_sitting"] * leg * talla_sentado
        + c["age_x_leg"] * age_years * leg
        + c["age_x_sitting"] * age_years * talla_sentado
        + c["age_x_weight"] * age_years * peso
        + c["weight_over_height"] * (peso / talla) * 100.0
    )
    stage = (
        "circa_phv" if abs(offset) <= 0.5
        else "pre_phv" if offset < 0
        else "post_phv"
    )
    return Maturity(
        offset_years=round(offset, 2),
        aphv_years=round(age_years - offset, 2),
        age_years=round(age_years, 2),
        confident=abs(offset) <= CONFIDENT_OFFSET,
        stage=stage,
    )


@dataclass(frozen=True)
class Velocity:
    """Annualised stature change between two assessments."""

    cm_per_year: float
    days: int
    delta_cm: float
    provisional: bool            # interval shorter than a year
    from_talla: float
    to_talla: float


def height_velocity(
    measurements: list[tuple[date, float]],
) -> Velocity | None:
    """cm/year from the FIRST and LAST plausible stature, or `None`.

    Uses the widest available interval rather than consecutive pairs: ISAK
    repeatability is a few millimetres, so a short gap can easily show negative
    growth in a child who is certainly growing.
    """
    pts = sorted(
        (d, h) for d, h in measurements
        if h is not None and TALLA_RANGE[0] <= h <= TALLA_RANGE[1]
    )
    if len(pts) < 2:
        return None
    (d0, h0), (d1, h1) = pts[0], pts[-1]
    days = (d1 - d0).days
    if days < MIN_VELOCITY_DAYS:
        return None
    per_year = (h1 - h0) / (days / 365.25)
    # A negative or absurd rate is a measurement problem, not a finding. Saying
    # "unknown" beats reporting that a 12-year-old shrank.
    if per_year < 0 or per_year > MAX_PLAUSIBLE_VELOCITY:
        return None
    return Velocity(
        cm_per_year=round(per_year, 1),
        days=days,
        delta_cm=round(h1 - h0, 1),
        provisional=days < CONFIDENT_VELOCITY_DAYS,
        from_talla=h0,
        to_talla=h1,
    )


# ---------- maturity timing (bio-banding) ----------

# Mirwald's estimate is biased toward the child's CURRENT age — the regression
# includes age on both sides, so APHV drifts upward as the sample ages. Measured
# on this club: the median APHV moves +1.19 years between ages 10 and 17, while
# the spread WITHIN a single age is only ~0.55. The bias is more than double the
# signal.
#
# The consequence is not subtle: an APHV of 14.0 is EARLY for a 17-year-old here
# (median 14.46) and LATE for a 14-year-old (median 13.38). The same number means
# opposite things, so a literature threshold like "APHV < 13.0 = early maturer"
# would mostly measure how old the boy is.
#
# Hence: always classify against peers of the SAME age, never against a constant.
TIMING_Z = 1.0            # standard deviations from the age-group median
MIN_TIMING_PEERS = 8      # below this the reference distribution is noise

TIMING_LABELS = {
    "early": "Maduración temprana",
    "on_time": "Maduración normal",
    "late": "Maduración tardía",
}


def maturity_timing(
    aphv: float, peer_aphvs: list[float],
) -> tuple[str, float] | None:
    """(classification, z) for one player against same-age peers, or None.

    A LOW APHV means he reaches peak growth younger — an early maturer.
    Returns None when the reference group is too small to define a spread.
    """
    peers = [v for v in peer_aphvs if v is not None]
    if len(peers) < MIN_TIMING_PEERS:
        return None
    n = len(peers)
    mean = sum(peers) / n
    var = sum((v - mean) ** 2 for v in peers) / n
    sd = var ** 0.5
    if sd <= 0:
        return None
    z = (aphv - mean) / sd
    if z <= -TIMING_Z:
        return "early", round(z, 2)
    if z >= TIMING_Z:
        return "late", round(z, 2)
    return "on_time", round(z, 2)


# Bands for grouping by maturity instead of birth year — the point of
# bio-banding. Offset is years from PHV, so these are training-relevant stages
# rather than arbitrary slices.
#
# NOTE: the textbook method bands by PERCENTAGE OF PREDICTED ADULT HEIGHT
# (85–90%, 90–95%…), which needs Khamis-Roche and therefore parental stature.
# That isn't recorded anywhere in this system, so offset bands are the honest
# substitute — they answer "who is at the same point in their growth?" without
# pretending to predict adult height.
BANDS: list[tuple[str, str, float, float]] = [
    ("pre_lejano", "Lejos del pico (< −1 año)", float("-inf"), -1.0),
    ("pre_cercano", "Acercándose al pico (−1 a 0)", -1.0, 0.0),
    ("post_cercano", "Recién pasado el pico (0 a +1)", 0.0, 1.0),
    ("post_lejano", "Pasado el pico (> +1 año)", 1.0, float("inf")),
]


def band_for(offset_years: float) -> tuple[str, str]:
    """(key, label) of the maturity band an offset falls in."""
    for key, label, lo, hi in BANDS:
        if lo <= offset_years < hi:
            return key, label
    return BANDS[-1][0], BANDS[-1][1]


# ---------- club-wide service ----------

# Mirwald is invalid past 18, so the senior squad is out by construction. The
# growth question is a YOUTH question: "is this boy still growing, and where is
# he in his spurt?" — meaningless for a 28-year-old.
_SENIOR_NAMES = {"Primer Equipo", "Selección Nacional"}

_ANTHRO_SLUG = "pentacompartimental"


def _reading(result_data: dict) -> tuple[float, float, float] | None:
    """(talla, talla_sentado, peso) when all three are usable numbers."""
    out = []
    for key in ("talla", "talla_sentado", "peso"):
        v = (result_data or {}).get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        out.append(float(v))
    return tuple(out)          # type: ignore[return-value]


def club_maturation(*, club_id, team_ids=None) -> dict:
    """Maturity + growth for a club's youth players.

    Two passes are unavoidable: the timing classification compares each player
    against peers of the SAME AGE, so the whole distribution has to exist before
    anyone can be classified. See `maturity_timing` for why a fixed threshold
    would mostly measure age.
    """
    from collections import defaultdict

    from exams.models import ExamResult

    qs = (
        ExamResult.objects
        .filter(template__slug=_ANTHRO_SLUG, player__category__club_id=club_id)
        .select_related("player", "player__category")
        .order_by("recorded_at")
    )
    if team_ids:
        qs = qs.filter(player__category_id__in=team_ids)

    latest: dict = {}
    heights: dict = defaultdict(list)
    skipped_senior = skipped_no_dob = skipped_unusable = 0

    for r in qs.iterator(chunk_size=2000):
        p = r.player
        if p.category is None or p.category.name in _SENIOR_NAMES:
            skipped_senior += 1
            continue
        if p.date_of_birth is None:
            skipped_no_dob += 1
            continue
        read = _reading(r.result_data)
        if read is None:
            skipped_unusable += 1
            continue
        talla, sentado, peso = read
        when = r.recorded_at.date()
        heights[p.id].append((when, talla))
        m = maturity_offset(
            age_years=decimal_age(p.date_of_birth, when),
            talla=talla, talla_sentado=sentado, peso=peso,
            female=(p.sex or "M").upper().startswith("F"),
        )
        # Ordered by date, so the last usable reading wins.
        if m is not None:
            latest[p.id] = (p, when, m)

    # Pass 2: the same-age reference, then classify.
    by_age: dict = defaultdict(list)
    for _, _, m in latest.values():
        by_age[int(m.age_years)].append(m.aphv_years)

    rows = []
    for pid, (p, when, m) in latest.items():
        timing = maturity_timing(m.aphv_years, by_age[int(m.age_years)])
        band_key, band_label = band_for(m.offset_years)
        vel = height_velocity(heights[pid])
        rows.append({
            "player_id": str(pid),
            "player_name": f"{p.first_name} {p.last_name}".strip(),
            "team": p.category.name if p.category else None,
            "team_id": str(p.category_id) if p.category_id else None,
            "birth_year": p.date_of_birth.year,
            "measured_on": when,
            "age_years": m.age_years,
            "offset_years": m.offset_years,
            "aphv_years": m.aphv_years,
            "stage": m.stage,
            "stage_label": m.label,
            "band": band_key,
            "band_label": band_label,
            "confident": m.confident,
            "timing": timing[0] if timing else None,
            "timing_label": TIMING_LABELS[timing[0]] if timing else None,
            "timing_z": timing[1] if timing else None,
            "velocity_cm_year": vel.cm_per_year if vel else None,
            "velocity_provisional": vel.provisional if vel else None,
            "velocity_days": vel.days if vel else None,
        })

    rows.sort(key=lambda r: (r["team"] or "", r["offset_years"]))
    return {
        "players": rows,
        "bands": [{"key": k, "label": lbl} for k, lbl, _, _ in BANDS],
        "skipped": {
            "senior": skipped_senior,
            "sin_fecha_nacimiento": skipped_no_dob,
            "medicion_inutilizable": skipped_unusable,
        },
    }


def band_summary(rows: list[dict]) -> list[dict]:
    """Per team: how many players sit in each band.

    `informative` is the point of the table. A team whose players all land in one
    band tells you nothing you didn't know from their birth year — measured on
    this club, that's every category from SUB-16 up, where everyone is past the
    peak. SUB-13 spans all four.
    """
    from collections import defaultdict

    per_team: dict = defaultdict(lambda: defaultdict(int))
    still_growing: dict = defaultdict(int)
    for r in rows:
        per_team[r["team"]][r["band"]] += 1
        if (r["velocity_cm_year"] or 0) >= 3.0:
            still_growing[r["team"]] += 1

    out = []
    for team, counts in per_team.items():
        occupied = sum(1 for v in counts.values() if v)
        out.append({
            "team": team,
            "players": sum(counts.values()),
            "counts": dict(counts),
            "bands_occupied": occupied,
            "informative": occupied >= 2,
            "still_growing": still_growing[team],
        })
    out.sort(key=lambda t: t["team"] or "")
    return out
