"""Deterministic analytical layer for the per-player Resumen report.

Computes the hard numbers the report's narrative interprets (the LLM never
invents analytics — it reads these). Three pillars:

  * match_load — per-metric trend over the player's match-GPS history + the
    Pearson correlations between those metrics (which variables co-move).
  * training  — ACWR (acute 7d ÷ chronic 28d-weekly, reusing the app's
    `_player_acwr`), a weekly ACWR trend, and current microcycle load vs the
    prior microcycles.
  * position  — the player benchmarked against same-position peers
    (percentile + position average), reusing `peer_comparison`.

All builders degrade gracefully (empty / None) when GPS data is sparse.
"""
from __future__ import annotations

from typing import Any

from core.models import Player
from exams.models import ExamResult, ExamTemplate

_GPS_MATCH_SLUG = "gps_rendimiento_fisico_de_partido"
_GPS_TRAIN_SLUG = "gps_entrenamiento"

# Core match-GPS metrics for trends + correlations (key, label, unit).
_MATCH_METRICS: list[tuple[str, str, str]] = [
    ("tot_dist_total", "Distancia total", "m"),
    ("hsr_total", "HSR (>19,8 km/h)", "m"),
    ("sprint_total", "Sprint (>25 km/h)", "m"),
    ("hiaa_total", "HIAA", "n"),
    ("hmld_total", "HMLD", "m"),
    ("acc_dec_total", "Acc+Dec ≥3", "n"),
    ("player_load_total", "Player Load", "a.u."),
    ("max_vel_total", "Vel. máxima", "km/h"),
]
# The headline load metric whose trend + co-movers lead the analysis.
_PRIMARY_MATCH_METRIC = "tot_dist_total"
# Position-context metrics (subset of match metrics that read well as peer
# benchmarks).
_POSITION_METRICS = ["tot_dist_total", "hsr_total", "hiaa_total", "max_vel_total"]

_STRONG_R = 0.6   # |r| at/above which a correlation is "strong"
_MIN_SERIES = 4   # min paired points for a meaningful correlation/trend


def build_player_analysis(player: Player) -> dict[str, Any]:
    """Assemble the analysis payload for `player`. Never raises."""
    match_tpl = _active_template(_GPS_MATCH_SLUG, player)
    train_tpl = _active_template(_GPS_TRAIN_SLUG, player)
    return {
        "match_load": _match_load(player, match_tpl),
        "training": _training(player, train_tpl, match_tpl),
        "position": _position_context(player, match_tpl),
    }


# ─── helpers ──────────────────────────────────────────────────────────────


def _active_template(slug: str, player: Player) -> ExamTemplate | None:
    club = player.category.club if player.category_id else None
    qs = ExamTemplate.objects.filter(slug=slug)
    if club is not None:
        qs = qs.filter(department__club=club)
    return qs.order_by("-is_active_version", "-version").first()


def _coerce(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < _MIN_SERIES:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def _trend(values: list[float]) -> dict[str, Any] | None:
    """Least-squares slope over the reading index + first-third → last-third
    percent change. Direction with a small deadband so noise reads 'flat'."""
    n = len(values)
    if n < _MIN_SERIES:
        return None
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(values) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / sxx
    k = max(1, n // 3)
    early = sum(values[:k]) / k
    late = sum(values[-k:]) / k
    pct = ((late - early) / early * 100) if early else None
    # Deadband relative to the mean so a tiny slope reads flat.
    thresh = abs(my) * 0.01
    direction = "up" if slope > thresh else "down" if slope < -thresh else "flat"
    return {
        "direction": direction,
        "pct_change": round(pct, 1) if pct is not None else None,
        "early": round(early, 1),
        "late": round(late, 1),
    }


def _match_load(player: Player, match_tpl: ExamTemplate | None) -> dict[str, Any]:
    if match_tpl is None:
        return {"n_matches": 0, "metrics": [], "correlations": [], "primary": None}
    rows = list(
        ExamResult.objects
        .filter(player=player, template__family_id=match_tpl.family_id)
        .order_by("recorded_at")
        .values_list("result_data", flat=True)
    )
    n = len(rows)
    # Per-metric chronological series (None-safe).
    series: dict[str, list[float | None]] = {
        key: [_coerce((rd or {}).get(key)) for rd in rows] for key, _, _ in _MATCH_METRICS
    }

    metrics_out: list[dict[str, Any]] = []
    for key, label, unit in _MATCH_METRICS:
        vals = [v for v in series[key] if v is not None]
        if not vals:
            continue
        metrics_out.append({
            "key": key, "label": label, "unit": unit,
            "latest": round(vals[-1], 1),
            "mean": round(sum(vals) / len(vals), 1),
            "trend": _trend(vals),
        })

    # Pairwise Pearson over matches where BOTH metrics are present.
    correlations: list[dict[str, Any]] = []
    keys = [k for k, _, _ in _MATCH_METRICS]
    label_by = {k: lbl for k, lbl, _ in _MATCH_METRICS}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            pairs = [(x, y) for x, y in zip(series[a], series[b]) if x is not None and y is not None]
            if len(pairs) < _MIN_SERIES:
                continue
            r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
            if r is None or abs(r) < _STRONG_R:
                continue
            correlations.append({
                "a": a, "a_label": label_by[a],
                "b": b, "b_label": label_by[b],
                "r": round(r, 2), "n": len(pairs),
            })
    correlations.sort(key=lambda c: abs(c["r"]), reverse=True)

    # Headline: the primary load metric's trend + its strongest co-movers.
    primary = None
    pmeta = next((m for m in metrics_out if m["key"] == _PRIMARY_MATCH_METRIC), None)
    if pmeta:
        comovers = [
            {"label": c["b_label"] if c["a"] == _PRIMARY_MATCH_METRIC else c["a_label"], "r": c["r"]}
            for c in correlations
            if _PRIMARY_MATCH_METRIC in (c["a"], c["b"])
        ]
        primary = {**pmeta, "comovers": comovers[:4]}

    return {
        "n_matches": n,
        "metrics": metrics_out,
        "correlations": correlations[:8],
        "primary": primary,
    }


def _weekly_load(player: Player, match_tpl, train_tpl) -> list[dict[str, Any]]:
    """Combined match+training distance per ISO week (newest last). Training
    also tracks player_load. Used for microcycle comparison + the ACWR trend."""
    weeks: dict[tuple[int, int], dict[str, float]] = {}

    def add(qs, dist_key, load_key=None):
        for recorded_at, rd in qs:
            iso = recorded_at.isocalendar()
            wk = (iso[0], iso[1])
            bucket = weeks.setdefault(wk, {"dist": 0.0, "load": 0.0, "sessions": 0})
            d = _coerce((rd or {}).get(dist_key))
            if d is not None:
                bucket["dist"] += d
            if load_key:
                ld = _coerce((rd or {}).get(load_key))
                if ld is not None:
                    bucket["load"] += ld
                bucket["sessions"] += 1

    if train_tpl is not None:
        add(
            ExamResult.objects.filter(player=player, template__family_id=train_tpl.family_id)
            .values_list("recorded_at", "result_data"),
            "tot_dist", "player_load",
        )
    if match_tpl is not None:
        add(
            ExamResult.objects.filter(player=player, template__family_id=match_tpl.family_id)
            .values_list("recorded_at", "result_data"),
            "tot_dist_total",
        )

    ordered = sorted(weeks.items())
    return [
        {
            "week": f"{yr}-W{wknum:02d}",
            "dist": round(b["dist"], 0),
            "load": round(b["load"], 0),
            "sessions": b["sessions"],
        }
        for (yr, wknum), b in ordered
    ]


def _training(player: Player, train_tpl, match_tpl) -> dict[str, Any]:
    from api.roster import _player_acwr

    acwr_val = None
    if player.category_id:
        acwr_val = _player_acwr(player.category, [player.id]).get(player.id)

    weekly = _weekly_load(player, match_tpl, train_tpl)

    # Microcycle comparison: current (last) week vs the mean of the prior up-to-3.
    micro = None
    train_weeks = [w for w in weekly if w["sessions"] > 0]
    if len(train_weeks) >= 2:
        current = train_weeks[-1]
        prior = train_weeks[-4:-1] if len(train_weeks) >= 4 else train_weeks[:-1]
        prior_avg = sum(w["load"] for w in prior) / len(prior) if prior else 0
        pct = ((current["load"] - prior_avg) / prior_avg * 100) if prior_avg else None
        micro = {
            "current_load": current["load"],
            "current_week": current["week"],
            "prior_avg_load": round(prior_avg, 0),
            "prior_weeks": len(prior),
            "pct_change": round(pct, 1) if pct is not None else None,
        }

    return {
        "acwr": _acwr_block(acwr_val),
        "weekly": weekly[-8:],
        "microcycle": micro,
    }


def _acwr_block(value: float | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if value >= 1.5:
        band, label = "danger", "Pico de carga — riesgo de lesión"
    elif value > 1.3:
        band, label = "high", "Sobre el rango óptimo"
    elif value < 0.8:
        band, label = "low", "Bajo el rango óptimo (descarga)"
    else:
        band, label = "ok", "Rango óptimo (0,8–1,3)"
    return {"value": value, "band": band, "label": label}


def _position_context(player: Player, match_tpl: ExamTemplate | None) -> dict[str, Any]:
    if match_tpl is None or not player.category_id or player.position_id is None:
        return {"position_label": None, "metrics": []}
    from dashboards.references import peer_comparison

    # Latest match reading per field for this player → the value we benchmark.
    latest = (
        ExamResult.objects
        .filter(player=player, template__family_id=match_tpl.family_id)
        .order_by("-recorded_at")
        .values_list("result_data", flat=True)
        .first()
    ) or {}

    position_name = player.position.name
    label_by = {k: lbl for k, lbl, _ in _MATCH_METRICS}
    unit_by = {k: u for k, _, u in _MATCH_METRICS}

    metrics: list[dict[str, Any]] = []
    for key in _POSITION_METRICS:
        value = _coerce(latest.get(key))
        if value is None:
            continue
        cmp = peer_comparison(match_tpl, key, player.category, value, position=position_name)
        pos = (cmp or {}).get("position")
        if not pos:
            continue
        metrics.append({
            "key": key, "label": label_by.get(key, key), "unit": unit_by.get(key, ""),
            "value": round(value, 1),
            "position_avg": pos["avg"],
            "percentile": pos["percentile"],
            "n": pos["n"],
        })

    return {"position_label": position_name, "metrics": metrics}
