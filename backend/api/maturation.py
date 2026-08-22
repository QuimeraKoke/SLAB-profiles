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
