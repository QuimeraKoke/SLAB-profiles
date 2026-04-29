"""Helpers that materialize `ExamTemplate.config_schema` payloads from
higher-level descriptions.

The first builder, `build_segmented_fields`, takes a list of metrics and a
list of segments (e.g. match phases, time intervals, body sides) and produces:

  * one `number` field per (metric × segment), keyed `{metric.key}_{segment.suffix}`
  * one `calculated` aggregate field per metric, keyed `{metric.key}_total`,
    with a formula that uses `coalesce(..., 0)` so missing segments don't
    blow up the whole-match value.

Use it from a management command, an admin action, or a future API endpoint.
The helper is pure — it just returns dicts. No DB writes happen here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

# What aggregate to materialize across segments.
#   sum   — coalesce(p1, 0) + coalesce(p2, 0) + ...           (totals)
#   max   — max(coalesce(p1, 0), coalesce(p2, 0), ...)         (peaks; assumes ≥0)
#   last  — first non-null walking right-to-left through segments (snapshots)
#   none  — no aggregate field generated
AggregateMode = Literal["sum", "max", "last", "none"]


@dataclass(frozen=True)
class Segment:
    """One slice of an observation (match phase, time interval, body side, …)."""

    suffix: str   # appended to each metric key, e.g. "p1"
    label: str    # human label, e.g. "Primer tiempo"


@dataclass(frozen=True)
class Metric:
    """One thing being measured. Materializes into one field per segment plus
    (optionally) one calculated aggregate field."""

    key: str
    label: str
    unit: str = ""
    group: str = ""
    aggregate: AggregateMode = "sum"
    chart_type: str = ""
    required: bool = False


_AGGREGATE_LABELS: dict[AggregateMode, str] = {
    "sum": "total",
    "max": "máx.",
    "last": "último",
}


def _aggregate_formula(metric: Metric, segments: list[Segment]) -> str:
    bracketed = [f"[{metric.key}_{s.suffix}]" for s in segments]
    if metric.aggregate == "sum":
        return " + ".join(f"coalesce({b}, 0)" for b in bracketed)
    if metric.aggregate == "max":
        # Assumes the metric is non-negative (true for distances, velocities,
        # counts). For metrics that can be negative, write the field manually.
        inner = ", ".join(f"coalesce({b}, 0)" for b in bracketed)
        return f"max({inner})"
    if metric.aggregate == "last":
        # First non-null when read right-to-left across segments.
        return f"coalesce({', '.join(reversed(bracketed))})"
    raise ValueError(f"Unsupported aggregate mode: {metric.aggregate!r}")


def _segment_field(metric: Metric, segment: Segment) -> dict:
    payload: dict = {
        "key": f"{metric.key}_{segment.suffix}",
        "label": f"{metric.label} – {segment.label}",
        "type": "number",
        "group": metric.group or metric.label,
    }
    if metric.unit:
        payload["unit"] = metric.unit
    if metric.chart_type:
        payload["chart_type"] = metric.chart_type
    if metric.required:
        payload["required"] = True
    return payload


def _aggregate_field(metric: Metric, segments: list[Segment]) -> dict:
    label_suffix = _AGGREGATE_LABELS[metric.aggregate]
    payload: dict = {
        "key": f"{metric.key}_total",
        "label": f"{metric.label} ({label_suffix})",
        "type": "calculated",
        "formula": _aggregate_formula(metric, segments),
        "group": metric.group or metric.label,
    }
    if metric.unit:
        payload["unit"] = metric.unit
    if metric.chart_type:
        payload["chart_type"] = metric.chart_type
    return payload


def build_segmented_fields(
    metrics: Iterable[Metric],
    segments: Iterable[Segment],
    *,
    extra_fields: Iterable[dict] | None = None,
) -> list[dict]:
    """Generate a `config_schema.fields[]` payload from metric × segment specs.

    `extra_fields` is appended verbatim at the end — useful when the caller
    needs custom calculated fields the generator can't express (e.g. rate
    metrics computed from `dist_total / dur_total`).
    """
    metrics = list(metrics)
    segments = list(segments)
    if not segments:
        raise ValueError("At least one segment is required")
    if not metrics:
        raise ValueError("At least one metric is required")

    fields: list[dict] = []
    for metric in metrics:
        for segment in segments:
            fields.append(_segment_field(metric, segment))
        if metric.aggregate != "none":
            fields.append(_aggregate_field(metric, segments))

    if extra_fields:
        fields.extend(extra_fields)
    return fields
