"""In-app Alert & Threshold editor (§1.g) — schemas, serialization, form
metadata and the side-effect-free backtest preview.

The endpoints in `routers.py` stay thin: they resolve club/category scope and
apply the Editor-role permission gate, then delegate here. `run_backtest`
builds an *unsaved* AlertRule and reuses the live firing predicate
(`goals.evaluator._rule_fire_decision`), so the "would have fired N times"
preview is exactly what the engine would do.
"""
from __future__ import annotations

from ninja import Schema

from goals.evaluator import backtest_rule as _backtest_rule
from goals.models import AlertRule, AlertRuleKind, AlertSeverity

_NUMERIC_TYPES = {"number", "calculated"}
# Canonical microcycle labels the scope picker offers (matches exams.microcycle).
_MICROCYCLE_DAYS = [
    "MD-6", "MD-5", "MD-4", "MD-3", "MD-2", "MD-1", "MD", "MD+1", "MD+2", "MD+3",
]


# ── Schemas ─────────────────────────────────────────────────────────────────

class RuleWriteIn(Schema):
    template_id: str
    field_key: str
    kind: str
    category_id: str | None = None
    config: dict = {}
    scope: dict = {}
    severity: str = AlertSeverity.WARNING
    message_template: str = ""
    is_active: bool = True


class RuleUpdateIn(Schema):
    field_key: str | None = None
    kind: str | None = None
    category_id: str | None = None
    config: dict | None = None
    scope: dict | None = None
    severity: str | None = None
    message_template: str | None = None
    is_active: bool | None = None


class BacktestIn(Schema):
    template_id: str
    field_key: str
    kind: str
    category_id: str | None = None
    config: dict = {}
    scope: dict = {}
    severity: str = AlertSeverity.WARNING
    days: int = 30


# ── ACWR (acute:chronic) configuration ─────────────────────────────────────────

class AcwrVariableIn(Schema):
    field: str
    label: str = ""
    acute_days: int = 7
    chronic_days: int = 28
    method: str = "moving_avg"  # "moving_avg" | "ewma"
    # Target band (green) low/high, and the outer risk limits (red) low/high.
    sweet_low: float = 0.8
    sweet_high: float = 1.3
    danger_low: float = 0.7
    danger_high: float = 1.5
    alert: bool = False
    severity: str = AlertSeverity.WARNING


class AcwrConfigIn(Schema):
    category_id: str
    variables: list[AcwrVariableIn] = []


def build_acwr_config(category) -> dict:
    """Current ACWR config for a category (defaults when unconfigured) + the
    GPS numeric fields available as monitored variables + picker vocab."""
    from dataclasses import asdict
    from dashboards.acwr import resolve_specs, gps_templates

    variables = [asdict(s) for s in resolve_specs(category)]

    seen: set[str] = set()
    fields: list[dict] = []
    for t in gps_templates(category):
        for f in (t.config_schema or {}).get("fields", []) or []:
            key = f.get("key")
            if f.get("type") in _NUMERIC_TYPES and key and key not in seen:
                seen.add(key)
                fields.append(
                    {"key": key, "label": f.get("label") or key, "unit": f.get("unit", "")}
                )
    return {
        "variables": variables,
        "available_fields": fields,
        "methods": [
            {"value": "moving_avg", "label": "Media móvil (agudo ÷ crónico)"},
            {"value": "ewma", "label": "EWMA (exponencial, Williams)"},
        ],
        "severities": [s.value for s in AlertSeverity],
    }


def save_acwr_config(category, variables: list[dict]) -> None:
    """Persist the monitored ACWR variables into ``Category.load_config['acwr']``
    (label backfilled from the field key when blank)."""
    clean: list[dict] = []
    for v in variables:
        v = dict(v)
        if not v.get("label"):
            v["label"] = v.get("field", "")
        clean.append(v)
    cfg = dict(category.load_config or {})
    cfg["acwr"] = {"variables": clean}
    category.load_config = cfg
    category.save(update_fields=["load_config"])


# ── Serialization ─────────────────────────────────────────────────────────────

def _field_label(template, field_key: str) -> str:
    for f in (template.config_schema or {}).get("fields", []) or []:
        if isinstance(f, dict) and f.get("key") == field_key:
            return f.get("label") or field_key
    return field_key


def serialize_rule(rule: AlertRule) -> dict:
    return {
        "id": str(rule.id),
        "template_id": str(rule.template_id),
        "template_name": rule.template.name,
        "field_key": rule.field_key,
        "field_label": _field_label(rule.template, rule.field_key),
        "category_id": str(rule.category_id) if rule.category_id else None,
        "kind": rule.kind,
        "config": rule.config or {},
        "scope": rule.scope or {},
        "severity": rule.severity,
        "message_template": rule.message_template or "",
        "is_active": rule.is_active,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


# ── Form metadata ─────────────────────────────────────────────────────────────

def build_rule_meta(category) -> dict:
    """Everything the form needs to render for one category: the applicable
    templates with their numeric + band fields, the kind/severity vocab, the
    club's línea (role) values, and the microcycle-day labels."""
    from core.models import Position
    from exams.models import ExamTemplate

    templates = (
        ExamTemplate.objects
        .filter(applicable_categories=category, is_active_version=True)
        .select_related("department")
        .order_by("department__name", "name")
        .distinct()
    )
    tpl_out = []
    for t in templates:
        fields = (t.config_schema or {}).get("fields", []) or []
        numeric, band_fields, session_types = [], [], []
        for f in fields:
            if not isinstance(f, dict) or not f.get("key"):
                continue
            if f.get("type") in _NUMERIC_TYPES:
                numeric.append({
                    "key": f["key"], "label": f.get("label") or f["key"],
                    "unit": f.get("unit", ""),
                    "has_bands": bool(f.get("reference_ranges")),
                })
            if f.get("reference_ranges"):
                band_fields.append({
                    "key": f["key"], "label": f.get("label") or f["key"],
                    "bands": [b.get("label") for b in f["reference_ranges"]
                              if isinstance(b, dict) and b.get("label")],
                })
            if f.get("key") == "tipo_sesion":
                session_types = list(f.get("options") or [])
        tpl_out.append({
            "id": str(t.id), "name": t.name, "department": t.department.name,
            "slug": t.slug, "numeric_fields": numeric,
            "band_fields": band_fields, "session_types": session_types,
        })

    roles = sorted({
        r for r in Position.objects.filter(club=category.club)
        .values_list("role", flat=True) if r
    })
    return {
        "templates": tpl_out,
        "kinds": [{"value": k.value, "label": k.label} for k in AlertRuleKind],
        "severities": [{"value": s.value, "label": s.label} for s in AlertSeverity],
        "roles": roles,
        "microcycle_days": _MICROCYCLE_DAYS,
    }


# ── Backtest ─────────────────────────────────────────────────────────────────

def run_backtest(*, template, category, payload: BacktestIn) -> dict:
    """Validate a draft rule and dry-run it. Raises ValidationError (→ 422)
    when the config is invalid, so the preview never masks a broken rule."""
    rule = AlertRule(
        template=template, category=category, kind=payload.kind,
        field_key=payload.field_key, config=payload.config or {},
        scope=payload.scope or {}, severity=payload.severity or AlertSeverity.WARNING,
    )
    rule.clean()  # field_key numeric? config valid for kind? scope well-formed?
    days = max(1, min(int(payload.days or 30), 365))
    return _backtest_rule(rule, days=days)
