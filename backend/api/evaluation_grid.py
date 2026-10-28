"""Centro de mando — "Evaluaciones físicas": every player against the club's bands.

The formativo's physical staff keeps one sheet per category with the bands of
each test (Muy deficiente … Elite, see `category_bands`) grouped by quality —
Fuerza, Neuromuscular, Carrera, Cambio de dirección, Resistencia. This is that
sheet applied to the squad: one row per player, one column per test, each cell
the player's LAST reading with the colour of the band it falls in.

Bands are the category's own (a 41 cm CMJ is "Bueno" in a Sub 20 and something
else in a Sub 13). A test shows only when the category has bands for it — the
colour is the point of the grid. A category without any (the Primer Equipo
today) gets no grid, and its Centro de mando stays as it was.

Roster: the category's own players (call-ups are counted where they belong).
"""
from __future__ import annotations

from typing import Any

from core.models import Category
from dashboards import category_bands
from exams.bands import band_for_value, band_rank
from exams.models import ExamResult, ExamTemplate

# The club's sheet, in its order: (group, [(template slug, field, label, unit)]).
GRUPOS: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    ("Fuerza", [
        ("fuerza", "rm_estimado", "RM Back Squat", "kg"),
        ("fuerza", "fr", "Back Squat", "RM/kg"),
    ]),
    ("Neuromuscular", [
        ("neuromuscular", "tiro_best", "Tiro", "km/h"),
        ("neuromuscular", "cmj_best", "CMJ", "cm"),
    ]),
    ("Carrera", [
        ("carreras", "t10_best", "T10", "s"),
        ("carreras", "t30_best", "T30", "s"),
    ]),
    ("Cambio de dirección", [
        ("carreras", "cod_der_best", "COD 505 Der", "s"),
        ("carreras", "cod_izq_best", "COD 505 Izq", "s"),
    ]),
    ("Resistencia", [
        ("resistencia", "palier", "Yo-Yo IR1", "palier"),
        ("resistencia", "vo2_max", "VO₂", "ml/kg/min"),
    ]),
]


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _score(levels: list[int]) -> dict | None:
    if not levels:
        return None
    return {"value": round(sum(levels) / len(levels), 2), "n": len(levels)}


def build_evaluation_grid(category: Category) -> dict[str, Any]:
    from api.scoping import players_in_category

    players = list(players_in_category(category, include_call_ups=False)
                   .select_related("position")
                   .order_by("position__sort_order", "last_name", "first_name"))
    slugs = {slug for _, cols in GRUPOS for slug, *_ in cols}
    templates: dict[str, ExamTemplate] = {}
    for t in (ExamTemplate.objects
              .filter(department__club_id=category.club_id, slug__in=slugs)
              .order_by("-is_active_version")):
        templates.setdefault(t.slug, t)
    bands_by_field = category_bands.build(category.id)

    # The latest reading of each field per player — per FIELD, not per result:
    # a session where the player skipped the CMJ still dated his last test.
    latest: dict[tuple[str, str], dict] = {}
    ids = [p.id for p in players]
    by_template: dict[str, list[str]] = {}
    for _, cols in GRUPOS:
        for slug, key, *_ in cols:
            by_template.setdefault(slug, []).append(key)
    for slug, keys in by_template.items():
        t = templates.get(slug)
        if t is None or not ids:
            continue
        rows = (ExamResult.objects
                .filter(template__family_id=t.family_id, player_id__in=ids)
                .order_by("-recorded_at")
                .values_list("player_id", "recorded_at", "result_data"))
        for pid, when, data in rows:
            for key in keys:
                v = _num((data or {}).get(key))
                if v is not None and (str(pid), key) not in latest:
                    latest[(str(pid), key)] = {"value": v, "date": when.date().isoformat()}

    groups = []
    for name, cols in GRUPOS:
        columns = []
        for slug, key, label, unit in cols:
            t = templates.get(slug)
            if t is None:
                continue
            bands = bands_by_field.get((t.family_id or t.id, key)) or []
            if not bands:
                continue
            field = next((f for f in (t.config_schema or {}).get("fields", [])
                          if isinstance(f, dict) and f.get("key") == key), {})
            columns.append({"key": key, "label": label, "unit": unit, "bands": bands,
                            # Breaks ties inside a band when sorting: a lower
                            # T10 is the better one.
                            "direction": field.get("direction_of_good") or "up"})
        if columns:
            groups.append({"name": name, "columns": columns})

    if not groups:
        return {"groups": [], "rows": [], "legend": []}

    rows = []
    for p in players:
        cells = {}
        for g in groups:
            for c in g["columns"]:
                hit = latest.get((str(p.id), c["key"]))
                if hit is None:
                    continue
                band = band_for_value(hit["value"], c["bands"])
                cells[c["key"]] = hit | {
                    "band": (band or {}).get("label"),
                    "color": (band or {}).get("color"),
                    # 1 = Muy deficiente … 7 = Elite: tests in s, cm and kg
                    # become comparable, so they can be averaged.
                    "level": band_rank(band, c["bands"]) if band else None,
                }
        # The summary: mean level per group and overall, over the tests the
        # player HAS — a missing test is not a 1, and `n` says how many counted.
        groups_score = {}
        for g in groups:
            lv = [cells[c["key"]]["level"] for c in g["columns"]
                  if cells.get(c["key"], {}).get("level") is not None]
            groups_score[g["name"]] = _score(lv)
        todos = [x["level"] for x in cells.values() if x.get("level") is not None]
        rows.append({
            "player_id": str(p.id),
            "name": f"{p.first_name} {p.last_name}".strip(),
            "position": p.position.name if p.position_id else "",
            "cells": cells,
            "groups": groups_score,
            "overall": _score(todos),
        })

    # The legend: the first full scale (every test uses the same seven names),
    # worst → best, so a level n is legend[n - 1].
    legend = next(([{"label": b.get("label"), "color": b.get("color")}
                    for b in sorted(c["bands"], key=lambda b: band_rank(b, c["bands"]))]
                   for g in groups for c in g["columns"] if c["bands"]), [])
    for g in groups:
        for c in g["columns"]:
            c.pop("bands")
    return {"groups": groups, "rows": rows, "legend": legend}
