"""GPS a lo largo del tiempo — team widgets plus the rules shared with the profile.

The formativo's Power BI reads its GPS as a timeline: one bar per session,
labelled with its microcycle day (MD-4, MD, MD+1…) and grouped under the club's
microcycle number (MICRO), with a second metric as a line on its own axis. The
per-player versions (`dual_axis_bar_line`, `kpi_card`, `session_log`) live in
`dashboards.aggregation`; these are the team ones:

    team_dual_axis_bar_line   one point per SESSION (day × microcycle day): the
                              squad's mean per player of two metrics
    team_kpi_card             one number for the period, with the session series
                              as its sparkline
    team_session_log          one row per player and session, newest first — the
                              club's own GPS table

Shared `display_config` keys:

    "team": true        read the category's TEAM rows (`dashboards.team_scope`):
                        the sheet the club keeps per team (U16), with everyone
                        in it — what the club's report shows. Without it, the
                        category's own roster.
    "md_filter": true   the report's "tipo de día" chips apply to this widget
                        (`resolve_team_widget(md_labels=…)`). Off for widgets
                        that must not move with them ("Última actividad").

Several data sources are merged — `gps_sesion` and `gps_partido` together, so
the match day sits on the same axis as the week that led to it. Their field keys
are the same (see `project_gps_template_split`).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from core.models import Category
from exams.models import ExamResult

from .models import TeamReportWidget

# ---------------------------------------------------------------------------
# Shared rules (also used by the per-player resolvers in `aggregation`)
# ---------------------------------------------------------------------------

_MD_RE = re.compile(r"^MD([+-])(\d{1,2})$")


def md_sort_key(label: str | None) -> tuple[int, int]:
    """Microcycle order: MD-5 … MD-1, MD, MD+1, MD+2; anything else last."""
    if label == "MD":
        return (0, 0)
    m = _MD_RE.match(label or "")
    if not m:
        return (1, 0)
    n = int(m.group(2))
    return (0, -n if m.group(1) == "-" else n)


def micro_of(datos: dict) -> int | None:
    """The club's microcycle number (MICRO), when the row has one."""
    v = (datos or {}).get("microciclo")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def iso_week(when: datetime | date) -> str:
    return "%d-W%02d" % when.isocalendar()[:2]


_NO_RIVAL = {"entrenamiento": "Entrenamiento", "amistoso": "Amistoso"}


def note_of(datos: dict) -> str:
    """What the club's OBSERVACIÓN column says: the opponent on a match or a
    friendly, otherwise the kind of session."""
    datos = datos or {}
    if datos.get("opponent"):
        return str(datos["opponent"])
    tipo = str(datos.get("tipo_sesion") or "").strip().lower()
    return _NO_RIVAL.get(tipo, tipo.capitalize())


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(when: datetime) -> date:
    return timezone.localtime(when).date() if timezone.is_aware(when) else when.date()


# ---------------------------------------------------------------------------
# Team rows
# ---------------------------------------------------------------------------


# A layout has a dozen widgets on the same team: its scope (which sheet rows,
# who is in them) is the same for all, and costs most of each widget's time.
# `request_cache()` keeps it for one report request.
_SCOPES: ContextVar[dict | None] = ContextVar("gps_timeline_scopes", default=None)


@contextmanager
def request_cache() -> Iterator[None]:
    token = _SCOPES.set({})
    try:
        yield
    finally:
        _SCOPES.reset(token)


def _team(category, slugs: tuple[str, ...]):
    from . import team_scope

    cache = _SCOPES.get()
    key = (category.id, slugs)
    if cache is not None and key in cache:
        return cache[key]
    team = team_scope.for_category(category, template_slug=slugs)
    if cache is not None:
        cache[key] = team
    return team


def _sources(widget: TeamReportWidget) -> list:
    return list(widget.data_sources.select_related("template").order_by("sort_order"))


def _rows(widget, category, sources, position_id, player_ids, date_from, date_to,
          event_id=None, event_ids=None):
    """(rows, roster by id): the widget's ExamResults across all its sources,
    chronological, for the category's roster — or its TEAM's, when
    `display_config.team` is set."""
    from .team_aggregation import _TEAM, _apply_date_window, _roster_query

    team = None
    if (widget.display_config or {}).get("team"):
        team = _team(category, tuple(sorted({s.template.slug for s in sources})))
    token = _TEAM.set(team) if team is not None else None
    try:
        roster = {p.id: p for p in _roster_query(category, position_id, player_ids)
                  .select_related("position", "category")}
        qs = ExamResult.objects.filter(
            template__family_id__in=[s.template.family_id for s in sources],
            player_id__in=roster.keys(),
        )
        qs = _apply_date_window(qs, date_from, date_to, event_id, event_ids)
        rows = list(qs.order_by("recorded_at", "id")
                    .only("id", "player_id", "recorded_at", "result_data"))
    finally:
        if token is not None:
            _TEAM.reset(token)
    return rows, roster


def _sessions(rows) -> list[dict]:
    """Rows grouped into sessions — one per (day, microcycle day): a match and
    the recovery session of the same day are two points, a day's training is
    one. Chronological, then in microcycle order within a day."""
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        datos = r.result_data or {}
        groups[(_day(r.recorded_at), datos.get("md_label") or None)].append(r)
    out = []
    for (dia, md), members in sorted(groups.items(),
                                     key=lambda kv: (kv[0][0], md_sort_key(kv[0][1]))):
        micros = Counter(m for r in members if (m := micro_of(r.result_data)) is not None)
        out.append({
            "day": dia,
            "md_label": md,
            # The most common MICRO of the session: a stray cell on one row
            # must not split the session across two microcycles.
            "micro": micros.most_common(1)[0][0] if micros else None,
            "rows": members,
        })
    return out


def _mean(rows, key: str) -> float | None:
    vals = [v for r in rows if (v := _num((r.result_data or {}).get(key))) is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _fields(widget, sources) -> list[str]:
    keys: list[str] = []
    for s in sources:
        for k in s.field_keys or []:
            if k not in keys:
                keys.append(k)
    return keys


def _meta(template, key: str) -> dict[str, Any]:
    from .team_aggregation import _field_meta

    return {"key": key} | _field_meta(template, key)


def _base(widget, chart_type: str) -> dict[str, Any]:
    return {"chart_type": chart_type, "title": widget.title,
            "description": widget.description, "column_span": widget.column_span}


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


def resolve_dual_axis(widget: TeamReportWidget, category: Category, *,
                      position_id: UUID | None = None,
                      player_ids: Sequence[UUID] | None = None,
                      date_from: datetime | None = None, date_to: datetime | None = None,
                      event_id=None, event_ids=None) -> dict[str, Any]:
    """Two metrics of the squad over time: bars on the left axis, a line on the
    right. Each point is a session, its value the mean per player.

    `display_config`: `{"bars": "<field>", "line": "<field>"}` — without them,
    the first two field keys."""
    chart_type = "team_dual_axis_bar_line"
    sources = _sources(widget)
    cfg = widget.display_config or {}
    keys = _fields(widget, sources)
    bars = cfg.get("bars") or (keys[0] if keys else None)
    line = cfg.get("line") or (keys[1] if len(keys) > 1 else None)
    if not sources or not bars or not line:
        return _base(widget, chart_type) | {
            "bars": None, "line": None, "points": [], "empty": True,
            "error": "Configura dos campos: el primero va como barras y el segundo como línea."}

    rows, _roster = _rows(widget, category, sources, position_id, player_ids,
                          date_from, date_to, event_id, event_ids)
    points = []
    for s in _sessions(rows):
        points.append({
            "recorded_at": s["day"].isoformat(),
            "week": iso_week(s["day"]),
            "micro": s["micro"],
            "md_label": s["md_label"],
            "bars": _mean(s["rows"], bars),
            "line": _mean(s["rows"], line),
            "n": len({r.player_id for r in s["rows"]}),
        })
    template = sources[0].template
    return _base(widget, chart_type) | {
        "bars": _meta(template, bars),
        "line": _meta(template, line),
        "points": points,
        "aggregate": "mean_per_player",
        "empty": not points,
    }


_AGG_LABEL = {
    "mean": "Promedio por sesión",
    "sum": "Total del período",
    "max": "Máximo del período",
    "latest": "Última sesión",
    "last": "Último registro",
}


def resolve_kpi(widget: TeamReportWidget, category: Category, *,
                position_id: UUID | None = None,
                player_ids: Sequence[UUID] | None = None,
                date_from: datetime | None = None, date_to: datetime | None = None,
                event_id=None, event_ids=None) -> dict[str, Any]:
    """One number for the period, and the session series as its sparkline.

    `display_config`: `{"field": "<key>", "agg": …}` where `agg` is
      * `mean`   — the mean of the sessions' per-player means (a typical session)
      * `sum`    — every reading added up (volume of the period)
      * `max`    — the highest single reading, and whose (`subject`)
      * `latest` — the last session's per-player mean
      * `last`   — the last reading as written: a text field (the last opponent)
                   or a code (the current microcycle) — `text` carries it.
    """
    chart_type = "team_kpi_card"
    sources = _sources(widget)
    cfg = widget.display_config or {}
    keys = _fields(widget, sources)
    field = cfg.get("field") or (keys[0] if keys else None)
    agg = str(cfg.get("agg") or "mean").lower()
    if agg not in _AGG_LABEL:
        agg = "mean"
    base = _base(widget, chart_type) | {"agg": agg, "agg_label": _AGG_LABEL[agg]}
    if not sources or not field:
        return base | {"field": None, "value": None, "sparkline": [], "n": 0, "empty": True,
                       "error": "Configura el campo de la tarjeta."}

    rows, roster = _rows(widget, category, sources, position_id, player_ids,
                         date_from, date_to, event_id, event_ids)
    meta = _meta(sources[0].template, field)
    sessions = _sessions(rows)
    serie = [{"recorded_at": s["day"].isoformat(), "value": v}
             for s in sessions if (v := _mean(s["rows"], field)) is not None]

    value: float | None = None
    text: str | None = None
    subject: str | None = None
    last_at: str | None = None
    if agg == "last":
        for r in reversed(rows):
            raw = (r.result_data or {}).get(field)
            if raw not in (None, ""):
                last_at = _day(r.recorded_at).isoformat()
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    value = raw
                else:
                    text = str(raw)
                break
        serie = []
    elif agg == "max":
        best = None
        for r in rows:
            v = _num((r.result_data or {}).get(field))
            if v is not None and (best is None or v > best[0]):
                best = (v, r)
        if best:
            value = round(best[0], 2)
            p = roster.get(best[1].player_id)
            subject = f"{p.first_name} {p.last_name}".strip() if p else None
            last_at = _day(best[1].recorded_at).isoformat()
    elif agg == "sum":
        vals = [v for r in rows if (v := _num((r.result_data or {}).get(field))) is not None]
        value = round(sum(vals), 2) if vals else None
    elif serie:
        value = (serie[-1]["value"] if agg == "latest"
                 else round(sum(p["value"] for p in serie) / len(serie), 2))
    if serie and last_at is None:
        last_at = serie[-1]["recorded_at"]

    return base | {
        "field": meta,
        "value": value,
        "text": text,
        "subject": subject,
        "sparkline": serie if cfg.get("sparkline", True) else [],
        # Sessions, not readings: "promedio de 38 sesiones" is what the card means.
        "n": len(serie) if agg in ("mean", "latest") else len(rows),
        "n_label": "sesión" if agg in ("mean", "latest") else "registro",
        "last_recorded_at": last_at,
        "empty": value is None and text is None,
    }


def resolve_session_log(widget: TeamReportWidget, category: Category, *,
                        position_id: UUID | None = None,
                        player_ids: Sequence[UUID] | None = None,
                        date_from: datetime | None = None, date_to: datetime | None = None,
                        event_id=None, event_ids=None) -> dict[str, Any]:
    """The club's GPS table: one row per player and session, newest first.

    Fixed columns first — date, team, position, player, microcycle day — then
    the configured metrics, then the observation (opponent or session kind).
    `display_config.limit` caps the rows (default 500): a season of a whole
    squad is thousands, and nobody scrolls past the last few weeks."""
    chart_type = "team_session_log"
    sources = _sources(widget)
    keys = _fields(widget, sources)
    if not sources or not keys:
        return _base(widget, chart_type) | {"columns": [], "rows": [], "empty": True,
                                            "error": "Configura al menos un campo."}
    limit = (widget.display_config or {}).get("limit")
    limit = int(limit) if isinstance(limit, int) and limit > 0 else 500

    rows, roster = _rows(widget, category, sources, position_id, player_ids,
                         date_from, date_to, event_id, event_ids)
    out = []
    for r in reversed(rows):
        p = roster.get(r.player_id)
        datos = r.result_data or {}
        out.append({
            "result_id": str(r.id),
            "recorded_at": _day(r.recorded_at).isoformat(),
            "md_label": datos.get("md_label") or None,
            "micro": micro_of(datos),
            "player_id": str(r.player_id),
            "player": f"{p.first_name} {p.last_name}".strip() if p else "",
            "position": p.position.name if p and p.position_id else "",
            # The club's own team label (its sheet, "U16") when the row came
            # from it; otherwise the player's category.
            "team": datos.get("origen_hoja") or (p.category.name if p else ""),
            "note": note_of(datos),
            "values": {k: _num(datos.get(k)) for k in keys},
        })
        if len(out) >= limit:
            break
    return _base(widget, chart_type) | {
        "columns": [_meta(sources[0].template, k) for k in keys],
        "rows": out,
        "total": len(rows),
        "empty": not out,
    }


# ---------------------------------------------------------------------------
# The "tipo de día" filter
# ---------------------------------------------------------------------------


def parse_md(raw: str | None) -> list[str]:
    """`?md=MD-1,MD` → ["MD-1", "MD"]. Unknown shapes are dropped: a stale URL
    must not empty the page."""
    out = []
    for part in (raw or "").split(","):
        label = part.strip().upper()
        if (label == "MD" or _MD_RE.match(label)) and label not in out:
            out.append(label)
    return out


def md_options(widgets, category: Category, *, position_id=None, player_ids=None,
               date_from=None, date_to=None) -> list[str]:
    """The microcycle days present in the data of the widgets that opt into
    the filter, in microcycle order — chips only for days there are."""
    labels: set[str] = set()
    seen: set = set()
    for w in widgets:
        if not (w.display_config or {}).get("md_filter"):
            continue
        sources = _sources(w)
        # Widgets reading the same templates the same way have the same days.
        key = (tuple(sorted(s.template.family_id for s in sources)),
               bool((w.display_config or {}).get("team")))
        if not sources or key in seen:
            continue
        seen.add(key)
        rows, _ = _rows(w, category, sources, position_id, player_ids, date_from, date_to)
        labels |= {m for r in rows if (m := (r.result_data or {}).get("md_label"))}
    return sorted(labels, key=md_sort_key)
