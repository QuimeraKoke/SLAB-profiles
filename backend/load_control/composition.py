"""Composición corporal — "¿Cómo evoluciona músculo, grasa, Σ pliegues?"
(question 9 of the club's brief).

The club's own artifact ("Antropometría") is the spec, metric for metric:
peso, masa muscular kg / %, masa adiposa kg / %, Σ 6 pliegues and IMO from the
`pentacompartimental` evaluation (the Nutrición anthropometry sheet). The
squad table shows the last reading of each player and the change vs his
previous one; a player shows every metric last-vs-previous, one metric over
time, and every measurement.

Favourable direction is the artifact's (green = more muscle, less fat; the
weight stays grey "because it depends on what changed") — kept here and not
read from the template, where the kg masses carry no direction.

Not weekly: anthropometry is measured every few months, so this reads the
selected CATEGORY (the global picker), like the Evaluaciones grid.
"""
from __future__ import annotations

from typing import Any

from core.models import Category
from exams.models import ExamResult, ExamTemplate

SLUG = "pentacompartimental"

# (key in the payload, template field, label, unit, decimals, direction)
METRICS: list[tuple[str, str, str, str, int, str]] = [
    ("peso", "peso", "Peso", "kg", 1, "neutral"),
    ("mm", "masa_muscular", "Masa muscular", "kg", 1, "up"),
    ("mmp", "masa_muscular_pct", "Masa muscular", "%", 1, "up"),
    ("ma", "masa_adiposa", "Masa adiposa", "kg", 1, "down"),
    ("map", "masa_adiposa_pct", "Masa adiposa", "%", 1, "down"),
    ("pl", "suma_pliegues", "Σ 6 pliegues", "mm", 1, "down"),
    ("imo", "imo", "Índice músculo/óseo", "", 2, "up"),
]
EXTRA = [("talla", "talla")]
# The squad table's columns, as in the club's artifact.
SQUAD_KEYS = ["peso", "mmp", "map", "pl"]


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _measurement(when, data: dict) -> dict:
    d = data or {}
    out = {"date": when.date().isoformat()}
    for key, field, *_ in METRICS:
        out[key] = _num(d.get(field))
    for key, field in EXTRA:
        out[key] = _num(d.get(field))
    return out


def _delta(last: dict, prev: dict | None) -> dict:
    return {key: (round(last[key] - prev[key], 3) if prev and last[key] is not None and prev[key] is not None
                  else None) for key, *_ in METRICS}


def _bands(template, field_key: str, category: Category) -> list[dict]:
    """The category's own reference bands (its BAND alert rule, e.g. the PF's
    table per Sub) or else the field's — the same ones that fire alerts."""
    if template is None:
        return []
    from dashboards import category_bands

    fallback = next((f.get("reference_ranges") for f in (template.config_schema or {}).get("fields", [])
                     if isinstance(f, dict) and f.get("key") == field_key), None)
    with category_bands.scope(category.id):
        return [b for b in category_bands.for_field(template, field_key, fallback) if isinstance(b, dict)]


def composition(category: Category, *, player_id: str | None = None) -> dict:
    from api.scoping import players_in_category
    from load_control.wellness import _name

    players = list(players_in_category(category, include_call_ups=False)
                   .select_related("position").order_by("last_name", "first_name"))
    template = (ExamTemplate.objects.filter(department__club_id=category.club_id, slug=SLUG)
                .order_by("-is_active_version").first())
    metrics = [{"key": k, "label": label, "unit": unit, "decimals": dec, "direction": direction,
                "bands": _bands(template, field, category)}
               for k, field, label, unit, dec, direction in METRICS]
    empty = {"metrics": metrics, "squad_keys": SQUAD_KEYS, "rows": [], "mean": {}, "player": None}
    if template is None or not players:
        return empty

    by_player: dict[str, list[dict]] = {}
    for pid, when, data in (ExamResult.objects
                            .filter(template__family_id=template.family_id or template.id,
                                    player_id__in=[p.id for p in players])
                            .order_by("recorded_at").values_list("player_id", "recorded_at", "result_data")):
        m = _measurement(when, data)
        if any(m[k] is not None for k, *_ in METRICS):
            by_player.setdefault(str(pid), []).append(m)

    rows = []
    for p in players:
        ms = by_player.get(str(p.id))
        if not ms:
            continue
        last, prev = ms[-1], (ms[-2] if len(ms) > 1 else None)
        rows.append({"player_id": str(p.id), "name": _name(p), "position": p.position.name if p.position_id else "",
                     "last": last, "prev_date": prev["date"] if prev else None,
                     "delta": _delta(last, prev), "measurements": len(ms)})

    # "vs grupo": the squad's mean of each player's LAST reading.
    mean = {}
    for key, *_ in METRICS:
        vals = [r["last"][key] for r in rows if r["last"][key] is not None]
        mean[key] = round(sum(vals) / len(vals), 3) if vals else None

    player = None
    if player_id is not None:
        r = next((r for r in rows if r["player_id"] == str(player_id)), None)
        if r is not None:
            ms = by_player[r["player_id"]]
            player = {"player_id": r["player_id"], "name": r["name"], "last": r["last"],
                      "prev": ms[-2] if len(ms) > 1 else None, "first": ms[0],
                      "delta": r["delta"], "delta_first": _delta(r["last"], ms[0] if len(ms) > 1 else None),
                      "measurements": ms}

    return {"metrics": metrics, "squad_keys": SQUAD_KEYS, "rows": rows, "mean": mean, "player": player}
