"""Team-scoped widget resolvers.

Parallel to `dashboards.aggregation` (per-player) — these resolvers walk the
full roster of a category and return aggregate-shaped payloads ready for the
frontend's team-widget registry to render.

The dispatcher is `resolve_team_widget(widget, category)`. Each chart type
gets a `_resolve_<name>` function returning a dict with at minimum
`{chart_type, title, ...}`. Empty / misconfigured widgets return a payload
shaped the same as the populated case but with `empty=True` so the frontend
can show a friendly stub instead of crashing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from core.models import Category, Player, Position
from exams.bands import band_for_value as _band_for_value
from exams.models import Episode, ExamResult, ExamTemplate

from .models import Aggregation, ChartType, TeamReportWidget


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def resolve_team_widget(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Resolve a team-scoped widget against a category roster.

    Optional `position_id` narrows the roster to players at one position
    (Goalkeeper, Defender, …). Applied uniformly across all team widgets
    so the report page's position picker affects every chart consistently.

    Optional `player_ids` further narrows the roster to a specific subset
    of players (empty / None = no filter). The chosen players still appear
    on roster-shaped widgets even if they have no data in the date window
    — empty cells preserve the roster as the "frame of reference".

    Optional `date_from` / `date_to` bound `ExamResult.recorded_at` before
    every aggregation runs. `LATEST` / `LAST_N` / `ALL` semantics stay the
    same — they just operate on the bounded queryset. Endpoint callers
    are expected to cap the window (currently 90 days at the API layer).
    """
    chart_type = widget.chart_type
    common = {
        "position_id": position_id,
        "player_ids": player_ids,
        "date_from": date_from,
        "date_to": date_to,
    }
    if chart_type == ChartType.TEAM_HORIZONTAL_COMPARISON.value:
        return _resolve_team_horizontal_comparison(widget, category, **common)
    if chart_type == ChartType.TEAM_ROSTER_MATRIX.value:
        return _resolve_team_roster_matrix(widget, category, **common)
    if chart_type == ChartType.TEAM_STATUS_COUNTS.value:
        return _resolve_team_status_counts(widget, category, **common)
    if chart_type == ChartType.TEAM_TREND_LINE.value:
        return _resolve_team_trend_line(widget, category, **common)
    if chart_type == ChartType.TEAM_DISTRIBUTION.value:
        return _resolve_team_distribution(widget, category, **common)
    if chart_type == ChartType.TEAM_ACTIVE_RECORDS.value:
        return _resolve_team_active_records(widget, category, **common)
    if chart_type == ChartType.TEAM_ACTIVITY_COVERAGE.value:
        return _resolve_team_activity_coverage(widget, category, **common)
    if chart_type == ChartType.TEAM_LEADERBOARD.value:
        return _resolve_team_leaderboard(widget, category, **common)
    if chart_type == ChartType.TEAM_GOAL_PROGRESS.value:
        return _resolve_team_goal_progress(widget, category, **common)
    if chart_type == ChartType.TEAM_ALERTS.value:
        return _resolve_team_alerts(widget, category, **common)
    return _empty(widget, chart_type, error=f"Unsupported chart type: {chart_type}")


def _roster_query(
    category: Category,
    position_id: UUID | None,
    player_ids: Sequence[UUID] | None = None,
):
    """Active-player queryset for the category.

    Filters cascade: position → explicit player subset. An empty / None
    `player_ids` means "no player-level filter" (all matching players).
    Players that the caller passes in `player_ids` are kept even if they
    have no data in the current date window — by design, since the
    selection itself is the user's "frame of reference".
    """
    qs = Player.objects.filter(category_id=category.id, is_active=True)
    if position_id is not None:
        qs = qs.filter(position_id=position_id)
    if player_ids:
        qs = qs.filter(id__in=list(player_ids))
    return qs.order_by("last_name", "first_name")


def _apply_date_window(
    qs,
    date_from: datetime | None,
    date_to: datetime | None,
):
    """Bound an ExamResult / Episode queryset by `recorded_at` (or
    `started_at` for Episode). Each resolver passes the right field via
    its own query construction — this helper handles ExamResult only.
    Callers that need Episode filtering apply it inline.
    """
    if date_from is not None:
        qs = qs.filter(recorded_at__gte=date_from)
    if date_to is not None:
        qs = qs.filter(recorded_at__lte=date_to)
    return qs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty(widget: TeamReportWidget, chart_type: str, error: str = "") -> dict[str, Any]:
    base: dict[str, Any] = {
        "chart_type": chart_type,
        "title": widget.title,
        "empty": True,
        "rows": [],
    }
    if chart_type == ChartType.TEAM_HORIZONTAL_COMPARISON.value:
        base["fields"] = []
        base["default_field_key"] = ""
        base["limit_per_player"] = 0
    elif chart_type == ChartType.TEAM_ROSTER_MATRIX.value:
        base["columns"] = []
        base["ranges"] = {}
        base["coloring"] = "none"
        base["variation"] = "off"
    elif chart_type == ChartType.TEAM_STATUS_COUNTS.value:
        base["stages"] = []
        base["available_count"] = 0
        base["total"] = 0
    elif chart_type == ChartType.TEAM_TREND_LINE.value:
        base["fields"] = []
        base["default_field_key"] = ""
        base["bucket_size"] = "week"
        base["buckets"] = []
    elif chart_type == ChartType.TEAM_DISTRIBUTION.value:
        base["field"] = None
        base["bin_count"] = 0
        base["bins"] = []
        base["stats"] = {}
    elif chart_type == ChartType.TEAM_ACTIVE_RECORDS.value:
        base["columns"] = []
        base["active_count"] = 0
        base["total"] = 0
        base["as_of"] = ""
    elif chart_type == ChartType.TEAM_ACTIVITY_COVERAGE.value:
        base["columns"] = []
        base["thresholds"] = {"green_max": 30, "yellow_max": 60}
        base["as_of"] = ""
    elif chart_type == ChartType.TEAM_LEADERBOARD.value:
        base["field"] = None
        base["aggregator"] = "sum"
        base["order"] = "desc"
        base["limit"] = 5
    elif chart_type == ChartType.TEAM_GOAL_PROGRESS.value:
        base["columns"] = []
        base["summary"] = {
            "achieved": 0, "in_progress": 0, "missed": 0,
            "no_data": 0, "total": 0,
        }
    elif chart_type == ChartType.TEAM_ALERTS.value:
        base["players"] = []
        base["total_alerts"] = 0
        base["department_name"] = ""
    if error:
        base["error"] = error
    return base


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _field_meta(template: ExamTemplate, key: str) -> dict[str, Any]:
    """Look up label/unit/direction/bands for a field key on the template schema."""
    for field in (template.config_schema or {}).get("fields", []):
        if isinstance(field, dict) and field.get("key") == key:
            return {
                "label": field.get("label", key),
                "unit": field.get("unit", ""),
                "type": field.get("type", ""),
                # "up" / "down" / "neutral" — drives delta coloring on the
                # frontend (TeamRosterMatrix.tsx). Defaults to "neutral"
                # when the template author hasn't set an opinion.
                "direction_of_good": field.get("direction_of_good", "neutral"),
                # Clinical reference bands. List of {label, min?, max?,
                # color?}. Empty list = no bands defined → frontend skips
                # band-based hint and coloring for this field.
                "reference_ranges": list(field.get("reference_ranges") or []),
            }
    return {
        "label": key, "unit": "", "type": "",
        "direction_of_good": "neutral", "reference_ranges": [],
    }


def _format_short_date(dt: datetime) -> str:
    """Spanish short date used for bar labels — '12 ago'."""
    months_es = [
        "ene", "feb", "mar", "abr", "may", "jun",
        "jul", "ago", "sep", "oct", "nov", "dic",
    ]
    return f"{dt.day:02d} {months_es[dt.month - 1]}"


# ---------------------------------------------------------------------------
# team_horizontal_comparison
# ---------------------------------------------------------------------------


def _resolve_team_horizontal_comparison(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Per-player horizontal bar groups, one bar per recent reading.

    Walks **all** `TeamReportWidgetDataSource` rows on the widget. Each
    source contributes its `field_keys` to the dropdown — so admins can
    mix multiple templates (e.g. peso from Antropo + distancia from GPS)
    in a single selector. With a single source the dropdown keys stay as
    the raw `field_key`; with multiple sources keys are disambiguated as
    `{source_pk}__{field_key}` and labels carry the template name.

    `aggregation` should be `last_n` per source; `aggregation_param`
    determines bars-per-player for that source. The widget's overall
    `limit_per_player` is the max across all sources (drives legend size
    on the frontend; shorter per-field lists just render fewer bars).

    Returns:
        {
            "chart_type": "team_horizontal_comparison",
            "title": "...",
            "fields": [
                {"key": "peso", "label": "Peso · Antropo", "unit": "kg"},
                {"key": "<uuid>__distancia", "label": "Distancia · GPS", "unit": "m"}
            ],
            "default_field_key": "peso",
            "limit_per_player": 3,
            "rows": [
                {
                    "player_id": "<uuid>", "player_name": "Juan Pérez",
                    "values": {
                        "peso":              [{"value": 78.5, "label": "12 ago", "iso": "..."}, ...],
                        "<uuid>__distancia": [{"value": 9800,  "label": "12 ago", "iso": "..."}, ...]
                    }
                },
                ...
            ]
        }

    Each (source × field_key) maintains its own last-N-readings list per
    player. Readings only count toward a field's list if that field has a
    numeric value on the result. Players with no readings on any field
    are still included with empty arrays so row order matches the roster.
    """
    sources = list(widget.data_sources.all().select_related("template"))
    if not sources:
        return _empty(
            widget,
            ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            error=(
                "Configura una Data Source en este widget: elige la plantilla "
                "del examen y los campos a graficar (Aggregation = last_n, "
                "Aggregation param = cantidad de barras por jugador)."
            ),
        )

    # Reject early if no source has any field_keys configured.
    if not any(source.field_keys for source in sources):
        return _empty(
            widget,
            ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            error=(
                "Las data sources de este widget no tienen field_keys. "
                "Agrega al menos una clave numérica a graficar."
            ),
        )

    multi_source = len(sources) > 1
    display_config = widget.display_config or {}
    group_raw = display_config.get("group_by", "none")
    group_by = group_raw if group_raw in {"none", "position"} else "none"

    def _make_key(source_pk: UUID, field_key: str) -> str:
        # Single-source: keep raw field_key for cleaner payloads.
        # Multi-source: prefix with source UUID so two templates can both
        # have e.g. `peso` without collision.
        return f"{source_pk}__{field_key}" if multi_source else field_key

    # Build the flat fields list (one entry per (source, field_key)) +
    # remember per-source limits so the right N applies when bucketing.
    fields_meta: list[dict[str, Any]] = []
    source_limits: dict[UUID, int] = {}
    for source in sources:
        if source.aggregation == Aggregation.LAST_N:
            source_limits[source.pk] = max(1, min(int(source.aggregation_param or 3), 12))
        else:
            source_limits[source.pk] = 3
        for fk in source.field_keys or []:
            meta = _field_meta(source.template, fk)
            label = meta["label"]
            if multi_source:
                # Disambiguate: "Peso · Antropo" vs "Peso · GPS".
                label = f"{label} · {source.template.name}"
            fields_meta.append(
                {
                    "key": _make_key(source.pk, fk),
                    "label": label,
                    "unit": meta["unit"],
                }
            )

    overall_limit = max(source_limits.values(), default=3)

    players = list(
        _roster_query(category, position_id, player_ids)
        .select_related("position")
    )
    player_index = {p.id: p for p in players}

    if group_by == "position":
        return _resolve_team_horizontal_comparison_by_position(
            widget, fields_meta, players, sources, _make_key,
            source_limits, overall_limit, date_from, date_to,
        )

    # Initialize buckets keyed by every synthetic key.
    by_player: dict[UUID, dict[str, list[dict[str, Any]]]] = {
        p.id: {f["key"]: [] for f in fields_meta} for p in players
    }

    # One query per source. We fan out across the template's version
    # family (see aggregation.py for rationale) so widgets pointing at v2
    # also surface results from v1.
    for source in sources:
        results = _apply_date_window(
            ExamResult.objects
            .filter(
                template__family_id=source.template.family_id,
                player_id__in=player_index.keys(),
            ),
            date_from, date_to,
        ).order_by("player_id", "-recorded_at").values(
            "player_id", "recorded_at", "result_data",
        )
        per_source_limit = source_limits[source.pk]
        for row in results:
            pid = row["player_id"]
            per_field = by_player.get(pid)
            if per_field is None:
                continue
            recorded_at = row["recorded_at"]
            raw = row["result_data"] or {}
            for fk in source.field_keys or []:
                synthetic = _make_key(source.pk, fk)
                bucket = per_field[synthetic]
                if len(bucket) >= per_source_limit:
                    continue
                value = _safe_float(raw.get(fk))
                if value is None:
                    continue
                bucket.append(
                    {
                        "value": value,
                        "label": _format_short_date(recorded_at),
                        "iso": recorded_at.date().isoformat(),
                    }
                )

    rows = [
        {
            "player_id": str(p.id),
            "player_name": f"{p.first_name} {p.last_name}".strip(),
            "values": by_player.get(p.id, {f["key"]: [] for f in fields_meta}),
        }
        for p in players
    ]

    has_any_data = any(
        any(values for values in row["values"].values()) for row in rows
    )

    return {
        "chart_type": ChartType.TEAM_HORIZONTAL_COMPARISON.value,
        "title": widget.title,
        "grouping": "none",
        "fields": fields_meta,
        "default_field_key": fields_meta[0]["key"] if fields_meta else "",
        "limit_per_player": overall_limit,
        "rows": rows,
        "empty": not has_any_data,
    }


# ---------------------------------------------------------------------------
# team_roster_matrix
# ---------------------------------------------------------------------------


def _resolve_team_roster_matrix(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Roster × metrics matrix — rows = players, columns = field keys.

    Reads its data binding from the widget's first `TeamReportWidgetDataSource`:
    `field_keys` is the **list of metrics**, one column per key. Each cell is
    the player's *latest* numeric value for that field — different fields can
    come from different readings (e.g. height measured monthly, weight weekly).

    Optional `display_config` knobs:
        {
            "coloring":  "none" | "vs_team_range",      // default "none"
            "variation": "off"  | "absolute" | "percent" // default "off"
        }

    When `variation != "off"`, each cell carries the previous numeric value
    on the same field (taken from the next-most-recent reading where that
    field was set), so the frontend can render a delta indicator. Cells
    with no prior reading omit the previous_value/iso keys.

    Returns:
        {
            "chart_type": "team_roster_matrix",
            "title": "...",
            "columns": [
                {"key": "imc",   "label": "IMC",   "unit": "kg/m²"},
                {"key": "peso",  "label": "Peso",  "unit": "kg"},
                ...
            ],
            "ranges": {
                "imc":  {"min": 18.5, "max": 26.4},
                "peso": {"min": 65.0, "max": 92.0},
                ...
            },
            "rows": [
                {
                    "player_id": "<uuid>",
                    "player_name": "Juan Pérez",
                    "cells": {
                        "imc": {
                            "value": 23.4, "iso": "2025-08-12",
                            "previous_value": 24.1, "previous_iso": "2025-07-05"
                        },
                        "peso": {"value": 78.5, "iso": "2025-08-12"}
                    }
                },
                ...
            ],
            "coloring": "vs_team_range",
            "variation": "absolute",
            "empty": false
        }

    Players with no readings on any field still appear with empty `cells`
    (preserves roster order). A field missing on a specific player just
    omits that field's entry from the player's `cells` dict.
    """
    sources = list(widget.data_sources.all().select_related("template"))
    if not sources:
        return _empty(
            widget,
            ChartType.TEAM_ROSTER_MATRIX.value,
            error=(
                "Configura una Data Source en este widget: elige la plantilla "
                "y los campos numéricos a graficar como columnas."
            ),
        )
    if not any(s.field_keys for s in sources):
        return _empty(
            widget,
            ChartType.TEAM_ROSTER_MATRIX.value,
            error=(
                "Las data sources de este widget no tienen field_keys. "
                "Agrega al menos una clave numérica para usar como columna."
            ),
        )

    multi_source = len(sources) > 1

    def _make_key(source_pk: UUID, field_key: str) -> str:
        # Single-source: keep raw `field_key` for cleaner payloads.
        # Multi-source: prefix with source UUID so two templates can share
        # a field name (e.g. both have `peso`) without colliding.
        return f"{source_pk}__{field_key}" if multi_source else field_key

    # Build the flat columns list (one entry per (source, field_key)) and
    # remember the (source_pk, field_key) tuple for each synthetic key so
    # we know which template each column reads from.
    columns: list[dict[str, Any]] = []
    column_origin: dict[str, tuple[UUID, str]] = {}
    for source in sources:
        for fk in source.field_keys or []:
            synthetic = _make_key(source.pk, fk)
            meta = _field_meta(source.template, fk)
            label = meta["label"]
            if multi_source:
                # Disambiguate: "Peso · Antropo" vs "Peso · GPS".
                label = f"{label} · {source.template.name}"
            columns.append(
                {
                    "key": synthetic,
                    "label": label,
                    "unit": meta["unit"],
                    # Pass-through so the frontend's delta coloring knows
                    # whether a rise on this column should be green or red.
                    "direction_of_good": meta.get("direction_of_good", "neutral"),
                    # Clinical reference bands — frontend renders each cell
                    # with a colored border matching the band the value
                    # falls into. Empty list = no bands → no border.
                    "reference_ranges": meta.get("reference_ranges", []),
                }
            )
            column_origin[synthetic] = (source.pk, fk)

    display_config = widget.display_config or {}

    coloring_raw = display_config.get("coloring", "none")
    coloring = coloring_raw if coloring_raw in {"none", "vs_team_range"} else "none"

    variation_raw = display_config.get("variation", "off")
    variation = (
        variation_raw if variation_raw in {"off", "absolute", "percent"} else "off"
    )

    players = list(_roster_query(category, position_id, player_ids))
    player_index = {p.id: p for p in players}

    # Whether we still need a "previous" value for each cell. When variation
    # is off we stop after capturing the latest, saving iterations on
    # players with long histories.
    needs_previous = variation != "off"

    cells_by_player: dict[UUID, dict[str, dict[str, Any]]] = {
        p.id: {} for p in players
    }

    # One query per source — different templates need different
    # `template_id` filters. Cheap with our roster sizes (~50 players,
    # ≤5 sources, hundreds of results per template).
    for source in sources:
        # Synthetic keys this source contributes to the matrix.
        source_synthetics: list[tuple[str, str]] = [
            (_make_key(source.pk, fk), fk) for fk in source.field_keys or []
        ]
        if not source_synthetics:
            continue

        results = _apply_date_window(
            ExamResult.objects
            .filter(
                template__family_id=source.template.family_id,
                player_id__in=player_index.keys(),
            ),
            date_from, date_to,
        ).order_by("player_id", "-recorded_at").values(
            "player_id", "recorded_at", "result_data",
        )

        for row in results:
            pid = row["player_id"]
            per_player = cells_by_player.get(pid)
            if per_player is None:
                continue
            # Stop iterating this player's history once every column from
            # THIS source is fully filled (latest + optional previous).
            all_done = all(
                synthetic in per_player
                and (not needs_previous or "previous_value" in per_player[synthetic])
                for synthetic, _ in source_synthetics
            )
            if all_done:
                continue
            recorded_at = row["recorded_at"]
            iso = recorded_at.date().isoformat()
            raw = row["result_data"] or {}
            for synthetic, fk in source_synthetics:
                value = _safe_float(raw.get(fk))
                if value is None:
                    continue
                cell = per_player.get(synthetic)
                if cell is None:
                    per_player[synthetic] = {"value": value, "iso": iso}
                elif needs_previous and "previous_value" not in cell:
                    cell["previous_value"] = value
                    cell["previous_iso"] = iso

    # Team-wide min/max per synthetic column, used by the frontend for
    # `vs_team_range` coloring.
    ranges: dict[str, dict[str, float]] = {}
    for col in columns:
        synthetic = col["key"]
        values = [
            cells_by_player[pid][synthetic]["value"]
            for pid in cells_by_player
            if synthetic in cells_by_player[pid]
        ]
        if values:
            ranges[synthetic] = {"min": min(values), "max": max(values)}

    rows = [
        {
            "player_id": str(p.id),
            "player_name": f"{p.first_name} {p.last_name}".strip(),
            "cells": cells_by_player.get(p.id, {}),
        }
        for p in players
    ]

    has_any_data = any(row["cells"] for row in rows)

    return {
        "chart_type": ChartType.TEAM_ROSTER_MATRIX.value,
        "title": widget.title,
        "columns": columns,
        "ranges": ranges,
        "rows": rows,
        "coloring": coloring,
        "variation": variation,
        "empty": not has_any_data,
    }


# ---------------------------------------------------------------------------
# team_status_counts
# ---------------------------------------------------------------------------


# Default stage colors when the admin doesn't override via display_config.
# `available` (no open episode) is green; open stages step from red →
# orange → yellow as severity decreases (most concerning first).
_DEFAULT_OPEN_STAGE_PALETTE = ["#dc2626", "#ea580c", "#f59e0b", "#eab308"]
_AVAILABLE_COLOR = "#16a34a"


def _resolve_team_status_counts(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,  # accepted for signature parity; see docstring
    date_to: datetime | None = None,    # accepted for signature parity; see docstring
) -> dict[str, Any]:
    """Squad availability snapshot — answers "who's ready to play?"

    Note: `date_from`/`date_to` are accepted but intentionally NOT applied
    to the Episode query — "who's available" is inherently a current-moment
    question, not a historical one. Restricting to open episodes started in
    a past window would produce a misleading snapshot.

    For each active player in the category, finds the most recent OPEN
    Episode on the configured episodic template (typically Lesiones). The
    player is bucketed by that episode's `stage` (e.g. "injured",
    "recovery", "reintegration"). Players with no open episode are
    bucketed as `available` — ready for full match.

    Reads its data binding from the widget's first `TeamReportWidgetDataSource`:
    only the `template` matters here (must be `is_episodic=True`); `field_keys`
    and `aggregation` are ignored.

    Optional `display_config` knobs:
        {
            "stage_colors": {"injured": "#dc2626", ...}  // override defaults
        }

    Returns:
        {
            "chart_type": "team_status_counts",
            "title": "...",
            "stages": [
                {
                    "value": "available", "label": "Disponible", "kind": "available",
                    "count": 13, "color": "#16a34a",
                    "players": [{"id": "...", "name": "Juan Pérez"}, ...]
                },
                {
                    "value": "reintegration", "label": "Reintegración", "kind": "open",
                    "count": 2, "color": "#eab308",
                    "players": [...]
                },
                ...
            ],
            "available_count": 13,
            "total": 18,
            "empty": false
        }

    Stages are returned in this order: `available` first (the headline
    number), then `open_stages` from `episode_config` in the template's
    declared order (worst → best). Closed stages are NEVER counted —
    closed = recovered = available.
    """
    source = widget.data_sources.first()
    if source is None:
        return _empty(
            widget,
            ChartType.TEAM_STATUS_COUNTS.value,
            error=(
                "Configura una Data Source en este widget: elige la plantilla "
                "episódica (típicamente Lesiones) que define las etapas."
            ),
        )

    template: ExamTemplate = source.template
    if not template.is_episodic:
        return _empty(
            widget,
            ChartType.TEAM_STATUS_COUNTS.value,
            error=(
                f"La plantilla '{template.name}' no es episódica. Este widget "
                f"sólo funciona con plantillas que tengan is_episodic=True."
            ),
        )

    cfg = template.episode_config or {}
    stage_field = cfg.get("stage_field") or ""
    open_stages: list[str] = list(cfg.get("open_stages") or [])
    if not stage_field or not open_stages:
        return _empty(
            widget,
            ChartType.TEAM_STATUS_COUNTS.value,
            error=(
                f"La plantilla '{template.name}' no tiene episode_config "
                f"completo (stage_field + open_stages)."
            ),
        )

    # Stage labels come from option_labels on the stage_field (when set);
    # fall back to the raw value capitalized.
    stage_labels: dict[str, str] = {}
    for f in (template.config_schema or {}).get("fields", []):
        if isinstance(f, dict) and f.get("key") == stage_field:
            stage_labels = dict(f.get("option_labels") or {})
            break

    color_overrides = (widget.display_config or {}).get("stage_colors") or {}

    players = list(_roster_query(category, position_id, player_ids))
    player_index = {p.id: p for p in players}

    # Most recent open Episode per player on this template family. We fan
    # out across all versions — an injury diagnosed under v1 should still
    # count toward "currently injured" after the template is forked. A
    # player can technically have several concurrent injuries; we surface
    # the most recently started one for the headline.
    open_episodes = (
        Episode.objects
        .filter(
            template__family_id=template.family_id,
            player_id__in=player_index.keys(),
            status=Episode.STATUS_OPEN,
        )
        .order_by("player_id", "-started_at")
        .values("player_id", "stage")
    )
    stage_by_player: dict[UUID, str] = {}
    for ep in open_episodes:
        # First-seen-wins per player (queryset is sorted -started_at).
        stage_by_player.setdefault(ep["player_id"], ep["stage"] or "")

    # Bucket players by stage.
    buckets: dict[str, list[dict[str, str]]] = {"available": []}
    for stage in open_stages:
        buckets[stage] = []
    for p in players:
        stage = stage_by_player.get(p.id, "")
        # Unknown / empty / closed-stage values from old data bucket as
        # available — closed = recovered = available. Stages that aren't in
        # `open_stages` but appear on episode rows shouldn't happen with
        # signal-managed lifecycle, but we degrade gracefully.
        bucket_key = stage if stage in buckets else "available"
        buckets[bucket_key].append(
            {
                "id": str(p.id),
                "name": f"{p.first_name} {p.last_name}".strip(),
            }
        )

    # Build the ordered stages list. `available` first (it's the headline),
    # then open_stages in template-declared order (worst → best).
    stages_payload = [
        {
            "value": "available",
            "label": stage_labels.get("available", "Disponible"),
            "kind": "available",
            "count": len(buckets["available"]),
            "color": color_overrides.get("available", _AVAILABLE_COLOR),
            "players": buckets["available"],
        }
    ]
    for i, stage in enumerate(open_stages):
        default_color = _DEFAULT_OPEN_STAGE_PALETTE[
            min(i, len(_DEFAULT_OPEN_STAGE_PALETTE) - 1)
        ]
        stages_payload.append(
            {
                "value": stage,
                "label": stage_labels.get(stage, stage.capitalize()),
                "kind": "open",
                "count": len(buckets[stage]),
                "color": color_overrides.get(stage, default_color),
                "players": buckets[stage],
            }
        )

    total = len(players)
    available_count = len(buckets["available"])

    return {
        "chart_type": ChartType.TEAM_STATUS_COUNTS.value,
        "title": widget.title,
        "stages": stages_payload,
        "available_count": available_count,
        "total": total,
        "empty": total == 0,
    }


# ---------------------------------------------------------------------------
# team_trend_line
# ---------------------------------------------------------------------------


def _bucket_start(dt: datetime, bucket_size: str) -> datetime:
    """Return the canonical start of `dt`'s bucket (Monday for weeks,
    1st of the month for months). Used to align readings into bins."""
    if bucket_size == "month":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # week: align to Monday
    days_to_monday = dt.weekday()
    monday = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = monday.replace(day=monday.day) - timedelta(days=days_to_monday)
    return monday


def _bucket_label(start: datetime, bucket_size: str) -> str:
    if bucket_size == "month":
        months = ["ene", "feb", "mar", "abr", "may", "jun",
                  "jul", "ago", "sep", "oct", "nov", "dic"]
        return f"{months[start.month - 1]} {start.year}"
    iso_year, iso_week, _ = start.isocalendar()
    return f"S{iso_week:02d} {iso_year}"


def _resolve_team_trend_line(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Multi-series line chart: team average per metric over time.

    Walks every `TeamReportWidgetDataSource` on the widget — same multi-
    source pattern as `team_horizontal_comparison`. Each (source × field_key)
    contributes one selectable series. Values are bucketed by week (default)
    or month and averaged across all readings from the (filtered) roster
    falling into each bucket.

    `display_config`:
        { "bucket_size": "week" | "month",   // default "week"
          "group_by":   "none" | "position"  // default "none" }

    With `group_by: "position"` the team-wide mean splits into one line
    per position (POR / DF / MC / DEL...). The header position filter
    overrides grouping — if the user picked "Defensores" already, the
    widget only emits the defenders line. Players without a position
    bucket into "Sin posición".

    Returns when `group_by="none"` (default):
        {
            "chart_type": "team_trend_line",
            "grouping": "none",
            "title": "...",
            "fields": [{"key": "...", "label": "...", "unit": "..."}, ...],
            "default_field_key": "...",
            "bucket_size": "week",
            "buckets": [
                {"label": "S35 2025", "iso": "...", "values": {"<key>": 23.4}}, ...
            ],
            "empty": false
        }

    Returns when `group_by="position"`:
        {
            ...
            "grouping": "position",
            "groups": [
                {"id": "<uuid>", "label": "POR", "color": "#a855f7"},
                {"id": "<uuid>", "label": "DF",  "color": "#3b82f6"},
                ...
            ],
            "buckets": [
                {
                    "label": "...", "iso": "...",
                    "values_by_group": {
                        "<position_id>": {"<field_key>": 23.4, ...},
                        ...
                    }
                }, ...
            ]
        }
    """
    sources = list(widget.data_sources.all().select_related("template"))
    if not sources:
        return _empty(
            widget,
            ChartType.TEAM_TREND_LINE.value,
            error=(
                "Configura una Data Source en este widget: elige la plantilla "
                "y los campos numéricos a graficar como series."
            ),
        )
    if not any(s.field_keys for s in sources):
        return _empty(
            widget,
            ChartType.TEAM_TREND_LINE.value,
            error=(
                "Las data sources de este widget no tienen field_keys. "
                "Agrega al menos una clave numérica para graficar."
            ),
        )

    multi_source = len(sources) > 1
    display_config = widget.display_config or {}
    bucket_raw = display_config.get("bucket_size", "week")
    bucket_size = bucket_raw if bucket_raw in {"week", "month"} else "week"
    group_raw = display_config.get("group_by", "none")
    group_by = group_raw if group_raw in {"none", "position"} else "none"

    def _make_key(source_pk: UUID, field_key: str) -> str:
        return f"{source_pk}__{field_key}" if multi_source else field_key

    # Build the flat fields list (one entry per (source, field_key)).
    fields_meta: list[dict[str, Any]] = []
    for source in sources:
        for fk in source.field_keys or []:
            meta = _field_meta(source.template, fk)
            label = meta["label"]
            if multi_source:
                label = f"{label} · {source.template.name}"
            fields_meta.append(
                {
                    "key": _make_key(source.pk, fk),
                    "label": label,
                    "unit": meta["unit"],
                }
            )

    players = list(
        _roster_query(category, position_id, player_ids)
        .select_related("position")
    )
    player_index = {p.id: p for p in players}
    if not player_index:
        empty: dict[str, Any] = {
            "chart_type": ChartType.TEAM_TREND_LINE.value,
            "title": widget.title,
            "fields": fields_meta,
            "default_field_key": fields_meta[0]["key"] if fields_meta else "",
            "bucket_size": bucket_size,
            "grouping": group_by,
            "buckets": [],
            "empty": True,
        }
        if group_by == "position":
            empty["groups"] = []
        return empty

    if group_by == "position":
        return _resolve_team_trend_line_by_position(
            widget, fields_meta, players, sources, bucket_size, _make_key,
            date_from, date_to,
        )

    # ---- group_by == "none" (legacy team-wide path) ----
    # bucket_start_iso → field_key → list of values from any roster member.
    # We aggregate per bucket at the end.
    buckets: dict[str, dict[str, list[float]]] = {}
    bucket_starts: dict[str, datetime] = {}

    for source in sources:
        source_synthetics = [
            (_make_key(source.pk, fk), fk) for fk in source.field_keys or []
        ]
        if not source_synthetics:
            continue
        results = _apply_date_window(
            ExamResult.objects
            .filter(
                template__family_id=source.template.family_id,
                player_id__in=player_index.keys(),
            ),
            date_from, date_to,
        ).order_by("recorded_at").values("recorded_at", "result_data")
        for row in results:
            start = _bucket_start(row["recorded_at"], bucket_size)
            iso = start.date().isoformat()
            bucket_starts.setdefault(iso, start)
            bucket = buckets.setdefault(iso, {})
            raw = row["result_data"] or {}
            for synthetic, fk in source_synthetics:
                value = _safe_float(raw.get(fk))
                if value is None:
                    continue
                bucket.setdefault(synthetic, []).append(value)

    # Render bucket list newest-last so the line chart reads left → right
    # in chronological order.
    sorted_isos = sorted(bucket_starts.keys())
    buckets_payload = []
    for iso in sorted_isos:
        start = bucket_starts[iso]
        per_field = buckets.get(iso, {})
        means: dict[str, float] = {}
        for f in fields_meta:
            values = per_field.get(f["key"]) or []
            if values:
                means[f["key"]] = round(sum(values) / len(values), 4)
        buckets_payload.append(
            {
                "label": _bucket_label(start, bucket_size),
                "iso": iso,
                "values": means,
            }
        )

    has_any_data = any(b["values"] for b in buckets_payload)

    return {
        "chart_type": ChartType.TEAM_TREND_LINE.value,
        "title": widget.title,
        "fields": fields_meta,
        "default_field_key": fields_meta[0]["key"] if fields_meta else "",
        "bucket_size": bucket_size,
        "grouping": "none",
        "buckets": buckets_payload,
        "empty": not has_any_data,
    }


# Default position color palette. Keys match the most common abbreviations
# in the demo data; admins overriding via `display_config.position_colors`
# can use the position UUID as the key for full precision.
_POSITION_COLORS_BY_ABBR = {
    "POR": "#a855f7",  # purple — goalkeepers
    "DF":  "#3b82f6",  # blue
    "MC":  "#10b981",  # green
    "DEL": "#f97316",  # orange
}
_POSITION_DEFAULT_PALETTE = [
    "#a855f7", "#3b82f6", "#10b981", "#f97316",
    "#ec4899", "#14b8a6", "#facc15", "#64748b",
]
_NO_POSITION_COLOR = "#9ca3af"


def _position_color(idx: int, abbr: str, overrides: dict[str, str]) -> str:
    """Pick a color for a position group. Override key precedence: position
    UUID > abbreviation > positional fallback in the default palette."""
    if abbr in overrides:
        return overrides[abbr]
    if abbr in _POSITION_COLORS_BY_ABBR:
        return _POSITION_COLORS_BY_ABBR[abbr]
    return _POSITION_DEFAULT_PALETTE[idx % len(_POSITION_DEFAULT_PALETTE)]


def _resolve_team_trend_line_by_position(
    widget: TeamReportWidget,
    fields_meta: list[dict[str, Any]],
    players: list[Player],
    sources: list,
    bucket_size: str,
    _make_key,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict[str, Any]:
    """Variant of `_resolve_team_trend_line` that emits one series per
    position. The team-wide path stays untouched; this one only runs
    when `display_config.group_by == "position"`.

    `groups` carries the legend (position id + label + color); each
    bucket carries `values_by_group[position_id][field_key] = mean`.
    Players without a position bucket into a synthetic "Sin posición"
    group with `id="__none__"`.
    """
    overrides = (widget.display_config or {}).get("position_colors") or {}

    # Build the group list — preserve sort_order, then by name. Players
    # without a position get bucketed under a synthetic "Sin posición"
    # entry only if any such player actually exists in scope.
    seen_position_pks: dict[UUID, Position] = {}
    has_no_position = False
    for p in players:
        if p.position is None:
            has_no_position = True
        else:
            seen_position_pks.setdefault(p.position_id, p.position)
    ordered_positions = sorted(
        seen_position_pks.values(),
        key=lambda pos: (pos.sort_order, pos.name),
    )

    groups: list[dict[str, Any]] = []
    for i, pos in enumerate(ordered_positions):
        groups.append({
            "id": str(pos.id),
            "label": pos.abbreviation or pos.name,
            "name": pos.name,
            "color": _position_color(i, pos.abbreviation or "", overrides),
        })
    if has_no_position:
        groups.append({
            "id": "__none__",
            "label": "S/P",
            "name": "Sin posición",
            "color": _NO_POSITION_COLOR,
        })

    # Player → group bucket key.
    player_group: dict[UUID, str] = {}
    for p in players:
        player_group[p.id] = str(p.position_id) if p.position_id else "__none__"

    # bucket_iso → group_key → field_key → list[float]
    buckets: dict[str, dict[str, dict[str, list[float]]]] = {}
    bucket_starts: dict[str, datetime] = {}

    for source in sources:
        source_synthetics = [
            (_make_key(source.pk, fk), fk) for fk in source.field_keys or []
        ]
        if not source_synthetics:
            continue
        results = _apply_date_window(
            ExamResult.objects
            .filter(
                template__family_id=source.template.family_id,
                player_id__in=player_group.keys(),
            ),
            date_from, date_to,
        ).order_by("recorded_at").values("player_id", "recorded_at", "result_data")
        for row in results:
            group_key = player_group.get(row["player_id"])
            if group_key is None:
                continue
            start = _bucket_start(row["recorded_at"], bucket_size)
            iso = start.date().isoformat()
            bucket_starts.setdefault(iso, start)
            per_group = buckets.setdefault(iso, {})
            per_field = per_group.setdefault(group_key, {})
            raw = row["result_data"] or {}
            for synthetic, fk in source_synthetics:
                value = _safe_float(raw.get(fk))
                if value is None:
                    continue
                per_field.setdefault(synthetic, []).append(value)

    sorted_isos = sorted(bucket_starts.keys())
    buckets_payload: list[dict[str, Any]] = []
    for iso in sorted_isos:
        start = bucket_starts[iso]
        per_group = buckets.get(iso, {})
        values_by_group: dict[str, dict[str, float]] = {}
        for g in groups:
            per_field = per_group.get(g["id"], {})
            means: dict[str, float] = {}
            for f in fields_meta:
                values = per_field.get(f["key"]) or []
                if values:
                    means[f["key"]] = round(sum(values) / len(values), 4)
            if means:
                values_by_group[g["id"]] = means
        buckets_payload.append({
            "label": _bucket_label(start, bucket_size),
            "iso": iso,
            "values_by_group": values_by_group,
        })

    has_any_data = any(b["values_by_group"] for b in buckets_payload)

    return {
        "chart_type": ChartType.TEAM_TREND_LINE.value,
        "title": widget.title,
        "fields": fields_meta,
        "default_field_key": fields_meta[0]["key"] if fields_meta else "",
        "bucket_size": bucket_size,
        "grouping": "position",
        "groups": groups,
        "buckets": buckets_payload,
        "empty": not has_any_data,
    }


def _resolve_team_horizontal_comparison_by_position(
    widget: TeamReportWidget,
    fields_meta: list[dict[str, Any]],
    players: list[Player],
    sources: list,
    _make_key,
    source_limits: dict[UUID, int],
    overall_limit: int,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict[str, Any]:
    """Position-grouped variant of `_resolve_team_horizontal_comparison`.

    Each "row" becomes a position (POR / DF / MC / DEL...) instead of a
    player. Bars represent the **last N monthly buckets** with the
    in-bucket mean across the position's players. Using monthly buckets
    here (not the original "last N individual readings") because at
    position level the natural narrative is "how did the defenders
    average over the last few months" rather than "which specific
    readings of which specific defenders".
    """
    # Position groups (same logic as in the trend-line variant — kept
    # local to avoid coupling the two helpers via a shared dependency).
    overrides = (widget.display_config or {}).get("position_colors") or {}
    seen_position_pks: dict[UUID, Position] = {}
    has_no_position = False
    for p in players:
        if p.position is None:
            has_no_position = True
        else:
            seen_position_pks.setdefault(p.position_id, p.position)
    ordered_positions = sorted(
        seen_position_pks.values(),
        key=lambda pos: (pos.sort_order, pos.name),
    )

    groups: list[dict[str, Any]] = []
    for i, pos in enumerate(ordered_positions):
        groups.append({
            "id": str(pos.id),
            "label": pos.abbreviation or pos.name,
            "name": pos.name,
            "color": _position_color(i, pos.abbreviation or "", overrides),
        })
    if has_no_position:
        groups.append({
            "id": "__none__",
            "label": "S/P",
            "name": "Sin posición",
            "color": _NO_POSITION_COLOR,
        })

    player_group: dict[UUID, str] = {}
    for p in players:
        player_group[p.id] = str(p.position_id) if p.position_id else "__none__"

    # bucket_iso → group_key → field_key → [values]
    monthly_buckets: dict[str, dict[str, dict[str, list[float]]]] = {}
    bucket_starts: dict[str, datetime] = {}

    for source in sources:
        source_synthetics = [
            (_make_key(source.pk, fk), fk) for fk in source.field_keys or []
        ]
        if not source_synthetics:
            continue
        results = _apply_date_window(
            ExamResult.objects
            .filter(
                template__family_id=source.template.family_id,
                player_id__in=player_group.keys(),
            ),
            date_from, date_to,
        ).order_by("recorded_at").values("player_id", "recorded_at", "result_data")
        for row in results:
            gkey = player_group.get(row["player_id"])
            if gkey is None:
                continue
            start = _bucket_start(row["recorded_at"], "month")
            iso = start.date().isoformat()
            bucket_starts.setdefault(iso, start)
            per_group = monthly_buckets.setdefault(iso, {})
            per_field = per_group.setdefault(gkey, {})
            raw = row["result_data"] or {}
            for synthetic, fk in source_synthetics:
                value = _safe_float(raw.get(fk))
                if value is None:
                    continue
                per_field.setdefault(synthetic, []).append(value)

    # Newest-first; we keep up to `overall_limit` monthly buckets per group.
    sorted_isos_desc = sorted(bucket_starts.keys(), reverse=True)

    rows: list[dict[str, Any]] = []
    for g in groups:
        values_by_field: dict[str, list[dict[str, Any]]] = {
            f["key"]: [] for f in fields_meta
        }
        for iso in sorted_isos_desc:
            start = bucket_starts[iso]
            per_field = monthly_buckets.get(iso, {}).get(g["id"], {})
            for f in fields_meta:
                bucket_vals = per_field.get(f["key"]) or []
                if not bucket_vals:
                    continue
                bucket_list = values_by_field[f["key"]]
                if len(bucket_list) >= overall_limit:
                    continue
                bucket_list.append({
                    "value": round(sum(bucket_vals) / len(bucket_vals), 4),
                    "label": _bucket_label(start, "month"),
                    "iso": iso,
                })
        rows.append({
            "group_id": g["id"],
            "group_label": g["label"],
            "group_name": g["name"],
            "color": g["color"],
            "values": values_by_field,
        })

    has_any_data = any(
        any(values for values in row["values"].values()) for row in rows
    )

    return {
        "chart_type": ChartType.TEAM_HORIZONTAL_COMPARISON.value,
        "title": widget.title,
        "grouping": "position",
        "groups": groups,
        "fields": fields_meta,
        "default_field_key": fields_meta[0]["key"] if fields_meta else "",
        "limit_per_player": overall_limit,
        "rows": rows,
        "empty": not has_any_data,
    }


# ---------------------------------------------------------------------------
# team_distribution
# ---------------------------------------------------------------------------


def _resolve_team_distribution(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Histogram of latest values across the roster for a single metric.

    Reads its data binding from the widget's first `TeamReportWidgetDataSource`:
    the first `field_keys` entry is the metric to bin. Single-source by
    design — distribution comparisons of two metrics belong on `multi_line`
    or `team_trend_line`, not a histogram.

    `display_config`:
        { "bin_count": 8 }   // default 8, clamped to [3, 30]

    `display_config` (extras):
        { "bin_count": 8, "coloring": "none" }
        - `coloring`: "none" disables band-based bin coloring even if the
          field has `reference_ranges`. Anything else (default / omitted)
          is treated as "auto" — color bins by the band their midpoint
          falls into, and emit a `band_counts` summary.

    Returns:
        {
            "chart_type": "team_distribution",
            "title": "...",
            "field": {"key": "imc", "label": "IMC", "unit": "kg/m²"},
            "bin_count": 8,
            "bins": [
                {
                    "low": 18.5, "high": 20.0,
                    "count": 2,
                    "players": [{"id": "...", "name": "...", "value": 18.7}, ...],
                    "color": "#16a34a",            // present when band-colored
                    "band_label": "Élite",         // present when band-colored
                },
                ...
            ],
            "stats": {
                "n": 18, "mean": 22.3, "median": 22.1,
                "min": 18.7, "max": 28.9
            },
            "band_counts": [
                {"label": "Élite", "color": "#16a34a",
                 "min": null, "max": 30, "count": 12},
                ...
            ],  // present only when band coloring is active and the field
                // has at least one configured band.
            "empty": false
        }
    """
    source = widget.data_sources.first()
    if source is None:
        return _empty(
            widget,
            ChartType.TEAM_DISTRIBUTION.value,
            error=(
                "Configura una Data Source en este widget: elige la plantilla "
                "y el campo numérico a histogramar."
            ),
        )
    field_keys = source.field_keys or []
    if not field_keys:
        return _empty(
            widget,
            ChartType.TEAM_DISTRIBUTION.value,
            error=(
                f"La data source para '{source.template.name}' no tiene "
                f"field_keys. Agrega la clave del campo numérico."
            ),
        )
    field_key = field_keys[0]
    template: ExamTemplate = source.template
    field_meta = _field_meta(template, field_key)

    display_config = widget.display_config or {}
    bin_count = max(3, min(int(display_config.get("bin_count") or 8), 30))

    players = list(_roster_query(category, position_id, player_ids))
    player_index = {p.id: p for p in players}
    if not player_index:
        return _empty(
            widget,
            ChartType.TEAM_DISTRIBUTION.value,
            error="",
        ) | {
            "field": {
                "key": field_key, "label": field_meta["label"],
                "unit": field_meta["unit"],
            },
        }

    # Collect each player's *latest* numeric value for this field, bounded
    # to the date window so distributions reflect the selected period.
    # Fan out across the template's version family — results from older
    # versions count unless the field key was renamed/removed on this one
    # (in which case `_safe_float(raw.get(field_key))` below returns None).
    results = _apply_date_window(
        ExamResult.objects
        .filter(
            template__family_id=template.family_id,
            player_id__in=player_index.keys(),
        ),
        date_from, date_to,
    ).order_by("player_id", "-recorded_at").values("player_id", "result_data")
    latest_by_player: dict[UUID, float] = {}
    for row in results:
        pid = row["player_id"]
        if pid in latest_by_player:
            continue
        value = _safe_float((row["result_data"] or {}).get(field_key))
        if value is None:
            continue
        latest_by_player[pid] = value

    payload_field = {
        "key": field_key,
        "label": field_meta["label"],
        "unit": field_meta["unit"],
    }

    if not latest_by_player:
        return {
            "chart_type": ChartType.TEAM_DISTRIBUTION.value,
            "title": widget.title,
            "field": payload_field,
            "bin_count": bin_count,
            "bins": [],
            "stats": {},
            "roster_size": len(player_index),
            "empty": True,
        }

    values = list(latest_by_player.values())
    n = len(values)
    lo = min(values)
    hi = max(values)
    sorted_values = sorted(values)
    median = (
        sorted_values[n // 2]
        if n % 2 == 1
        else (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2
    )
    mean = sum(values) / n

    # Edge case: all values identical → one bin with everyone in it.
    if hi == lo:
        bin_width = 1.0
        bin_count_eff = 1
    else:
        bin_width = (hi - lo) / bin_count
        bin_count_eff = bin_count

    bins: list[dict[str, Any]] = []
    for i in range(bin_count_eff):
        low = lo + i * bin_width
        high = lo + (i + 1) * bin_width if i < bin_count_eff - 1 else hi
        bins.append({"low": round(low, 4), "high": round(high, 4), "players": []})

    for pid, value in latest_by_player.items():
        if hi == lo:
            idx = 0
        else:
            # The last bin is inclusive of `hi` so the max value lands there.
            idx = min(int((value - lo) / bin_width), bin_count_eff - 1)
        player = player_index[pid]
        bins[idx]["players"].append(
            {
                "id": str(pid),
                "name": f"{player.first_name} {player.last_name}".strip(),
                "value": value,
            }
        )

    for b in bins:
        b["count"] = len(b["players"])

    # --- Band coloring overlay -------------------------------------------------
    # When the field has `reference_ranges` configured AND the widget hasn't
    # opted out via display_config.coloring == "none", we:
    #   1. Tag each bin with the color of the band its midpoint falls into.
    #   2. Emit a `band_counts` summary: how many players (by latest value)
    #      fall in each declared band.
    # Both are skipped silently when no bands are defined — the frontend
    # falls back to the default violet bars + base stats row.
    reference_ranges = field_meta.get("reference_ranges") or []
    coloring_mode = (display_config.get("coloring") or "auto")
    band_overlay = (
        coloring_mode != "none"
        and isinstance(reference_ranges, list)
        and len(reference_ranges) > 0
    )

    band_counts_payload: list[dict[str, Any]] | None = None
    if band_overlay:
        for b in bins:
            mid = (b["low"] + b["high"]) / 2.0
            band = _band_for_value(mid, reference_ranges)
            if band is not None:
                color = band.get("color")
                if color:
                    b["color"] = color
                b["band_label"] = band.get("label") or ""

        # Per-band counts use each player's *latest* numeric value (not the
        # bin midpoint) so the chips reflect reality, not bin-discretized
        # buckets. Players whose value falls outside every band (possible
        # when bands don't span the full real line) are dropped silently —
        # the sum of band_counts can be < n in that case.
        counts: list[dict[str, Any]] = []
        for band in reference_ranges:
            if not isinstance(band, dict):
                continue
            counts.append({
                "label": band.get("label") or "",
                "color": band.get("color"),
                "min": band.get("min"),
                "max": band.get("max"),
                "count": 0,
            })
        for value in latest_by_player.values():
            band = _band_for_value(value, reference_ranges)
            if band is None:
                continue
            # Walk in declared order; first-match-wins matches _band_for_value.
            for entry, src in zip(counts, reference_ranges):
                if src is band:
                    entry["count"] += 1
                    break
        band_counts_payload = counts

    result: dict[str, Any] = {
        "chart_type": ChartType.TEAM_DISTRIBUTION.value,
        "title": widget.title,
        "field": payload_field,
        "bin_count": bin_count_eff,
        "bins": bins,
        "stats": {
            "n": n,
            "mean": round(mean, 4),
            "median": round(median, 4),
            "min": round(lo, 4),
            "max": round(hi, 4),
        },
        # Frontend uses `roster_size` to decide whether to show the
        # "referencia limitada" badge (configured threshold lives there
        # so the rule is auditable on the client).
        "roster_size": len(player_index),
        "empty": False,
    }
    if band_counts_payload is not None:
        result["band_counts"] = band_counts_payload
    return result


# ---------------------------------------------------------------------------
# team_active_records
# ---------------------------------------------------------------------------


def _resolve_team_active_records(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,  # accepted but unused; see docstring
    date_to: datetime | None = None,    # accepted but unused; see docstring
) -> dict[str, Any]:
    """List of records currently "active" based on date-range fields.

    Note: `date_from`/`date_to` are accepted for signature parity but NOT
    applied — "active" is a single-instant question (as_of), not a window.
    Constraining the underlying ExamResult queryset by `recorded_at` would
    hide currently-active prescriptions whose row was created outside the
    selected window.

    Useful for non-episodic templates with a notion of "this row applies
    right now" — e.g. medication courses where today falls between
    `fecha_inicio` and `fecha_fin` (with `fecha_fin` optional / null
    meaning "ongoing").

    Single-source by design. The data source's `field_keys` are the
    columns to display per active record. Date-range bounds and the
    "as_of" override come from `display_config`:

        {
            "start_field": "fecha_inicio",   // default
            "end_field":   "fecha_fin",      // default; null end = ongoing
            "as_of":       "YYYY-MM-DD"      // optional, default = today
        }

    Each player contributes their *latest* active record (most recent
    `start_field` ≤ as_of). Players with no active record are excluded
    from the table — `total` reports the full roster size for context
    so the UI can show "5 / 18 con tratamiento activo".
    """
    from datetime import date as _date

    source = widget.data_sources.first()
    if source is None:
        return _empty(
            widget,
            ChartType.TEAM_ACTIVE_RECORDS.value,
            error=(
                "Configura una Data Source en este widget: elige la plantilla "
                "y los campos a mostrar como columnas."
            ),
        )
    field_keys = source.field_keys or []
    if not field_keys:
        return _empty(
            widget,
            ChartType.TEAM_ACTIVE_RECORDS.value,
            error=(
                f"La data source para '{source.template.name}' no tiene "
                f"field_keys. Agrega al menos uno para mostrar como columna."
            ),
        )

    template: ExamTemplate = source.template
    display_config = widget.display_config or {}
    start_field = display_config.get("start_field") or "fecha_inicio"
    end_field = display_config.get("end_field") or "fecha_fin"
    as_of_raw = display_config.get("as_of") or ""
    try:
        as_of = _date.fromisoformat(as_of_raw) if as_of_raw else _date.today()
    except (TypeError, ValueError):
        as_of = _date.today()

    columns = [
        {
            "key": fk,
            "label": _field_meta(template, fk)["label"],
            "unit": _field_meta(template, fk)["unit"],
        }
        for fk in field_keys
    ]

    players = list(_roster_query(category, position_id, player_ids))
    player_index = {p.id: p for p in players}

    def _parse_date(raw: Any) -> _date | None:
        if isinstance(raw, _date):
            return raw
        if not raw or not isinstance(raw, str):
            return None
        try:
            return _date.fromisoformat(raw[:10])
        except (TypeError, ValueError):
            return None

    # Pull all results for this template family newest-first per player,
    # then per player take the most recent reading whose start_field ≤ as_of
    # AND end_field ≥ as_of (or null/empty). Fan-out by family so a
    # medication started under v1 still surfaces as "active" after v2 forks.
    results = (
        ExamResult.objects
        .filter(
            template__family_id=template.family_id,
            player_id__in=player_index.keys(),
        )
        .order_by("player_id", "-recorded_at")
        .values("player_id", "recorded_at", "result_data")
    )
    active_by_player: dict[UUID, dict[str, Any]] = {}
    for row in results:
        pid = row["player_id"]
        if pid in active_by_player:
            continue
        raw = row["result_data"] or {}
        start = _parse_date(raw.get(start_field))
        end = _parse_date(raw.get(end_field))
        if start is None:
            continue
        if start > as_of:
            continue
        # Open-ended (no end date) → still active.
        if end is not None and end < as_of:
            continue
        active_by_player[pid] = {
            "started_at": start.isoformat(),
            "ends_at": end.isoformat() if end else None,
            "values": {fk: raw.get(fk) for fk in field_keys},
        }

    rows = []
    for p in players:
        record = active_by_player.get(p.id)
        if record is None:
            continue
        rows.append(
            {
                "player_id": str(p.id),
                "player_name": f"{p.first_name} {p.last_name}".strip(),
                "started_at": record["started_at"],
                "ends_at": record["ends_at"],
                "values": record["values"],
            }
        )

    return {
        "chart_type": ChartType.TEAM_ACTIVE_RECORDS.value,
        "title": widget.title,
        "columns": columns,
        "rows": rows,
        "as_of": as_of.isoformat(),
        "active_count": len(rows),
        "total": len(players),
        "start_field": start_field,
        "end_field": end_field,
        "empty": len(rows) == 0,
    }


# ---------------------------------------------------------------------------
# team_activity_coverage
# ---------------------------------------------------------------------------


def _resolve_team_activity_coverage(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,  # accepted but unused; see docstring
    date_to: datetime | None = None,    # accepted but unused; see docstring
) -> dict[str, Any]:
    """Operational "who's overdue for evaluation?" matrix.

    Rows = players, columns = templates configured on the widget's data
    sources. Each cell holds the number of days since that player's most
    recent ExamResult on that template (or null when they've never been
    evaluated).

    Note: `date_from` / `date_to` are accepted for signature parity but
    NOT applied — this widget is inherently "all-time, today is the
    reference". Bounding by recorded_at would silently hide players whose
    last evaluation falls outside the window, defeating the purpose.

    Reads data binding from EVERY `TeamReportWidgetDataSource` on the
    widget — each contributes one column. `field_keys` and `aggregation`
    are ignored; only the linked `template` matters.

    Returns:
        {
            "chart_type": "team_activity_coverage",
            "title": "...",
            "columns": [{"key": "<template_id>", "label": "...", "slug": "..."}, ...],
            "thresholds": {"green_max": 30, "yellow_max": 60},
            "rows": [
                {
                    "player_id": "<uuid>", "player_name": "Juan Pérez",
                    "cells": {
                        "<template_id>": {
                            "days_since": 14,
                            "last_iso": "2026-04-27",
                            "status": "ok" | "due" | "overdue" | "never"
                        },
                        ...
                    }
                },
                ...
            ],
            "as_of": "2026-05-11",
            "empty": false
        }
    """
    from datetime import date as _date

    sources = list(widget.data_sources.all().select_related("template"))
    if not sources:
        return _empty(
            widget,
            ChartType.TEAM_ACTIVITY_COVERAGE.value,
            error=(
                "Configura al menos una Data Source: cada una representa una "
                "plantilla cuyo cumplimiento se monitorea (CK, hidratación, etc.)."
            ),
        )

    # Thresholds (days) — configurable via display_config; defaults match
    # the "30 / 60" demo convention chosen with the user.
    display_config = widget.display_config or {}
    green_max = max(1, int(display_config.get("green_max") or 30))
    yellow_max = max(green_max + 1, int(display_config.get("yellow_max") or 60))

    players = list(_roster_query(category, position_id, player_ids))
    player_index = {p.id: p for p in players}

    # Build the column list: one per (source, template). Dedup by
    # template_id in case admins configured the same template twice.
    columns: list[dict[str, Any]] = []
    seen_template_ids: set[UUID] = set()
    template_objs: list[ExamTemplate] = []
    for source in sources:
        if source.template_id in seen_template_ids:
            continue
        seen_template_ids.add(source.template_id)
        template_objs.append(source.template)
        columns.append({
            "key": str(source.template_id),
            "label": source.template.name,
            "slug": source.template.slug,
        })

    if not template_objs or not players:
        return {
            "chart_type": ChartType.TEAM_ACTIVITY_COVERAGE.value,
            "title": widget.title,
            "columns": columns,
            "thresholds": {"green_max": green_max, "yellow_max": yellow_max},
            "rows": [],
            "as_of": _date.today().isoformat(),
            "empty": True,
        }

    today = _date.today()

    # Latest recorded_at per (player, family) — one query that fans out
    # across template versions. Cheap because Postgres collapses the
    # MAX aggregate over (template__family_id) groups efficiently.
    from django.db.models import Max
    family_ids = [t.family_id for t in template_objs]
    latest = (
        ExamResult.objects
        .filter(
            player_id__in=player_index.keys(),
            template__family_id__in=family_ids,
        )
        .values("player_id", "template__family_id")
        .annotate(last_at=Max("recorded_at"))
    )

    # Index by (player_id, family_id). Then we map back to template_id
    # via the columns since one family covers all its versions.
    last_by_pair: dict[tuple[UUID, UUID], datetime] = {}
    for row in latest:
        last_by_pair[(row["player_id"], row["template__family_id"])] = row["last_at"]

    family_by_column: dict[str, UUID] = {
        str(t.id): t.family_id for t in template_objs
    }

    def _classify(days: int | None) -> str:
        if days is None:
            return "never"
        if days <= green_max:
            return "ok"
        if days <= yellow_max:
            return "due"
        return "overdue"

    rows = []
    for player in players:
        cells: dict[str, dict[str, Any]] = {}
        for col in columns:
            family_id = family_by_column[col["key"]]
            last_at = last_by_pair.get((player.id, family_id))
            if last_at is None:
                cells[col["key"]] = {
                    "days_since": None,
                    "last_iso": None,
                    "status": "never",
                }
            else:
                days = (today - last_at.date()).days
                cells[col["key"]] = {
                    "days_since": days,
                    "last_iso": last_at.date().isoformat(),
                    "status": _classify(days),
                }
        rows.append({
            "player_id": str(player.id),
            "player_name": f"{player.first_name} {player.last_name}".strip(),
            "cells": cells,
        })

    return {
        "chart_type": ChartType.TEAM_ACTIVITY_COVERAGE.value,
        "title": widget.title,
        "columns": columns,
        "thresholds": {"green_max": green_max, "yellow_max": yellow_max},
        "rows": rows,
        "as_of": today.isoformat(),
        "empty": False,
    }


# ---------------------------------------------------------------------------
# team_leaderboard
# ---------------------------------------------------------------------------


def _resolve_team_leaderboard(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Top-N ranking by a single numeric metric.

    Reads its data binding from the widget's first `TeamReportWidgetDataSource`:
    first `field_keys` entry is the metric to rank by. `display_config`
    knobs:

        {
            "aggregator": "sum" | "avg" | "max" | "latest",  // default "sum"
            "limit": 5,                                       // default 5, clamp [3, 20]
            "order": "desc" | "asc"                           // default "desc"
        }

    `latest` returns each player's most recent value in the window;
    `sum` / `avg` / `max` aggregate across every result in the window.

    Returns:
        {
            "chart_type": "team_leaderboard",
            "title": "...",
            "field": {"key": "tot_dist_total", "label": "Distancia", "unit": "m"},
            "aggregator": "sum",
            "order": "desc",
            "limit": 5,
            "rows": [
                {"rank": 1, "player_id": "...", "player_name": "...", "value": 32450, "samples": 4},
                ...
            ],
            "empty": false
        }
    """
    source = widget.data_sources.first()
    if source is None:
        return _empty(
            widget,
            ChartType.TEAM_LEADERBOARD.value,
            error=(
                "Configura una Data Source en este widget: elige la "
                "plantilla y el campo numérico a rankear."
            ),
        )
    field_keys = source.field_keys or []
    if not field_keys:
        return _empty(
            widget,
            ChartType.TEAM_LEADERBOARD.value,
            error=(
                f"La data source para '{source.template.name}' no tiene "
                f"field_keys. Agrega la clave del campo numérico."
            ),
        )

    field_key = field_keys[0]
    template: ExamTemplate = source.template
    meta = _field_meta(template, field_key)

    display_config = widget.display_config or {}
    aggregator = display_config.get("aggregator") or "sum"
    if aggregator not in {"sum", "avg", "max", "latest"}:
        aggregator = "sum"
    limit = max(3, min(int(display_config.get("limit") or 5), 20))
    order = "asc" if display_config.get("order") == "asc" else "desc"

    players = list(_roster_query(category, position_id, player_ids))
    player_index = {p.id: p for p in players}
    if not player_index:
        return {
            "chart_type": ChartType.TEAM_LEADERBOARD.value,
            "title": widget.title,
            "field": {"key": field_key, "label": meta["label"], "unit": meta["unit"]},
            "aggregator": aggregator,
            "order": order,
            "limit": limit,
            "rows": [],
            "empty": True,
        }

    # Fan out across the template family for cross-version continuity.
    results = _apply_date_window(
        ExamResult.objects.filter(
            template__family_id=template.family_id,
            player_id__in=player_index.keys(),
        ),
        date_from, date_to,
    ).order_by("player_id", "-recorded_at").values(
        "player_id", "recorded_at", "result_data",
    )

    # Aggregate by player. Tracked: list of (recorded_at, value) so we can
    # compute sum/avg/max/latest from a single pass.
    samples_by_player: dict[UUID, list[tuple[datetime, float]]] = {}
    for row in results:
        v = _safe_float((row["result_data"] or {}).get(field_key))
        if v is None:
            continue
        samples_by_player.setdefault(row["player_id"], []).append(
            (row["recorded_at"], v),
        )

    def _aggregate(samples: list[tuple[datetime, float]]) -> float:
        values = [v for _, v in samples]
        if aggregator == "avg":
            return sum(values) / len(values)
        if aggregator == "max":
            return max(values)
        if aggregator == "latest":
            # Results already ordered newest-first per player (see queryset).
            return samples[0][1]
        return sum(values)

    ranked: list[tuple[UUID, float, int]] = []
    for pid, samples in samples_by_player.items():
        if not samples:
            continue
        ranked.append((pid, _aggregate(samples), len(samples)))

    ranked.sort(key=lambda triple: triple[1], reverse=(order == "desc"))
    top = ranked[:limit]

    rows = []
    for i, (pid, value, sample_count) in enumerate(top, start=1):
        player = player_index[pid]
        rows.append({
            "rank": i,
            "player_id": str(pid),
            "player_name": f"{player.first_name} {player.last_name}".strip(),
            "value": round(value, 4),
            "samples": sample_count,
        })

    return {
        "chart_type": ChartType.TEAM_LEADERBOARD.value,
        "title": widget.title,
        "field": {"key": field_key, "label": meta["label"], "unit": meta["unit"]},
        "aggregator": aggregator,
        "order": order,
        "limit": limit,
        "rows": rows,
        "empty": len(rows) == 0,
    }


# ---------------------------------------------------------------------------
# team_goal_progress
# ---------------------------------------------------------------------------


def _resolve_team_goal_progress(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,  # accepted but unused; see docstring
    date_to: datetime | None = None,    # accepted but unused; see docstring
) -> dict[str, Any]:
    """Roster × active-goals matrix.

    Columns: distinct `(template, field_key, operator, target_value)`
    tuples derived from every active goal in scope. Multiple players
    sharing the exact same goal collapse onto the same column. Players
    with a goal on a different template / target get their own columns.

    Scoping rules:
    - Active goals only (`status='active'`).
    - When the widget has `WidgetDataSource`s with templates → restrict
      to goals on those templates (any version, via family_id).
    - Otherwise → restrict to goals whose template is in the layout's
      `department` (same scoping logic as `_resolve_goal_card`).

    Note: `date_from` / `date_to` accepted for parity but NOT applied —
    same reasoning as goal_card; the cross-tab date filter has no
    bearing on future-target goals.

    Returns:
        {
            "chart_type": "team_goal_progress",
            "title": "...",
            "columns": [
                {
                    "key": "<column_id>",
                    "template_name": "Pentacompartimental",
                    "field_label": "Peso", "field_unit": "kg",
                    "operator": "<=", "target_value": 75.0,
                },
                ...
            ],
            "rows": [
                {
                    "player_id": "<uuid>", "player_name": "...",
                    "cells": {
                        "<column_id>": {
                            "goal_id": "<uuid>",
                            "current_value": 78.5,
                            "progress": {"achieved": false, "distance": 3.5, ...},
                            "due_date": "2026-08-01",
                            "days_to_due": 82,
                        }
                    }
                },
                ...
            ],
            "summary": {"achieved": 8, "in_progress": 12, "missed": 2, "no_data": 3, "total": 25},
            "empty": false
        }

    Players without ANY goal on the scoped columns still appear in
    `rows` with an empty `cells` dict — preserves the roster as the
    frame of reference (same posture as `roster_matrix`).
    """
    from datetime import date as _date
    from api.routers import _resolve_goal_current_value, _goal_progress  # noqa: WPS433
    from goals.models import Goal  # noqa: WPS433

    department = widget.section.layout.department

    sources = list(widget.data_sources.all().select_related("template"))

    # Build the goals queryset.
    goals_qs = (
        Goal.objects
        .filter(player__category=category, status="active")
        .select_related("template", "player")
    )
    if sources:
        family_ids = [s.template.family_id for s in sources if s.template_id]
        if family_ids:
            goals_qs = goals_qs.filter(template__family_id__in=family_ids)
    else:
        goals_qs = goals_qs.filter(template__department_id=department.id)

    # Limit to the active roster (respecting position + explicit subset).
    roster = list(_roster_query(category, position_id, player_ids))
    roster_ids = {p.id for p in roster}
    goals = [g for g in goals_qs if g.player_id in roster_ids]

    if not goals:
        return {
            "chart_type": ChartType.TEAM_GOAL_PROGRESS.value,
            "title": widget.title,
            "columns": [],
            "rows": [{
                "player_id": str(p.id),
                "player_name": f"{p.first_name} {p.last_name}".strip(),
                "cells": {},
            } for p in roster],
            "summary": {
                "achieved": 0, "in_progress": 0, "missed": 0,
                "no_data": 0, "total": 0,
            },
            "empty": True,
        }

    # Compute the column axis. Two goals collapse onto the same column
    # only when (template_family, field_key, operator, target_value) is
    # identical — otherwise they're conceptually different objectives.
    def _column_key(g: Goal) -> str:
        return f"{g.template.family_id}::{g.field_key}::{g.operator}::{g.target_value}"

    columns_by_key: dict[str, dict[str, Any]] = {}
    for g in goals:
        ck = _column_key(g)
        if ck in columns_by_key:
            continue
        meta = _field_meta(g.template, g.field_key)
        columns_by_key[ck] = {
            "key": ck,
            "template_name": g.template.name,
            "field_label": meta["label"],
            "field_unit": meta["unit"],
            "operator": g.operator,
            "target_value": float(g.target_value),
        }

    # Sort columns: by template_name → field_label → target_value.
    columns = sorted(
        columns_by_key.values(),
        key=lambda c: (c["template_name"], c["field_label"], c["target_value"]),
    )

    # Build rows + summary counters in a single pass.
    today = _date.today()
    cells_by_player: dict[UUID, dict[str, Any]] = {p.id: {} for p in roster}
    counters = {"achieved": 0, "in_progress": 0, "missed": 0, "no_data": 0}
    for g in goals:
        current, _ = _resolve_goal_current_value(g)
        progress = _goal_progress(g, current)
        days_to_due = (g.due_date - today).days
        if current is None:
            bucket = "no_data"
        elif progress["achieved"]:
            bucket = "achieved"
        elif days_to_due < 0:
            bucket = "missed"
        else:
            bucket = "in_progress"
        counters[bucket] += 1
        cells_by_player.setdefault(g.player_id, {})[_column_key(g)] = {
            "goal_id": str(g.id),
            "current_value": current,
            "progress": progress,
            "due_date": g.due_date.isoformat(),
            "days_to_due": days_to_due,
            "status": bucket,
        }

    rows = [
        {
            "player_id": str(p.id),
            "player_name": f"{p.first_name} {p.last_name}".strip(),
            "cells": cells_by_player.get(p.id, {}),
        }
        for p in roster
    ]

    summary = {
        **counters,
        "total": sum(counters.values()),
    }

    return {
        "chart_type": ChartType.TEAM_GOAL_PROGRESS.value,
        "title": widget.title,
        "columns": columns,
        "rows": rows,
        "summary": summary,
        "empty": False,
    }


# ---------------------------------------------------------------------------
# team_alerts
# ---------------------------------------------------------------------------


def _resolve_team_alerts(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
    player_ids: Sequence[UUID] | None = None,
    date_from: datetime | None = None,  # accepted; alerts are point-in-time
    date_to: datetime | None = None,
) -> dict[str, Any]:
    """Players ranked by active-alert count, scoped to the layout's department.

    Mirrors `_resolve_player_alerts` but groups by player and includes
    only players in the current category roster (after position /
    explicit-player filters). Each card surfaces the count + a preview
    of the player's individual alerts. Empty cards (zero alerts) are
    excluded — the widget answers "who's lighting up", not "who isn't".

    `display_config`:
      - `limit_per_player`: max alerts to inline per card (default 5).
      - `limit_players`: max player cards to return (default 30).
    """
    from goals.models import Alert, AlertRule, AlertStatus, AlertSource
    from goals.models import Goal

    department = widget.section.layout.department
    department_id = department.id

    display_config = widget.display_config or {}
    limit_per_player = max(1, min(int(display_config.get("limit_per_player") or 5), 20))
    limit_players = max(1, min(int(display_config.get("limit_players") or 30), 100))

    roster = list(_roster_query(category, position_id, player_ids))
    if not roster:
        return _empty(widget, ChartType.TEAM_ALERTS.value) | {
            "department_name": department.name,
        }
    roster_ids = {p.id for p in roster}
    roster_by_id = {p.id: p for p in roster}

    alerts = list(
        Alert.objects
        .filter(player_id__in=roster_ids, status=AlertStatus.ACTIVE)
        .order_by("player_id", "-fired_at")
    )
    if not alerts:
        return {
            "chart_type": ChartType.TEAM_ALERTS.value,
            "title": widget.title,
            "department_id": str(department_id),
            "department_name": department.name,
            "players": [],
            "total_alerts": 0,
            "empty": True,
        }

    # Same dept-resolution trick as the per-player resolver: batch lookup
    # source_id → template.department_id so the filter is a single query
    # per source kind.
    goal_ids = {
        a.source_id for a in alerts
        if a.source_type in (AlertSource.GOAL, AlertSource.GOAL_WARNING)
    }
    threshold_ids = {
        a.source_id for a in alerts if a.source_type == AlertSource.THRESHOLD
    }

    goal_meta: dict = {}
    if goal_ids:
        for g in (
            Goal.objects
            .filter(id__in=goal_ids)
            .select_related("template")
            .only(
                "id", "field_key",
                "template__id", "template__name", "template__department_id",
            )
        ):
            goal_meta[g.id] = {
                "template_id": g.template_id,
                "template_name": g.template.name,
                "department_id": g.template.department_id,
                "field_key": g.field_key,
            }

    rule_meta: dict = {}
    if threshold_ids:
        for r in (
            AlertRule.objects
            .filter(id__in=threshold_ids)
            .select_related("template")
            .only(
                "id", "field_key", "kind",
                "template__id", "template__name", "template__department_id",
            )
        ):
            rule_meta[r.id] = {
                "template_id": r.template_id,
                "template_name": r.template.name,
                "department_id": r.template.department_id,
                "field_key": r.field_key,
                "kind": r.kind,
            }

    # Bucket alerts by player, only keeping those matching this department.
    severity_rank = {"critical": 3, "warning": 2, "info": 1}
    by_player: dict[UUID, list[dict[str, Any]]] = {}
    crit_count: dict[UUID, int] = {}
    max_severity: dict[UUID, str] = {}
    for a in alerts:
        if a.source_type in (AlertSource.GOAL, AlertSource.GOAL_WARNING):
            meta = goal_meta.get(a.source_id)
        elif a.source_type == AlertSource.THRESHOLD:
            meta = rule_meta.get(a.source_id)
        else:
            meta = None
        if meta is None or meta["department_id"] != department_id:
            continue
        item = {
            "id": str(a.id),
            "source_type": a.source_type,
            "severity": a.severity,
            "message": a.message,
            "fired_at": a.fired_at.isoformat(),
            "template_name": meta.get("template_name", ""),
            "field_key": meta.get("field_key", ""),
        }
        by_player.setdefault(a.player_id, []).append(item)
        if a.severity == "critical":
            crit_count[a.player_id] = crit_count.get(a.player_id, 0) + 1
        prev = max_severity.get(a.player_id)
        if prev is None or severity_rank.get(a.severity, 0) > severity_rank.get(prev, 0):
            max_severity[a.player_id] = a.severity

    # Rank: critical-count desc → total-count desc → name asc. Surfaces
    # the most concerning players at the top without burying anyone
    # because of alphabetical order.
    ranked = sorted(
        by_player.items(),
        key=lambda kv: (
            -crit_count.get(kv[0], 0),
            -len(kv[1]),
            roster_by_id[kv[0]].last_name.lower(),
        ),
    )[:limit_players]

    cards: list[dict[str, Any]] = []
    total_alerts = 0
    for pid, items in ranked:
        player = roster_by_id[pid]
        cards.append({
            "player_id": str(pid),
            "player_name": f"{player.first_name} {player.last_name}".strip(),
            "alert_count": len(items),
            "critical_count": crit_count.get(pid, 0),
            "max_severity": max_severity.get(pid, "info"),
            "alerts": items[:limit_per_player],
        })
        total_alerts += len(items)

    return {
        "chart_type": ChartType.TEAM_ALERTS.value,
        "title": widget.title,
        "department_id": str(department_id),
        "department_name": department.name,
        "players": cards,
        "total_alerts": total_alerts,
        # Cards can drop to zero AFTER filtering even when raw alerts exist
        # (e.g. all alerts belong to a different department); treat that as
        # empty so the frontend renders the friendly "Sin alertas" state.
        "empty": len(cards) == 0,
    }
