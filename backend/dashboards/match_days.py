"""Match DAYS from GPS: the selector of a match-based layout without Events.

A team layout's match selector lists `Event`s, which is right when every match
GPS hangs from its event. The formativo's does not, for good reasons: the U11
(Serie 2015) has no fixtures in SLAB at all, a player of one cohort plays in
another team's match, and a fixture the federation moved keeps its old date.
So a layout can list, instead, the days its players have a `gps_partido`
result — the data is the source of truth — labelled with the opponent and the
team(s) that played:

    {"id": "2026-09-26", "title": "vs Deportes Temuco", "location": "U20 · U18"}

The layout opts in with `match_selector_config.source = "gps_days"`. Its
widgets then pick their window with `display_config.scope`: `"match"` reads
that one day, anything else the page's period (see `api.routers`).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

from exams.models import ExamResult

SLUG = "gps_partido"


def _legible(name: str) -> str:
    """COMET and the club's sheet shout ("DEPORTES TEMUCO"); a label shouldn't."""
    name = name.strip()
    return name.title() if name.isupper() else name


def rival_from_title(title: str) -> str:
    """"Universidad de Chile vs Deportes Temuco" → "Deportes Temuco"."""
    sides = re.split(r"\s+vs\.?\s+", title or "", flags=re.I)
    others = [s for s in sides if "CHILE" not in s.upper()]
    return _legible(others[0] if others else (title or ""))


def rival_from_session(sesion: str) -> str:
    """"Partido 2026-09-05 · MD · SANTIAGO WANDERERS" → "Santiago Wanderers"."""
    parts = (sesion or "").split(" · ")
    return _legible(parts[2]) if len(parts) >= 3 else ""


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1) - timedelta(microseconds=1)


def empty_window() -> tuple[datetime, datetime]:
    """A window nothing falls in: a match-scoped widget with no day chosen."""
    start = timezone.make_aware(datetime(2000, 1, 2))
    return start, start - timedelta(days=1)


def parse_day(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def options(player_ids=None, *, rows_q=None, limit: int = 500) -> list[dict[str, Any]]:
    """Newest first. One option per local day with match GPS — of those
    players, or of the rows `rows_q` selects (a team's: `team_scope`)."""
    qs = ExamResult.objects.filter(template__slug=SLUG)
    qs = qs.filter(rows_q) if rows_q is not None else qs.filter(player_id__in=list(player_ids or []))
    rows = (qs
            .values_list("recorded_at", "event__title", "event__starts_at",
                         "result_data__sesion", "result_data__origen_hoja",
                         "result_data__opponent", "result_data__venue",
                         "result_data__result", "result_data__opponent_quality"))
    per_day: dict[date, dict] = defaultdict(lambda: {"rivals": Counter(), "teams": Counter(),
                                                     "starts": None, "facts": Counter()})
    for recorded, ev_title, ev_start, sesion, hoja, opp, venue, result, quality in rows:
        day = timezone.localtime(recorded).date()
        slot = per_day[day]
        rival = (_legible(opp) if opp else
                 rival_from_title(ev_title) if ev_title else rival_from_session(sesion or ""))
        if venue or result or quality:
            slot["facts"][(venue, result, quality)] += 1
        if rival:
            slot["rivals"][rival] += 1
        if hoja:
            slot["teams"][hoja] += 1
        if ev_start and slot["starts"] is None and timezone.localtime(ev_start).date() == day:
            slot["starts"] = ev_start
    out = []
    for day in sorted(per_day, reverse=True)[:limit]:
        slot = per_day[day]
        rivals = [r for r, _ in slot["rivals"].most_common()]
        out.append({
            "id": day.isoformat(),
            "title": (" / ".join(f"vs {r}" for r in rivals[:2]) if rivals else "Partido"),
            # Noon, not midnight: a bare day sent as 00:00 UTC reads as the
            # evening before in Chile.
            "starts_at": slot["starts"] or day_bounds(day)[0] + timedelta(hours=12),
            "location": " · ".join([*(t for t, _ in slot["teams"].most_common()),
                                    *_facts(slot["facts"])]),
        })
    return out


_VENUE = {"home": "Local", "away": "Visita"}
_RESULT = {"won": "Ganado", "drawn": "Empatado", "lost": "Perdido"}


def _facts(facts: Counter) -> list[str]:
    """"Local", "Ganado", "Rival 3º en la tabla" — from the club's sheet."""
    if not facts:
        return []
    venue, result, quality = facts.most_common(1)[0][0]
    out = [x for x in (_VENUE.get(venue), _RESULT.get(result)) if x]
    if quality:
        q = quality.strip()
        out.append(f"Rival {q}º en la tabla" if q.isdigit() else f"Rival: {q.capitalize()}")
    return out


def short_facts(venue, result) -> str:
    """"L, G" for a tooltip."""
    parts = [{"home": "L", "away": "V"}.get(venue), {"won": "G", "drawn": "E", "lost": "P"}.get(result)]
    return ", ".join(p for p in parts if p)


def opponents_by_day(rows) -> dict[str, str]:
    """iso day → "Palestino (L, G)", from (recorded_at, event title, result_data)."""
    count: dict[str, Counter] = defaultdict(Counter)
    for recorded, ev_title, data in rows:
        data = data or {}
        rival = (_legible(data["opponent"]) if data.get("opponent") else
                 rival_from_title(ev_title) if ev_title else
                 rival_from_session(data.get("sesion") or ""))
        if rival:
            extra = short_facts(data.get("venue"), data.get("result"))
            count[timezone.localtime(recorded).date().isoformat()][
                f"{rival} ({extra})" if extra else rival] += 1
    return {d: c.most_common(1)[0][0] for d, c in count.items()}
