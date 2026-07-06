"""Shared wellness scoring from the real Check-IN data (`checkin_fisico`).

The form mixes scales — recuperación is 1–10, the other four items are 1–5 —
so the 0–100 score normalizes each item by its template-configured `max`
(data-driven, not hardcoded) and averages. Used by both the Equipo roster
and the Centro de mando KPI so they agree.
"""

from __future__ import annotations

from exams.models import ExamResult, ExamTemplate

WELLNESS_SLUG = "checkin_fisico"
# Items that make up the wellness score, with display labels for dimensions.
ITEMS = [
    ("recuperacion", "Recuperación"),
    ("cuerpo", "Cuerpo"),
    ("energia", "Energía"),
    ("animo", "Ánimo"),
    ("sueno", "Sueño"),
]
# Dimensions surfaced as chips on the Centro de mando wellness KPI.
DIMENSIONS = [("sueno", "Sueño"), ("energia", "Energía"), ("animo", "Ánimo")]


def field_max(category) -> dict[str, float]:
    """field_key → configured max for the category's checkin_fisico template
    (e.g. recuperacion→10, cuerpo→5). Empty if the template is absent."""
    t = (
        ExamTemplate.objects.filter(slug=WELLNESS_SLUG, applicable_categories=category).first()
        or ExamTemplate.objects.filter(slug=WELLNESS_SLUG).first()
    )
    out: dict[str, float] = {}
    for f in ((t.config_schema or {}).get("fields") if t else []) or []:
        k = f.get("key")
        if k in dict(ITEMS):
            out[k] = float(f.get("max") or 10)
    return out


def score(data: dict, fmax: dict[str, float]) -> int | None:
    """0–100 wellness for one response: mean of (value ÷ field-max)."""
    fracs = []
    for key, _ in ITEMS:
        v = _coerce((data or {}).get(key))
        mx = fmax.get(key)
        if v is not None and mx:
            fracs.append(min(1.0, v / mx))
    return round(sum(fracs) / len(fracs) * 100) if fracs else None


def dimension_pct(data: dict, key: str, fmax: dict[str, float]) -> int | None:
    v = _coerce((data or {}).get(key))
    mx = fmax.get(key)
    return round(min(1.0, v / mx) * 100) if (v is not None and mx) else None


def recent_by_player(category, player_ids: list, limit: int = 12, since=None,
                     with_dates: bool = False) -> dict:
    """{player_id: [result_data, ...]} newest-first, for the category's
    checkin_fisico responses. With `since` (an aware datetime) it returns every
    reading on/after that instant — a date window; otherwise caps to `limit`.
    With `with_dates=True` each item is a `(recorded_at, result_data)` tuple."""
    tids = list(
        ExamTemplate.objects.filter(slug=WELLNESS_SLUG, applicable_categories=category)
        .values_list("id", flat=True)
    ) or list(ExamTemplate.objects.filter(slug=WELLNESS_SLUG).values_list("id", flat=True))
    out: dict = {}
    if not tids:
        return out
    qs = ExamResult.objects.filter(player_id__in=player_ids, template_id__in=tids)
    if since is not None:
        qs = qs.filter(recorded_at__gte=since)
    rows = qs.order_by("player_id", "-recorded_at").values_list(
        "player_id", "recorded_at", "result_data",
    )
    for pid, rec, data in rows:
        bucket = out.setdefault(pid, [])
        if since is not None or len(bucket) < limit:
            bucket.append((rec, data or {}) if with_dates else (data or {}))
    return out


def _coerce(raw):
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
