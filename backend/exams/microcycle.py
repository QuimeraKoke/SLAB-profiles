"""Microcycle-day labelling (§1.e) — tag a session by its distance to matches.

`md_label` (MD-4, MD-3, MD-1, MD, MD+1 …) places a session in the weekly
cycle so alert rules and views can scope to a phase ("solo en MD-1"). It is a
pure function of the session date and the category's match calendar, so it is
recomputed — not authored: at GPS ingest for fresh rows, and by the
`backfill_md_labels` command whenever the fixture calendar changes.

Convention: a session *before* a match is MD-n (MD-1 = the eve); *after* is
MD+n. Ties (equidistant to a past and an upcoming match) resolve to the
upcoming one — the pre-match taper is the dominant framing. Beyond
``MAX_OFFSET_DAYS`` of any match there is no meaningful label (None).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

MAX_OFFSET_DAYS = 7


def microcycle_label(session_date: date, match_dates) -> str | None:
    """Label ``session_date`` by proximity to the nearest date in
    ``match_dates`` (an iterable of ``date``). Returns None when the calendar
    is empty or the nearest match is more than a week away."""
    best = None  # (sort_key, offset)
    for m in match_dates:
        offset = (m - session_date).days  # >0: match ahead (MD-n); <0: past (MD+n)
        # Smaller distance wins; on a tie the upcoming match (offset >= 0) wins.
        sort_key = (abs(offset), 0 if offset >= 0 else 1)
        if best is None or sort_key < best[0]:
            best = (sort_key, offset)
    if best is None:
        return None
    offset = best[1]
    if abs(offset) > MAX_OFFSET_DAYS:
        return None
    if offset == 0:
        return "MD"
    return f"MD-{offset}" if offset > 0 else f"MD+{-offset}"


def _session_date(result) -> date | None:
    """The calendar day the session happened on. `recorded_at` is set from the
    session date at ingest, so it's the reliable anchor; fall back to the
    `fecha` field only if needed."""
    if result.recorded_at is not None:
        return result.recorded_at.date()
    fecha = (result.result_data or {}).get("fecha")
    if isinstance(fecha, str) and fecha:
        try:
            return date.fromisoformat(fecha[:10])
        except ValueError:
            return None
    return None


def apply_md_labels(results) -> list:
    """Compute + set ``result_data['md_label']`` on each ExamResult in
    ``results`` (grouped by the player's category, one calendar query each).
    Mutates ``result_data`` in memory and returns the subset whose label
    actually changed — the caller persists them (bulk_update)."""
    from events.models import Event

    by_cat: dict = defaultdict(list)
    for r in results:
        by_cat[r.player.category_id].append(r)

    changed: list = []
    for cat_id, rs in by_cat.items():
        if cat_id is None:
            match_dates: list[date] = []
        else:
            match_dates = sorted(
                dt.date()
                for dt in Event.objects.filter(
                    event_type=Event.TYPE_MATCH, category_id=cat_id
                ).values_list("starts_at", flat=True)
            )
        for r in rs:
            sd = _session_date(r)
            label = microcycle_label(sd, match_dates) if sd is not None else None
            data = r.result_data or {}
            if data.get("md_label") != label:
                data["md_label"] = label
                r.result_data = data
                changed.append(r)
    return changed
