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

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from core.models import Category, Player
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
) -> dict[str, Any]:
    """Resolve a team-scoped widget against a category roster.

    Optional `position_id` narrows the roster to players at one position
    (Goalkeeper, Defender, …). Applied uniformly across all team widgets
    so the report page's position picker affects every chart consistently.
    """
    chart_type = widget.chart_type
    if chart_type == ChartType.TEAM_HORIZONTAL_COMPARISON.value:
        return _resolve_team_horizontal_comparison(widget, category, position_id=position_id)
    if chart_type == ChartType.TEAM_ROSTER_MATRIX.value:
        return _resolve_team_roster_matrix(widget, category, position_id=position_id)
    if chart_type == ChartType.TEAM_STATUS_COUNTS.value:
        return _resolve_team_status_counts(widget, category, position_id=position_id)
    if chart_type == ChartType.TEAM_TREND_LINE.value:
        return _resolve_team_trend_line(widget, category, position_id=position_id)
    if chart_type == ChartType.TEAM_DISTRIBUTION.value:
        return _resolve_team_distribution(widget, category, position_id=position_id)
    if chart_type == ChartType.TEAM_ACTIVE_RECORDS.value:
        return _resolve_team_active_records(widget, category, position_id=position_id)
    return _empty(widget, chart_type, error=f"Unsupported chart type: {chart_type}")


def _roster_query(category: Category, position_id: UUID | None):
    """Active-player queryset for the category, optionally narrowed by position."""
    qs = Player.objects.filter(category_id=category.id, is_active=True)
    if position_id is not None:
        qs = qs.filter(position_id=position_id)
    return qs.order_by("last_name", "first_name")


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
    """Look up label/unit for a field key on the template schema."""
    for field in (template.config_schema or {}).get("fields", []):
        if isinstance(field, dict) and field.get("key") == key:
            return {
                "label": field.get("label", key),
                "unit": field.get("unit", ""),
                "type": field.get("type", ""),
            }
    return {"label": key, "unit": "", "type": ""}


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
                "Configurá una Data Source en este widget: elegí la plantilla "
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
                "Agregá al menos una clave numérica a graficar."
            ),
        )

    multi_source = len(sources) > 1

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

    players = list(_roster_query(category, position_id))
    player_index = {p.id: p for p in players}

    # Initialize buckets keyed by every synthetic key.
    by_player: dict[UUID, dict[str, list[dict[str, Any]]]] = {
        p.id: {f["key"]: [] for f in fields_meta} for p in players
    }

    # One query per source — different templates need different `template_id`
    # filters. Cheap with our roster sizes.
    for source in sources:
        results = (
            ExamResult.objects
            .filter(template_id=source.template_id, player_id__in=player_index.keys())
            .order_by("player_id", "-recorded_at")
            .values("player_id", "recorded_at", "result_data")
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
                "Configurá una Data Source en este widget: elegí la plantilla "
                "y los campos numéricos a graficar como columnas."
            ),
        )
    if not any(s.field_keys for s in sources):
        return _empty(
            widget,
            ChartType.TEAM_ROSTER_MATRIX.value,
            error=(
                "Las data sources de este widget no tienen field_keys. "
                "Agregá al menos una clave numérica para usar como columna."
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
                {"key": synthetic, "label": label, "unit": meta["unit"]}
            )
            column_origin[synthetic] = (source.pk, fk)

    display_config = widget.display_config or {}

    coloring_raw = display_config.get("coloring", "none")
    coloring = coloring_raw if coloring_raw in {"none", "vs_team_range"} else "none"

    variation_raw = display_config.get("variation", "off")
    variation = (
        variation_raw if variation_raw in {"off", "absolute", "percent"} else "off"
    )

    players = list(_roster_query(category, position_id))
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

        results = (
            ExamResult.objects
            .filter(template_id=source.template_id, player_id__in=player_index.keys())
            .order_by("player_id", "-recorded_at")
            .values("player_id", "recorded_at", "result_data")
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
) -> dict[str, Any]:
    """Squad availability snapshot — answers "who's ready to play?"

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
                "Configurá una Data Source en este widget: elegí la plantilla "
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

    players = list(_roster_query(category, position_id))
    player_index = {p.id: p for p in players}

    # Most recent open Episode per player on this template. A player can
    # technically have several concurrent injuries — we surface the most
    # recently started one for the headline. (Adding multi-episode
    # awareness is a v2 enhancement; current need is the squad snapshot.)
    open_episodes = (
        Episode.objects
        .filter(
            template_id=template.id,
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
) -> dict[str, Any]:
    """Multi-series line chart: team average per metric over time.

    Walks every `TeamReportWidgetDataSource` on the widget — same multi-
    source pattern as `team_horizontal_comparison`. Each (source × field_key)
    contributes one selectable series. Values are bucketed by week (default)
    or month and averaged across all readings from the (filtered) roster
    falling into each bucket.

    `display_config`:
        { "bucket_size": "week" | "month" }   // default "week"

    Returns:
        {
            "chart_type": "team_trend_line",
            "title": "...",
            "fields": [{"key": "...", "label": "...", "unit": "..."}, ...],
            "default_field_key": "...",
            "bucket_size": "week",
            "buckets": [
                {
                    "label": "S35 2025",
                    "iso": "2025-08-25",
                    "values": {"<key>": 23.4, ...}   // mean across roster
                },
                ...
            ],
            "empty": false
        }
    """
    sources = list(widget.data_sources.all().select_related("template"))
    if not sources:
        return _empty(
            widget,
            ChartType.TEAM_TREND_LINE.value,
            error=(
                "Configurá una Data Source en este widget: elegí la plantilla "
                "y los campos numéricos a graficar como series."
            ),
        )
    if not any(s.field_keys for s in sources):
        return _empty(
            widget,
            ChartType.TEAM_TREND_LINE.value,
            error=(
                "Las data sources de este widget no tienen field_keys. "
                "Agregá al menos una clave numérica para graficar."
            ),
        )

    multi_source = len(sources) > 1
    display_config = widget.display_config or {}
    bucket_raw = display_config.get("bucket_size", "week")
    bucket_size = bucket_raw if bucket_raw in {"week", "month"} else "week"

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

    players = list(_roster_query(category, position_id))
    player_index = {p.id: p for p in players}
    if not player_index:
        return {
            "chart_type": ChartType.TEAM_TREND_LINE.value,
            "title": widget.title,
            "fields": fields_meta,
            "default_field_key": fields_meta[0]["key"] if fields_meta else "",
            "bucket_size": bucket_size,
            "buckets": [],
            "empty": True,
        }

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
        results = (
            ExamResult.objects
            .filter(template_id=source.template_id, player_id__in=player_index.keys())
            .order_by("recorded_at")
            .values("recorded_at", "result_data")
        )
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
        "buckets": buckets_payload,
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
) -> dict[str, Any]:
    """Histogram of latest values across the roster for a single metric.

    Reads its data binding from the widget's first `TeamReportWidgetDataSource`:
    the first `field_keys` entry is the metric to bin. Single-source by
    design — distribution comparisons of two metrics belong on `multi_line`
    or `team_trend_line`, not a histogram.

    `display_config`:
        { "bin_count": 8 }   // default 8, clamped to [3, 30]

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
                    "players": [{"id": "...", "name": "...", "value": 18.7}, ...]
                },
                ...
            ],
            "stats": {
                "n": 18, "mean": 22.3, "median": 22.1,
                "min": 18.7, "max": 28.9
            },
            "empty": false
        }
    """
    source = widget.data_sources.first()
    if source is None:
        return _empty(
            widget,
            ChartType.TEAM_DISTRIBUTION.value,
            error=(
                "Configurá una Data Source en este widget: elegí la plantilla "
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
                f"field_keys. Agregá la clave del campo numérico."
            ),
        )
    field_key = field_keys[0]
    template: ExamTemplate = source.template
    field_meta = _field_meta(template, field_key)

    display_config = widget.display_config or {}
    bin_count = max(3, min(int(display_config.get("bin_count") or 8), 30))

    players = list(_roster_query(category, position_id))
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

    # Collect each player's *latest* numeric value for this field.
    results = (
        ExamResult.objects
        .filter(template_id=template.id, player_id__in=player_index.keys())
        .order_by("player_id", "-recorded_at")
        .values("player_id", "result_data")
    )
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

    return {
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
        "empty": False,
    }


# ---------------------------------------------------------------------------
# team_active_records
# ---------------------------------------------------------------------------


def _resolve_team_active_records(
    widget: TeamReportWidget,
    category: Category,
    *,
    position_id: UUID | None = None,
) -> dict[str, Any]:
    """List of records currently "active" based on date-range fields.

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
                "Configurá una Data Source en este widget: elegí la plantilla "
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
                f"field_keys. Agregá al menos uno para mostrar como columna."
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

    players = list(_roster_query(category, position_id))
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

    # Pull all results for this (template, category) newest-first per player,
    # then per player take the most recent reading whose start_field ≤ as_of
    # AND end_field ≥ as_of (or null/empty).
    results = (
        ExamResult.objects
        .filter(template_id=template.id, player_id__in=player_index.keys())
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
