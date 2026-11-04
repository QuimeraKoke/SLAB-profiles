"""Any calendar week of a team, planned or not.

The squad panels (Resumen, Fatiga, Check-in/out, Kinesia, Minutos, Jugador)
are read day by day with "día anterior / día siguiente" (the staff,
2026-11-04): the week is whichever Monday–Sunday holds the day, with no need
to have planned it first. A planned week (`Microcycle`) is used as is; an
unplanned one is built in memory — the same days, match kinds and MD labels
the planner would suggest, and no load targets (those only exist in a plan).

Services read a week's days through `days_of(mc)`, which works for both.
"""
from __future__ import annotations

from datetime import date, timedelta

from load_control.models import Microcycle, MicrocycleDay


class _Days(list):
    """A list that answers the two queryset calls the services make."""

    def all(self):
        return self

    def order_by(self, *_):
        return sorted(self, key=lambda d: d.date)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def days_of(mc: Microcycle):
    transient = getattr(mc, "_week_days", None)
    return transient if transient is not None else mc.days.order_by("date")


def week_for(team, day: date) -> Microcycle:
    """The team's week holding `day`: its planned microcycle, or a transient one."""
    from load_control import planning
    from load_control.labels import labels_for, neighbour_matches

    start = monday_of(day)
    mc = (Microcycle.objects.select_related("club", "bracket", "copied_from")
          .filter(club=team.club, season=team.season, bracket=team.bracket, start_date=start).first())
    if mc is not None:
        return mc
    s = planning.suggest(team, start)
    mc = Microcycle(club=team.club, season=team.season, bracket=team.bracket, number=s["number"],
                    kind=s["kind"], start_date=start, end_date=start + timedelta(days=6))
    days = _Days(MicrocycleDay(microcycle=mc, date=x["date"], kind=x["kind"]) for x in s["days"])
    labels = labels_for(mc.club, mc.season, mc.bracket, mc.start_date, mc.end_date,
                        [(d.date, d.is_match) for d in days], neighbour_matches(mc))
    for d in days:
        d.md_label, d.md_label_source = labels[d.date]
    mc._week_days = days
    return mc


def describe(mc: Microcycle, day: date) -> dict:
    """What the day navigator shows."""
    return {
        "day": day.isoformat(), "start_date": mc.start_date.isoformat(), "end_date": mc.end_date.isoformat(),
        "number": mc.number, "kind": mc.kind, "planned": mc.pk is not None and not hasattr(mc, "_week_days"),
        "microcycle_id": str(mc.pk) if not hasattr(mc, "_week_days") else None,
        "md_label": next((d.md_label for d in days_of(mc) if d.date == day), ""),
        "day_kind": next((d.kind for d in days_of(mc) if d.date == day), ""),
    }
