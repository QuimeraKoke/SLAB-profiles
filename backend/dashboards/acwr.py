"""Centralized ACWR (acute:chronic workload ratio) — §1.f.

One implementation for every surface (roster readiness, command-center KPI,
and — via 1.f/alertable — the alert engine), reading per-category parameters
from ``Category.load_config['acwr']``. An unconfigured category falls back to
``DEFAULT_SPEC``, so behaviour is unchanged until a club tweaks it in the
Django admin.

A *spec* is one monitored variable::

    {"field": "tot_dist", "acute_days": 7, "chronic_days": 28,
     "method": "moving_avg" | "ewma",
     "sweet_low": 0.8, "sweet_high": 1.3,      # target band
     "danger_low": 0.7, "danger_high": 1.5,    # red band
     "label": "Distancia total", "alert": false, "severity": "warning"}

Ratio methods:
  * ``moving_avg`` — acute-window total ÷ (chronic-window total scaled to the
    acute length). Identical to the legacy ``7d ÷ (28d/4)``.
  * ``ewma`` — span-weighted daily load: ``EWMA(daily, acute) ÷
    EWMA(daily, chronic)`` (Williams et al. exponential ACWR).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

from exams.models import ExamResult, ExamTemplate

from .stats import ewma

_GPS_SLUGS = ("gps_partido", "gps_sesion")

DEFAULT_SPEC: dict = {
    "field": "tot_dist", "acute_days": 7, "chronic_days": 28, "method": "moving_avg",
    "sweet_low": 0.8, "sweet_high": 1.3, "danger_low": 0.7, "danger_high": 1.5,
    "label": "Distancia total", "alert": False, "severity": "warning",
}


def _coerce(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class AcwrSpec:
    field: str = "tot_dist"
    acute_days: int = 7
    chronic_days: int = 28
    method: str = "moving_avg"
    sweet_low: float = 0.8
    sweet_high: float = 1.3
    danger_low: float = 0.7
    danger_high: float = 1.5
    label: str = "Distancia total"
    alert: bool = False
    severity: str = "warning"

    @classmethod
    def from_dict(cls, d: dict | None) -> "AcwrSpec":
        merged = {**DEFAULT_SPEC, **(d or {})}
        return cls(**{k: merged[k] for k in DEFAULT_SPEC})

    def band(self, ratio: float | None) -> str | None:
        """'danger' | 'watch' | 'ok' for a ratio (None → None)."""
        if ratio is None:
            return None
        if ratio > self.danger_high or ratio < self.danger_low:
            return "danger"
        if ratio > self.sweet_high or ratio < self.sweet_low:
            return "watch"
        return "ok"


def resolve_specs(category) -> list[AcwrSpec]:
    """The category's configured ACWR variables, or the system default."""
    cfg = (getattr(category, "load_config", None) or {}).get("acwr") or {}
    variables = cfg.get("variables") or []
    if not variables:
        return [AcwrSpec.from_dict(DEFAULT_SPEC)]
    return [AcwrSpec.from_dict(v) for v in variables]


def moving_avg_ratio(acute_total, chronic_total, acute_days, chronic_days):
    """Acute total ÷ chronic total scaled to the acute window. Pure."""
    scaled = chronic_total * acute_days / chronic_days
    return round(acute_total / scaled, 2) if scaled > 0 else None


def ewma_ratio(daily_oldest_to_newest, acute_days, chronic_days):
    """EWMA(acute) ÷ EWMA(chronic) over a zero-filled daily series. Pure."""
    a = ewma(daily_oldest_to_newest, acute_days)
    c = ewma(daily_oldest_to_newest, chronic_days)
    if not c:
        return None
    return round(a / c, 2)


def gps_templates(category) -> list:
    return list(
        ExamTemplate.objects.filter(
            slug__in=_GPS_SLUGS, applicable_categories=category, is_active_version=True,
        ).distinct()
    )


def compute_acwr(player_ids, category, spec: AcwrSpec, *, now=None, templates=None) -> dict:
    """Per-player ACWR for one spec.

    Returns ``{player_id: {ratio, acute, chronic_week, band, last}}``; players
    with no usable GPS in the window are omitted (ratio would be undefined)."""
    now = now or timezone.now()
    templates = templates if templates is not None else gps_templates(category)
    if not templates or not player_ids:
        return {}

    since = now - timedelta(days=spec.chronic_days)
    acute_cut = now - timedelta(days=spec.acute_days)
    rows = ExamResult.objects.filter(
        player_id__in=player_ids, template__in=templates, recorded_at__gte=since,
    ).values_list("player_id", "recorded_at", "result_data")

    acute_total: dict[Any, float] = {}
    chronic_total: dict[Any, float] = {}
    last: dict[Any, Any] = {}
    daily: dict[Any, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for pid, rec, data in rows:
        v = _coerce((data or {}).get(spec.field))
        if v is None:
            continue
        chronic_total[pid] = chronic_total.get(pid, 0.0) + v
        if rec >= acute_cut:
            acute_total[pid] = acute_total.get(pid, 0.0) + v
        if pid not in last or rec > last[pid]:
            last[pid] = rec
        if spec.method == "ewma":
            # day 0 = today … chronic_days-1 = oldest day in window
            daily[pid][(now - rec).days] += v

    out: dict = {}
    for pid in set(chronic_total) | set(daily):
        if spec.method == "ewma":
            series = [daily[pid].get(d, 0.0) for d in range(spec.chronic_days - 1, -1, -1)]
            ratio = ewma_ratio(series, spec.acute_days, spec.chronic_days)
        else:
            ratio = moving_avg_ratio(
                acute_total.get(pid, 0.0), chronic_total.get(pid, 0.0),
                spec.acute_days, spec.chronic_days,
            )
        if ratio is None:
            continue
        out[pid] = {
            "ratio": ratio,
            "acute": acute_total.get(pid, 0.0),
            "chronic_week": chronic_total.get(pid, 0.0) * spec.acute_days / spec.chronic_days,
            "band": spec.band(ratio),
            "last": timezone.localtime(last[pid]).date().isoformat() if pid in last else None,
        }
    return out
