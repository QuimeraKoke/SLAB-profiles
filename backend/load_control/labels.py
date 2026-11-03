"""MD±n labels for a microcycle's days, from ITS match days.

A friendly cuts the microcycle like an official match (decided 2026-11-03), so
the labels come from every match day of the plan — not from the fixtures
calendar, which has no friendlies (they are `gps_sesion` rows with no Event).
The rule itself is `exams.microcycle.microcycle_label`: nearest match within a
week, the upcoming one on a tie. Matches just outside the microcycle (the
previous Sunday, the next Saturday) are passed in so its first and last days
label against them.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from exams.microcycle import microcycle_label


def next_match_label(d: date, matches) -> str | None:
    ahead = [m for m in matches if m > d]
    if not ahead or (ahead[0] - d).days > 7:
        return None
    return f"MD-{(ahead[0] - d).days}"


RULES = {"nearest": microcycle_label, "next": lambda d, ms: next_match_label(d, sorted(ms))}


def label_days(days: Iterable[tuple[date, bool]],
               outside_matches: Iterable[date] = (), *, rule: str = "nearest",
               club_labels: dict[date, str] | None = None) -> dict[date, tuple[str, str]]:
    """`days` = (date, is_match) pairs → {date: (label, source)}.

    A match day is "MD". A day the club coded keeps the club's code (source
    "club") — "siempre lo que use la U". Any other day is computed with
    `rule` (source "calc"); no match within a week → ''."""
    days = list(days)
    club_labels = club_labels or {}
    matches = sorted({d for d, is_match in days if is_match} | set(outside_matches))
    compute = RULES.get(rule, microcycle_label)
    out = {}
    for d, is_match in days:
        if is_match:
            out[d] = ("MD", "club" if club_labels.get(d) == "MD" else "calc")
        elif d in club_labels and club_labels[d] != "MD":
            out[d] = (club_labels[d], "club")
        else:
            out[d] = (compute(d, matches) or "", "calc")
    return out


def neighbour_matches(microcycle) -> list[date]:
    """Match dates within a week either side of `microcycle`: the same team's
    other planned microcycles, and its match days as the club's sheet records
    them (fixtures only where the sheet has none — see `load_control.matches`)."""
    from load_control.matches import team_match_days
    from load_control.models import MicrocycleDay

    lo = microcycle.start_date - timedelta(days=7)
    hi = microcycle.end_date + timedelta(days=7)
    planned = MicrocycleDay.objects.filter(
        microcycle__club=microcycle.club, microcycle__bracket=microcycle.bracket,
        kind__in=MicrocycleDay.MATCH_KINDS, date__range=(lo, hi),
    # By id: a suggestion asks about a microcycle not saved yet.
    ).exclude(microcycle_id=microcycle.pk).values_list("date", flat=True)
    played = team_match_days(microcycle.club, microcycle.season, microcycle.bracket, lo, hi)
    out = set(planned) | set(played)
    return sorted(d for d in out if not microcycle.start_date <= d <= microcycle.end_date)


def labels_for(club, season, bracket, start, end, days, outside) -> dict[date, tuple[str, str]]:
    from load_control.matches import club_day_labels
    from load_control.models import LoadControlConfig

    cfg = LoadControlConfig.resolved(club, bracket)
    return label_days(days, outside, rule=cfg["md_label_rule"],
                      club_labels=club_day_labels(club, season, bracket, start, end))


def relabel(microcycle) -> int:
    """Recompute and save every day's `md_label`. Returns how many changed."""
    days = list(microcycle.days.all())
    labels = labels_for(microcycle.club, microcycle.season, microcycle.bracket,
                        microcycle.start_date, microcycle.end_date,
                        [(d.date, d.is_match) for d in days], neighbour_matches(microcycle))
    changed = [d for d in days if (d.md_label, d.md_label_source) != labels[d.date]]
    for d in changed:
        d.md_label, d.md_label_source = labels[d.date]
    if changed:
        type(days[0]).objects.bulk_update(changed, ["md_label", "md_label_source"])
    return len(changed)
