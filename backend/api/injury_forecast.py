"""Forecast-accuracy KPI (§3.2) — how close injury return *prognoses* are to
the real availability date.

Per episode with a known return (available_at, else ended_at):

    error_days = actual − first_expected_return_date

where `first_expected_return_date` is the earliest linked result carrying an
`expected_return_date` (the prognosis at diagnosis). Positive error = the
player came back LATER than forecast (an optimistic prognosis).

Aggregated per (category, optional department, period) into:
  * bias  = signed mean of error_days — systematic optimism (+) / pessimism (−)
  * mae   = mean of |error_days| — typical error size

Pure-ish: one bounded query per episode; fine for an on-demand report.
"""
from __future__ import annotations

from datetime import date, datetime
from statistics import mean
from typing import Any


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    # datetime is a subclass of date — narrow it first, else a tz-aware
    # available_at would slip through and break date arithmetic.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def forecast_accuracy(*, category, department=None, date_from=None, date_to=None,
                      template_slug: str = "lesiones") -> dict:
    from exams.models import Episode, ExamResult

    eps = (
        Episode.objects
        .filter(template__slug=template_slug, player__category=category)
        .select_related("player", "template")
    )
    if department is not None:
        eps = eps.filter(template__department=department)

    samples: list[dict] = []
    for ep in eps:
        actual = ep.available_at or ep.ended_at
        actual_d = _to_date(actual)
        if actual_d is None:
            continue  # no real return yet → can't score
        if date_from and actual_d < date_from:
            continue
        if date_to and actual_d > date_to:
            continue

        first_expected = None
        for data in (
            ExamResult.objects.filter(episode=ep)
            .order_by("recorded_at").values_list("result_data", flat=True)
        ):
            d = _to_date((data or {}).get("expected_return_date"))
            if d is not None:
                first_expected = d
                break
        if first_expected is None:
            continue  # never forecast → nothing to compare

        error = (actual_d - first_expected).days
        samples.append({
            "player": f"{ep.player.first_name} {ep.player.last_name}".strip(),
            "title": ep.title or ep.template.name,
            "first_expected": first_expected.isoformat(),
            "actual": actual_d.isoformat(),
            "error_days": error,
        })

    if not samples:
        return {"episodes": 0, "bias_days": None, "mae_days": None, "samples": []}

    errs = [s["error_days"] for s in samples]
    return {
        "episodes": len(samples),
        "bias_days": round(mean(errs), 1),
        "mae_days": round(mean(abs(e) for e in errs), 1),
        # Worst-first so the report leads with the biggest misses.
        "samples": sorted(samples, key=lambda s: abs(s["error_days"]), reverse=True),
    }
