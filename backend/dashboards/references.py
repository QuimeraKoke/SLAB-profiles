"""Reference data + deterministic analytics for player metrics.

Single source of truth, split by origin:
- **internal bands** → `ExamTemplate.config_schema.reference_ranges` (the club's
  own normal/low/high). Passed to the agent, never retyped into a KB.
- **external norms** → `MetricReference` rows (ISAK, league, literature),
  each tagged with its `source`.
- **methodology** → the agent KB (how to read; no raw numbers).

All numbers (band classification, percentile-vs-squad, percentile/Z-score
vs an external norm, trend slope) are computed HERE, deterministically, and
handed to the agents + charts. The LLM interprets them; it never computes
them. `build_metric_references(...)` assembles the per-metric block that gets
attached to the report payloads.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ─── Internal bands (from config_schema.reference_ranges) ──────────────


def band_for_value(value: float | None, reference_ranges: list[dict] | None) -> str | None:
    """Label of the band `value` falls in. Bands are [{min?, max?, label}];
    an absent edge is open-ended."""
    if value is None or not reference_ranges:
        return None
    for band in reference_ranges:
        lo, hi = band.get("min"), band.get("max")
        if lo is not None and value < lo:
            continue
        if hi is not None and value > hi:
            continue
        return band.get("label")
    return None


def _internal_bands(reference_ranges: list[dict] | None) -> list[dict] | None:
    if not reference_ranges:
        return None
    return [
        {"label": b.get("label"), "min": b.get("min"), "max": b.get("max")}
        for b in reference_ranges
    ]


# ─── External norms (MetricReference) + comparison stats ───────────────


def _external_references(
    template_id, field_key: str, current_value: float | None,
    *, sex: str | None, position: str | None,
) -> list[dict]:
    from dashboards.models import MetricReference

    rows = MetricReference.objects.filter(
        template_id=template_id, field_key=field_key, is_active=True,
    )
    out: list[dict] = []
    for r in rows:
        if r.sex and sex and r.sex != sex:
            continue
        if r.position and position and r.position != position:
            continue
        entry: dict[str, Any] = {"source": r.source}
        if r.range_min is not None or r.range_max is not None:
            entry["range"] = {"min": r.range_min, "max": r.range_max}
        if r.mean is not None:
            entry["mean"] = r.mean
        if r.sd is not None:
            entry["sd"] = r.sd
        if r.percentiles:
            entry["percentiles"] = r.percentiles
        if r.unit:
            entry["unit"] = r.unit
        if r.note:
            entry["note"] = r.note
        comp = _compare_to_norm(current_value, r)
        if comp:
            entry["comparison"] = comp
        out.append(entry)
    return out


def _compare_to_norm(value: float | None, ref) -> dict | None:
    """Where `value` sits vs one external norm: Z-score + percentile (from
    mean/SD), or percentile (interpolated from a percentile map), and/or a
    within/below/above range verdict. All computed, never guessed."""
    if value is None:
        return None
    comp: dict[str, Any] = {}

    if ref.mean is not None and ref.sd:
        z = (value - ref.mean) / ref.sd
        comp["z_score"] = round(z, 2)
        comp["percentile"] = round(_normal_cdf(z) * 100)
    elif ref.percentiles:
        pct = _percentile_from_map(value, ref.percentiles)
        if pct is not None:
            comp["percentile"] = round(pct)

    if ref.range_min is not None or ref.range_max is not None:
        if ref.range_min is not None and value < ref.range_min:
            comp["vs_range"] = "below"
        elif ref.range_max is not None and value > ref.range_max:
            comp["vs_range"] = "above"
        else:
            comp["vs_range"] = "within"

    return comp or None


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _percentile_from_map(value: float, percentiles: dict) -> float | None:
    """Piecewise-linear interpolation of `value`'s percentile from a
    {"p5": .., "p50": .., ...} map. Clamps outside the provided range."""
    pts: list[tuple[float, float]] = []
    for key, v in percentiles.items():
        num = _coerce(v)
        try:
            p = float(str(key).lower().lstrip("p"))
        except ValueError:
            continue
        if num is not None:
            pts.append((num, p))
    if len(pts) < 2:
        return None
    pts.sort(key=lambda t: t[0])
    if value <= pts[0][0]:
        return pts[0][1]
    if value >= pts[-1][0]:
        return pts[-1][1]
    for (v0, p0), (v1, p1) in zip(pts, pts[1:]):
        if v0 <= value <= v1:
            frac = 0.0 if v1 == v0 else (value - v0) / (v1 - v0)
            return p0 + frac * (p1 - p0)
    return None


# ─── Percentile vs the player's own squad ──────────────────────────────


def squad_percentile(
    template, field_key: str, category, value: float | None, *, min_n: int = 3,
) -> dict | None:
    """Percentile rank of `value` among the latest reading per player in the
    same category for this metric. None if fewer than `min_n` players have a
    value (a percentile off 1-2 teammates is noise)."""
    if value is None or category is None:
        return None
    from exams.models import ExamResult

    rows = (
        ExamResult.objects
        .filter(template=template, player__category=category)
        .order_by("player_id", "-recorded_at")
        .distinct("player_id")
        .values_list("result_data", flat=True)
    )
    vals: list[float] = []
    for data in rows:
        v = _coerce((data or {}).get(field_key))
        if v is not None:
            vals.append(v)
    if len(vals) < min_n:
        return None
    at_or_below = sum(1 for v in vals if v <= value)
    return {"percentile": round(at_or_below / len(vals) * 100), "n": len(vals)}


def peer_comparison(
    template, field_key: str, category, value: float | None, *,
    position: str | None = None, min_n: int = 3, min_n_pos: int = 2,
) -> dict | None:
    """Team + same-position comparison of `value` against the latest reading
    per player in `category` for this metric.

    Returns ``{"team": {avg, percentile, n}, "position": {avg, percentile, n,
    label}}`` — each block omitted below its minimum count, None when there's
    no team block. Same-position grouping is by Position.name (positional peers).
    """
    if value is None or category is None:
        return None
    from core.models import Player
    from exams.models import ExamResult

    rows = (
        ExamResult.objects
        .filter(template=template, player__category=category)
        .order_by("player_id", "-recorded_at")
        .distinct("player_id")
        .values_list("player_id", "result_data")
    )
    pvals: dict[Any, float] = {}
    for pid, data in rows:
        v = _coerce((data or {}).get(field_key))
        if v is not None:
            pvals.setdefault(pid, v)
    if not pvals:
        return None

    def _stats(vals: list[float]) -> dict:
        n = len(vals)
        at_or_below = sum(1 for v in vals if v <= value)
        return {
            "avg": round(sum(vals) / n, 2),
            "percentile": round(at_or_below / n * 100),
            "n": n,
        }

    out: dict[str, Any] = {}
    team_vals = list(pvals.values())
    if len(team_vals) >= min_n:
        out["team"] = _stats(team_vals)

    if position:
        pos_pids = set(
            Player.objects
            .filter(category=category, position__name=position)
            .values_list("id", flat=True)
        )
        pos_vals = [v for pid, v in pvals.items() if pid in pos_pids]
        if len(pos_vals) >= min_n_pos:
            block = _stats(pos_vals)
            block["label"] = position
            out["position"] = block

    return out or None


def peer_averages(
    template, field_key: str, category, *,
    position: str | None = None, min_n: int = 3, min_n_pos: int = 2,
) -> dict | None:
    """Team + same-position AVERAGE of the latest reading per player for a
    metric — for chart reference lines (no player value needed, so it works
    for GPS and any other field). Returns ``{"team": float|None,
    "position": {"avg": float, "label": str}|None}`` or None when no data.
    """
    if category is None:
        return None
    from core.models import Player
    from exams.models import ExamResult

    rows = (
        ExamResult.objects
        .filter(template=template, player__category=category)
        .order_by("player_id", "-recorded_at")
        .distinct("player_id")
        .values_list("player_id", "result_data")
    )
    pvals: dict[Any, float] = {}
    for pid, data in rows:
        v = _coerce((data or {}).get(field_key))
        if v is not None:
            pvals.setdefault(pid, v)
    if not pvals:
        return None

    out: dict[str, Any] = {}
    team_vals = list(pvals.values())
    if len(team_vals) >= min_n:
        out["team"] = round(sum(team_vals) / len(team_vals), 2)
    if position:
        pos_pids = set(
            Player.objects
            .filter(category=category, position__name=position)
            .values_list("id", flat=True)
        )
        pos_vals = [v for pid, v in pvals.items() if pid in pos_pids]
        if len(pos_vals) >= min_n_pos:
            out["position"] = {
                "avg": round(sum(pos_vals) / len(pos_vals), 2), "label": position,
            }
    return out or None


# ─── Trend ─────────────────────────────────────────────────────────────


def trend_slope(history: list[dict]) -> dict | None:
    """Least-squares slope (units per day) over a metric's history points
    [{value, recorded_at}]. None if <3 points."""
    pts = [
        (h["recorded_at"], _coerce(h.get("value")))
        for h in (history or [])
        if h.get("value") is not None
    ]
    pts = [(t, v) for t, v in pts if v is not None and t is not None]
    if len(pts) < 3:
        return None
    t0 = min(t for t, _ in pts)
    xs = [(t - t0).total_seconds() / 86400.0 for t, _ in pts]
    ys = [v for _, v in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return {"per_day": round(slope, 4), "direction": "up" if slope > 0 else "down" if slope < 0 else "flat"}


# ─── Assembly ──────────────────────────────────────────────────────────


def build_metric_references(
    template, field_key: str, spec: dict | None, current_value: float | None,
    *, sex: str | None = None, position: str | None = None, category=None,
    history: list[dict] | None = None,
) -> dict:
    """Assemble the per-metric reference + analytics block for the agent
    payload: internal band, external norms (source-labeled, with computed
    percentile/Z), percentile-vs-squad, and trend. Empty keys omitted."""
    block: dict[str, Any] = {}

    bands = _internal_bands((spec or {}).get("reference_ranges"))
    if bands:
        block["internal_band"] = bands
        cb = band_for_value(current_value, (spec or {}).get("reference_ranges"))
        if cb:
            block["current_band"] = cb

    ext = _external_references(
        template.id, field_key, current_value, sex=sex, position=position,
    )
    if ext:
        block["external"] = ext

    peer = peer_comparison(
        template, field_key, category, current_value, position=position,
    )
    if peer:
        block["peer"] = peer
        # Back-compat: keep squad_percentile (team) for existing consumers.
        if "team" in peer:
            block["squad_percentile"] = {
                "percentile": peer["team"]["percentile"], "n": peer["team"]["n"],
            }

    tr = trend_slope(history) if history else None
    if tr:
        block["trend"] = tr

    return block


def _coerce(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return None if (v != v or v in (float("inf"), float("-inf"))) else v
