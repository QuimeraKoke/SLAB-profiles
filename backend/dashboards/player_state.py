"""Compute a player's materialized metric state.

`ExamResult` is the source of truth; this derives the player's *current*
state from it — latest tracked metrics + the weekly chronic-load monitor —
and is what `PlayerMetricState` stores. Always rebuildable from raw, so a
missed trigger is never fatal (`manage.py rebuild_player_state`).

Player-INTRINSIC only: no squad-relative numbers here (those depend on other
players and stay lazy at read time, per the Phase-1 design).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from .references import band_for_value

logger = logging.getLogger(__name__)


# ─── Weekly chronic-load monitor (German Tapia's thresholds) ────────────
#
# Weekly *total* load = matches + trainings summed over a rolling 7-day
# window. Each concept sums a match-template field + a training-template
# field. Ranges are the standard weekly chronic-load thresholds; `note` is
# the physiological relevance (interpretation context for the físico agent).
# Editable home (admin) can come later — kept as config for Phase 1.
_GPS_MATCH_SLUG = "gps_rendimiento_fisico_de_partido"
_GPS_TRAIN_SLUG = "gps_entrenamiento"

WEEKLY_LOAD_METRICS: list[dict] = [
    {
        "key": "dist_total", "label": "Distancia total", "unit": "m",
        "min": 28000, "max": 35000,
        "fields": {_GPS_MATCH_SLUG: "tot_dist_total", _GPS_TRAIN_SLUG: "tot_dist"},
        "note": "Volumen general; gestión de gasto calórico y fatiga sistémica.",
    },
    {
        "key": "hsr", "label": "HSR > 19,8 km/h", "unit": "m",
        "min": 1800, "max": 2600,
        "fields": {_GPS_MATCH_SLUG: "hsr_total", _GPS_TRAIN_SLUG: "hsr"},
        "note": "Volumen de alta intensidad; acondicionamiento aeróbico de alta potencia.",
    },
    {
        "key": "sprint", "label": "Sprint > 25,2 km/h", "unit": "m",
        "min": 400, "max": 700,
        "fields": {_GPS_MATCH_SLUG: "sprint_total", _GPS_TRAIN_SLUG: "sprint"},
        "note": "Estrés mecánico excéntrico máximo; ligado a riesgo de isquiosurales.",
    },
    {
        "key": "acc", "label": "Aceleraciones ≥3 m/s²", "unit": "n",
        "min": 150, "max": 250,
        "fields": {_GPS_MATCH_SLUG: "acc_total", _GPS_TRAIN_SLUG: "acc"},
        "note": "Costo metabólico y estrés del tejido contráctil; fatiga periférica.",
    },
    {
        "key": "dec", "label": "Desaceleraciones ≥3 m/s²", "unit": "n",
        "min": 150, "max": 250,
        "fields": {_GPS_MATCH_SLUG: "dec_total", _GPS_TRAIN_SLUG: "dec"},
        "note": "Estrés excéntrico de frenado; fatiga periférica.",
    },
]


def compute_weekly_load(player) -> dict | None:
    """Rolling 7-day chronic-load totals (matches + trainings) per concept,
    classified vs the weekly thresholds. Window ends at the player's most
    recent GPS reading (robust to stale data — "their latest week of load").
    None if the player has no GPS readings."""
    from exams.models import ExamResult

    results = list(
        ExamResult.objects
        .filter(player=player, template__slug__in=[_GPS_MATCH_SLUG, _GPS_TRAIN_SLUG])
        .select_related("template")
        .order_by("-recorded_at")
    )
    if not results:
        return None

    to = results[0].recorded_at
    frm = to - timedelta(days=7)
    window = [r for r in results if frm < r.recorded_at <= to]

    metrics: list[dict] = []
    for spec in WEEKLY_LOAD_METRICS:
        total = 0.0
        sessions = 0
        for r in window:
            field_key = spec["fields"].get(r.template.slug)
            if not field_key:
                continue
            v = _coerce((r.result_data or {}).get(field_key))
            if v is not None:
                total += v
                sessions += 1
        if sessions == 0:
            continue
        lo, hi = spec["min"], spec["max"]
        status = "under" if total < lo else "over" if total > hi else "within"
        metrics.append({
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "total": round(total, 1), "sessions": sessions,
            "min": lo, "max": hi, "status": status, "note": spec["note"],
        })

    if not metrics:
        return None
    return {
        "window": {"from": frm.isoformat(), "to": to.isoformat(), "days": 7},
        "metrics": metrics,
    }


# ─── Latest tracked metrics (the "current readings" snapshot) ───────────


def compute_latest_metrics(player) -> list[dict]:
    """Latest value + internal band per tracked field (fields with
    reference_ranges) across the player's templates. The 'all latest info'
    part of the state — cheap, player-intrinsic."""
    from exams.models import ExamResult, ExamTemplate

    if player.category_id is None:
        return []
    templates = ExamTemplate.objects.filter(
        applicable_categories=player.category, is_active_version=True,
    ).distinct()

    out: list[dict] = []
    for t in templates:
        specs = {
            f["key"]: f for f in (t.config_schema or {}).get("fields") or []
            if isinstance(f, dict) and f.get("key") and f.get("reference_ranges")
        }
        if not specs:
            continue
        results = list(
            ExamResult.objects.filter(player=player, template=t).order_by("-recorded_at")
        )
        for field_key, spec in specs.items():
            value = at = None
            for r in results:
                v = _coerce((r.result_data or {}).get(field_key))
                if v is not None:
                    value, at = v, r.recorded_at
                    break
            if value is None:
                continue
            out.append({
                "template": t.name, "field": spec.get("label") or field_key,
                "value": value, "unit": spec.get("unit"),
                "band": band_for_value(value, spec.get("reference_ranges")),
                "recorded_at": at.isoformat() if at else None,
            })
    return out


# ─── Assembly + persistence ─────────────────────────────────────────────


def compute_player_state(player) -> dict:
    return {
        "status": player.status,
        "weekly_load": compute_weekly_load(player),
        "latest": compute_latest_metrics(player),
    }


def upsert_player_state(player):
    """Recompute and persist the player's state. Returns the row."""
    from .models import PlayerMetricState

    state = compute_player_state(player)
    obj, _ = PlayerMetricState.objects.update_or_create(
        player=player,
        defaults={"state": state, "version": PlayerMetricState.STATE_VERSION},
    )
    return obj


def weekly_load_evolution(player) -> list[dict]:
    """Per-concept weekly-load time series across the player's state
    snapshots (oldest → newest), for evolution charts. One pass over
    snapshots; only concepts with ≥2 points (an actual trend) are returned.

    Returns: [{key, label, unit, min, max, points:[{date, value, status}]}].
    """
    snaps = list(player.state_snapshots.all())  # Meta.ordering = captured_on asc
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for snap in snaps:
        for m in ((snap.state or {}).get("weekly_load") or {}).get("metrics", []):
            k = m.get("key")
            if not k:
                continue
            if k not in by_key:
                by_key[k] = {
                    "key": k, "label": m.get("label"), "unit": m.get("unit"),
                    "min": m.get("min"), "max": m.get("max"), "points": [],
                }
                order.append(k)
            by_key[k]["points"].append({
                "date": snap.captured_on.isoformat(),
                "value": m.get("total"), "status": m.get("status"),
            })
    return [by_key[k] for k in order if len(by_key[k]["points"]) >= 2]


def _coerce(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return None if (v != v or v in (float("inf"), float("-inf"))) else v


# ─── Match-load reference (acute / chronic) ─────────────────────────────
#
# Acute / chronic load = the MAXIMUM match-day value over the 7-day / 28-day
# window, counting ONLY matches where the player logged ≥75 GPS-min. Used by
# (1) the training-load chart reference lines and (2) the training-load alert.
# Each training field maps to its match "_total" counterpart.
MIN_MATCH_MINUTES = 75.0
TRAIN_TO_MATCH_FIELD: dict[str, str] = {
    "tot_dist": "tot_dist_total", "tot_dur": "tot_dur_total",
    "player_load": "player_load_total", "max_vel": "max_vel_total",
    "hsr": "hsr_total", "sprint": "sprint_total", "acc": "acc_total",
    "dec": "dec_total", "hiaa": "hiaa_total", "hmld": "hmld_total",
    "mpm": "mpm_total",
}

# Metrics the training-load alert watches — cumulative external-load/volume
# only, per the físico InsightAgent's recommendation (2026-06-19): duration,
# relative intensity (mpm) and peak speed (max_vel) are deliberately excluded.
TRAINING_LOAD_ALERT_METRICS: list[str] = [
    "tot_dist", "player_load", "hsr", "sprint", "acc", "dec", "hiaa", "hmld",
]
TRAINING_LOAD_ALERT_RATIO = 0.85  # fire when a session ≥85% of match reference


def match_load_refs(player_id, anchor, train_fields: list[str]) -> dict[str, dict]:
    """Per training-field acute/chronic match-load reference at `anchor`.

    Returns ``{train_field: {"acute": float|None, "chronic": float|None}}``;
    a value is None when no qualifying match (≥75 GPS-min) sits in that window.
    """
    from django.utils import timezone

    from exams.models import ExamResult

    if timezone.is_naive(anchor):
        anchor = timezone.make_aware(anchor, timezone.get_default_timezone())
    acute_cut = anchor - timedelta(days=7)
    chronic_cut = anchor - timedelta(days=28)

    rows = ExamResult.objects.filter(
        player_id=player_id, template__slug=_GPS_MATCH_SLUG,
        recorded_at__gte=chronic_cut, recorded_at__lte=anchor,
    ).values_list("recorded_at", "result_data")
    qualifying = [
        (rec, data or {}) for rec, data in rows
        if (_coerce((data or {}).get("tot_dur_total")) or 0.0) >= MIN_MATCH_MINUTES
    ]

    out: dict[str, dict] = {}
    for tf in train_fields:
        match_key = TRAIN_TO_MATCH_FIELD.get(tf)
        if not match_key:
            continue
        chronic_vals = [v for v in (_coerce(d.get(match_key)) for _, d in qualifying) if v is not None]
        acute_vals = [
            v for v in (_coerce(d.get(match_key)) for rec, d in qualifying if rec >= acute_cut)
            if v is not None
        ]
        out[tf] = {
            "acute": max(acute_vals) if acute_vals else None,
            "chronic": max(chronic_vals) if chronic_vals else None,
        }
    return out
