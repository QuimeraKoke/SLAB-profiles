"""Per-category reference bands for charts, tables and player state.

`AlertRule.config["ranges"]` lets a band rule carry its own thresholds so a
Sub 11 is not judged with a Sub 20's numbers — that is what the evaluator reads
when it decides whether to fire. But the DISPLAY side never learned: every
widget serialised `ExamTemplate.config_schema…reference_ranges`, which is one
shared scale for every category. So after seeding the club's real thresholds,
alerts became correct per category while the band DRAWN on the chart stayed the
shared default, and a dashboard that paints a Sub 20's band over a Sub 11 looks
right — which is what makes it worse than no dashboard.

Why a ContextVar
----------------
`_field_meta` is called from 11 resolvers in `aggregation.py` and 3 in
`team_aggregation.py`, none of which take a category: the player resolvers get
a `player_id`, the team ones get the category but pass only `(template, key)`
down. Threading a parameter through all fourteen would touch every resolver
signature for one lookup.

The codebase already solves this shape twice the same way — the roster's
"include secondary" flag in `team_aggregation`, and column width in the PDF
renderers. So the scope is set once by the dispatcher and read where the band
is serialised.

Empty context = the field's own bands, so nothing changes for a caller that
does not opt in.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

# (template family_id or id, field_key) → the category's own bands.
# Keyed on `family_id` so a template version bump does not orphan the rules:
# an `AlertRule` points at one version, and the widget may read another.
_BANDS: ContextVar[dict[tuple[Any, str], list[dict]] | None] = ContextVar(
    "category_reference_bands", default=None,
)


def build(category_id: UUID | None) -> dict[tuple[Any, str], list[dict]]:
    """One query: every band rule of this category that carries thresholds."""
    if category_id is None:
        return {}
    from goals.models import AlertRule, AlertRuleKind

    out: dict[tuple[Any, str], list[dict]] = {}
    rules = (AlertRule.objects
             .filter(category_id=category_id, kind=AlertRuleKind.BAND,
                     is_active=True)
             .select_related("template")
             .only("config", "field_key", "template__family_id", "template__id"))
    for rule in rules:
        ranges = (rule.config or {}).get("ranges")
        if not isinstance(ranges, list) or not ranges:
            continue
        clave = rule.template.family_id or rule.template_id
        out[(clave, rule.field_key)] = list(ranges)
    return out


@contextmanager
def scope(category_id: UUID | None):
    """Make `category_id`'s bands the ones charts draw, for this block."""
    token = _BANDS.set(build(category_id))
    try:
        yield
    finally:
        _BANDS.reset(token)


def for_field(template, field_key: str, fallback: list[dict] | None) -> list[dict]:
    """The bands to draw: the category's if it has its own, else the field's."""
    mapa = _BANDS.get()
    if not mapa:
        return list(fallback or [])
    clave = (getattr(template, "family_id", None) or getattr(template, "id", None),
             field_key)
    return list(mapa.get(clave) or fallback or [])
