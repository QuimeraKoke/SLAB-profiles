"""Per-(department, category) configurable visualization layouts.

The platform admin composes a `DepartmentLayout` from `LayoutSection`s, each
holding ordered `Widget`s. Each widget declares the visual it renders
(`chart_type`) and one or more `WidgetDataSource`s telling the API which exam
template + which fields + which time window to feed it.

The frontend stays a dumb client: the API resolves layouts, runs the configured
aggregation server-side, and returns ready-to-render payloads keyed by
`chart_type`. The frontend's job is just to map `chart_type` → component.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Iterable

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

from core.models import Category, Department
from exams.models import ExamTemplate


class ChartType(models.TextChoices):
    """Registry of supported chart presets.

    Adding a new visualization is a four-step process:
    1. Add a value here.
    2. Implement aggregation in `dashboards.aggregation.resolve_widget`.
    3. Add a renderer to the frontend's dashboard widget registry.
    4. (Optional) Document the data-source shape it expects below.
    """

    # 1 source, aggregation=last_n, multiple field_keys
    # Renders a left-to-right comparison table of the last N takes.
    COMPARISON_TABLE = "comparison_table", "Comparison table (last N takes)"

    # 1 source, aggregation=all, multiple field_keys (user picks which to plot)
    # Renders a line chart with a field selector dropdown.
    LINE_WITH_SELECTOR = "line_with_selector", "Line chart with field selector"

    # 1 source, aggregation=last_n, multiple field_keys
    # Renders one donut chart per result, one slice per field.
    DONUT_PER_RESULT = "donut_per_result", "Donut chart per result"

    # 1 source, aggregation=last_n, multiple field_keys
    # Renders a grouped bar chart (one group per result, one bar per field).
    GROUPED_BAR = "grouped_bar", "Grouped bar chart"

    # 1 source, aggregation=all (or last_n), multiple field_keys.
    # Renders one overlaid line per field, sharing a single x-axis. Use when
    # you want all series visible at once (vs. line_with_selector's dropdown).
    MULTI_LINE = "multi_line", "Multi-series line chart"

    # 1 source (GPS entrenamiento). Radar comparing the latest training
    # session's GPS variables as a % of the player's chronic match load.
    TRAINING_RADAR = "training_radar", "Radar: entrenamiento vs carga crónica"

    # 1 source, aggregation=latest. Display config defines reference targets.
    # Reserved — V1 ships with the renderer falling back to "Unsupported".
    REFERENCE_CARD = "reference_card", "Reference card (current vs target)"

    # 1 source, aggregation=all, on a "Goals" template (Metas).
    # Reserved — V1 ships with the renderer falling back to "Unsupported".
    GOALS_LIST = "goals_list", "Goals list"

    # N sources, aggregation=all per source, 1 field_key each.
    # Reserved — V1 ships with the renderer falling back to "Unsupported".
    CROSS_EXAM_LINE = "cross_exam_line", "Cross-exam line chart"

    # 1 source, aggregation=all (or last_n), exactly 1 categorical field_key
    # whose options carry `option_regions` mappings to body parts.
    # Renders a human silhouette colored by counts per region.
    BODY_MAP_HEATMAP = "body_map_heatmap", "Body map heatmap (counts per region)"

    # Team-scoped chart types — used by `TeamReportLayout` only. Config lives
    # on `TeamReportWidget.config` (JSONField), not WidgetDataSource. See
    # `dashboards/team_aggregation.py` for the resolver dispatch.

    # Per-player horizontal bar groups, one bar per recent reading. Config:
    #   { "template_id": UUID, "field_key": str, "limit_per_player": int }
    TEAM_HORIZONTAL_COMPARISON = (
        "team_horizontal_comparison",
        "Team — horizontal bars (player vs. past values)",
    )

    # Roster matrix: rows = players, columns = field keys (one per metric),
    # cells = latest value per (player, field). Optional vs-team-range or
    # vs-target coloring via `display_config`. See team_aggregation.py.
    TEAM_ROSTER_MATRIX = (
        "team_roster_matrix",
        "Team — roster matrix (latest values per player × metric)",
    )

    # Squad availability snapshot — for episodic templates only. Buckets each
    # player by the stage of their most-recent open episode, or "available"
    # when no open episode exists. Headline: "X de Y disponibles". See
    # `_resolve_team_status_counts` in team_aggregation.py.
    TEAM_STATUS_COUNTS = (
        "team_status_counts",
        "Team — squad availability (ready / partial / out)",
    )

    # Multi-series line chart of team averages over time. One or more
    # field_keys (across one or more templates) become selectable lines;
    # values are bucketed by week or month and averaged across the roster.
    TEAM_TREND_LINE = (
        "team_trend_line",
        "Team — trend line (team average over time)",
    )

    # Histogram of latest values across the roster for a single metric.
    # Surfaces clusters and outliers ("most of the squad sits at IMC 22-24,
    # with two outliers above 27").
    TEAM_DISTRIBUTION = (
        "team_distribution",
        "Team — distribution histogram (latest values across the roster)",
    )

    # Currently-active records, keyed on date-range fields (e.g. medication
    # courses where today falls between fecha_inicio and fecha_fin). Works
    # without the Episode model — useful for non-episodic templates that
    # still have a notion of "this record is active right now".
    TEAM_ACTIVE_RECORDS = (
        "team_active_records",
        "Team — active records (date-range filtered)",
    )

    # Roster × template matrix tracking how many days have passed since
    # each player's most recent result on each template. Drives the
    # operational "who's overdue for evaluation?" question — green when
    # recent, yellow when due-ish, red when overdue, gray when never.
    TEAM_ACTIVITY_COVERAGE = (
        "team_activity_coverage",
        "Team — activity coverage (days since last result per template)",
    )

    # Top-N leaderboard for a single numeric metric. Aggregates each
    # player's results in the current window (sum / avg / max / latest)
    # and ranks. Visual flair for demos + a quick "who's leading?"
    # answer for staff.
    TEAM_LEADERBOARD = (
        "team_leaderboard",
        "Team — leaderboard (top N by a metric)",
    )

    # Per-player goal-vs-current cards. Each card surfaces a Goal's
    # target, the player's latest reading on the goal's (template,
    # field_key), and a status badge driven by the operator. Renders
    # in Department layouts; auto-filters goals to those tied to
    # templates in the same department (or to the widget's data source
    # template when one is configured).
    GOAL_CARD = (
        "goal_card",
        "Goal — current vs target cards",
    )

    # Team-wide goal progress matrix. Rows = players, columns = goal
    # axes (per template + field_key). Each cell shows the player's
    # current value vs target with an achieved / in-progress / missed
    # badge driven by the operator semantics. Useful for "qué % del
    # plantel está on-track con sus objetivos" questions.
    TEAM_GOAL_PROGRESS = (
        "team_goal_progress",
        "Team — goal progress matrix (roster × goals)",
    )

    # Per-player list of active alerts. Filters by the widget's containing
    # department (alerts whose source's template belongs to that
    # department). Used in Department layouts (player view). No data
    # sources required — the widget reads straight from the Alert table.
    PLAYER_ALERTS = (
        "player_alerts",
        "Player — active alerts list (filtered by department)",
    )

    # Roster ranked by active-alert count. Each card lists the player's
    # active alerts (severity + message + fired_at), department-scoped by
    # the widget's layout. Used in TeamReportLayout. No data sources.
    TEAM_ALERTS = (
        "team_alerts",
        "Team — players ranked by active alert count",
    )

    # Per-player horizontal stacked bars. One row per player, one bar
    # split into N colored segments (one per field_key). Sort is by
    # the row's total (sum of all field values) descending — useful
    # for Acc + Dec breakdowns, period workload composition, etc.
    TEAM_STACKED_BARS = (
        "team_stacked_bars",
        "Team — stacked bars per player (composition of N fields)",
    )

    # Per-player activity log — last N ExamResults rendered as a
    # timeline list. Each entry shows date + a couple of summary fields
    # configured via the WidgetDataSource.field_keys. Used by the
    # 'Molestias' daily-log pattern in the medical department.
    ACTIVITY_LOG = (
        "activity_log",
        "Activity log (per-player timeline of recent entries)",
    )

    # Team-scoped variant: same shape but rosters across all players in
    # the category, newest first. Used for the team-wide medical-events
    # feed (lesiones / molestias / medicación combined chronology).
    TEAM_ACTIVITY_LOG = (
        "team_activity_log",
        "Team — activity log (recent entries across the roster)",
    )

    # Per-day grouped bars across the team: one X-axis tick per day in
    # the window, one bar per configured field (team mean for that
    # field on that day). Optional overlay line for the per-day SUM of
    # the field means (e.g. "Total Bienestar" on a Check-IN chart).
    TEAM_DAILY_GROUPED_BARS = (
        "team_daily_grouped_bars",
        "Team — daily grouped bars (N metrics × daily buckets)",
    )

    # Compact aggregate-statistics strip for a match. One mini-card per
    # configured field showing SUM / AVG / STD across the roster. Used
    # as the "team-wide totals" footer in match-scoped GPS layouts.
    TEAM_MATCH_SUMMARY = (
        "team_match_summary",
        "Team — match-aggregate statistics strip",
    )

    # Per-player season-stats table aggregated over a selectable set of
    # matches. Reads from EventParticipant (not ExamResult) so we can
    # surface citaciones / titular / minutes / goals / cards as a single
    # roster-wide view. Driven by the layout's match_selector_config
    # when mode="multi"; otherwise falls back to all in-window matches.
    TEAM_SEASON_STATS = (
        "team_season_stats",
        "Team — season stats per player (multi-match aggregate)",
    )


class Aggregation(models.TextChoices):
    LATEST = "latest", "Latest result only"
    LAST_N = "last_n", "Last N results"
    ALL = "all", "All results"


class DepartmentLayout(models.Model):
    """One layout per (department, category) pair.

    A category that wants the same layout as another should use the admin
    "Duplicate" action rather than sharing one row, so each category's layout
    can evolve independently.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="layouts"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="layouts"
    )
    name = models.CharField(
        max_length=120,
        default="Default",
        help_text="Internal label shown in admin lists.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="If unchecked, the API falls back to the legacy auto-rendered grid.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("department", "category")
        ordering = ("department__name", "category__name")
        verbose_name = "Player profile — Layout"
        verbose_name_plural = "Player profile — Layouts"

    def clean(self) -> None:
        super().clean()
        if self.department_id and self.category_id:
            if self.department.club_id != self.category.club_id:
                raise ValidationError(
                    "Department and category must belong to the same club."
                )
            if not self.category.departments.filter(pk=self.department_id).exists():
                raise ValidationError(
                    f"Category '{self.category}' has not opted in to department "
                    f"'{self.department}'. Add the department to the category first."
                )

    def __str__(self) -> str:
        return f"{self.department} – {self.category}"


class LayoutSection(models.Model):
    """A visual grouping of widgets within a layout (collapsible header)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    layout = models.ForeignKey(
        DepartmentLayout, on_delete=models.CASCADE, related_name="sections"
    )
    title = models.CharField(
        max_length=120,
        blank=True,
        help_text="Leave blank to render widgets without a section header.",
    )
    is_collapsible = models.BooleanField(default=True)
    default_collapsed = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Player profile — Section"
        verbose_name_plural = "Player profile — Sections"

    def __str__(self) -> str:
        return self.title or f"Section #{self.sort_order}"


class Widget(models.Model):
    """A single chart/card on the rendered layout."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(
        LayoutSection, on_delete=models.CASCADE, related_name="widgets"
    )
    chart_type = models.CharField(max_length=40, choices=ChartType.choices)
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=400, blank=True)
    column_span = models.PositiveSmallIntegerField(
        default=12,
        help_text="Width on a 12-column grid. 12 = full width, 6 = half, etc.",
    )
    chart_height = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Chart height in pixels. Leave blank to use the per-chart-type default "
            "(line ≈ 240, multi-line ≈ 280, grouped bar ≈ 220, donut ≈ 180). "
            "Recommended range: 160–600. Ignored for table-only widgets."
        ),
    )
    display_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Chart-specific knobs (axis labels, units, color overrides, etc.). "
            "Optional — sensible defaults apply when empty."
        ),
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Player profile — Widget"
        verbose_name_plural = "Player profile — Widgets"

    def __str__(self) -> str:
        return f"{self.title} ({self.get_chart_type_display()})"


class WidgetDataSource(models.Model):
    """One bound data feed for a widget.

    Most widgets need exactly one source. `cross_exam_line` and similar
    cross-template visualizations use multiple sources, each pointing at a
    different `ExamTemplate`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    widget = models.ForeignKey(
        Widget, on_delete=models.CASCADE, related_name="data_sources"
    )
    template = models.ForeignKey(
        ExamTemplate, on_delete=models.PROTECT, related_name="widget_data_sources"
    )
    field_keys = ArrayField(
        models.CharField(max_length=80),
        default=list,
        help_text=(
            "Keys from the chosen template's config_schema, e.g. "
            "['peso', 'masa_muscular']. Order matters — it drives column / "
            "legend order on the chart."
        ),
    )
    aggregation = models.CharField(
        max_length=20,
        choices=Aggregation.choices,
        default=Aggregation.LAST_N,
    )
    aggregation_param = models.PositiveIntegerField(
        default=3,
        help_text="N for `last_n`. Ignored for `latest` / `all`.",
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional override for legends / axis titles.",
    )
    color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional hex color for legends / chart series, e.g. '#3b82f6'.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Player profile — Widget data source"
        verbose_name_plural = "Player profile — Widget data sources"

    def clean(self) -> None:
        super().clean()
        if not self.template_id:
            return

        # Field keys must exist in the template schema.
        schema_keys = {
            f.get("key")
            for f in (self.template.config_schema or {}).get("fields", [])
            if isinstance(f, dict) and f.get("key")
        }
        unknown = [k for k in (self.field_keys or []) if k not in schema_keys]
        if unknown:
            raise ValidationError(
                {
                    "field_keys": (
                        f"Unknown field key(s) for template '{self.template.name}': "
                        f"{', '.join(unknown)}. Available: "
                        f"{', '.join(sorted(schema_keys)) or '(none defined)'}"
                    )
                }
            )

        # Template's department must match the layout's department, with two
        # exceptions: chart types that explicitly support cross-template data.
        CROSS_TEMPLATE_CHART_TYPES = {
            ChartType.CROSS_EXAM_LINE,
            ChartType.LINE_WITH_SELECTOR,
        }
        if self.widget_id:
            layout = self.widget.section.layout
            if self.template.department_id != layout.department_id:
                if self.widget.chart_type not in CROSS_TEMPLATE_CHART_TYPES:
                    raise ValidationError(
                        f"Template '{self.template.name}' is in department "
                        f"'{self.template.department}', but this widget lives in "
                        f"department '{layout.department}'. Use a "
                        f"'{ChartType.CROSS_EXAM_LINE.label}' or "
                        f"'{ChartType.LINE_WITH_SELECTOR.label}' widget if you "
                        f"intend to mix departments."
                    )
                if self.template.department.club_id != layout.department.club_id:
                    raise ValidationError(
                        "Cross-department sources must still come from the same club."
                    )

    def __str__(self) -> str:
        keys = ", ".join(self.field_keys[:3]) or "(no fields)"
        more = f" + {len(self.field_keys) - 3} more" if len(self.field_keys) > 3 else ""
        return f"{self.template.name} → [{keys}{more}]"


def field_lookup(template: ExamTemplate, key: str) -> dict | None:
    """Return the field config dict for a key in a template's schema, or None."""
    for field in (template.config_schema or {}).get("fields", []):
        if isinstance(field, dict) and field.get("key") == key:
            return field
    return None


def iter_template_fields(template: ExamTemplate) -> Iterable[dict]:
    """Iterate over all field config dicts in a template's schema."""
    for field in (template.config_schema or {}).get("fields", []):
        if isinstance(field, dict) and field.get("key"):
            yield field


# =============================================================================
# Team report layouts (parallel to DepartmentLayout — aggregate-across-roster
# views configured per (department, category)).
# =============================================================================


class TeamReportLayout(models.Model):
    """One team-wide report layout per (department, category) pair.

    Mirrors `DepartmentLayout`'s shape but its widgets resolve against the
    full category roster instead of one player. The frontend reads it from
    `GET /api/reports/{department_slug}?category_id=...` and renders the
    payload through a parallel team-widget registry.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="team_report_layouts"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="team_report_layouts"
    )
    name = models.CharField(
        max_length=120,
        default="Default",
        help_text="Internal label shown in admin lists.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "If unchecked, the API returns `{layout: null}` and the frontend "
            "shows the placeholder 'no report configured' state."
        ),
    )
    match_selector_config = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Per-match scoping for this layout. When enabled, the report page "
            "renders a match selector and every widget filters its data to the "
            "chosen Event. Shape: "
            '<code>{"enabled": true, "event_type": "match", "required": true, '
            '"label": "Partido", "show_recent": 10}</code>. '
            "Empty / disabled → date-window mode (current behavior)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("department", "category")
        ordering = ("department__name", "category__name")
        verbose_name = "Team report — Layout"
        verbose_name_plural = "Team report — Layouts"

    def clean(self) -> None:
        super().clean()
        if self.department_id and self.category_id:
            if self.department.club_id != self.category.club_id:
                raise ValidationError(
                    "Department and category must belong to the same club."
                )
            if not self.category.departments.filter(pk=self.department_id).exists():
                raise ValidationError(
                    f"Category '{self.category}' has not opted in to department "
                    f"'{self.department}'. Add the department to the category first."
                )

    def __str__(self) -> str:
        return f"{self.department} – {self.category} (team)"


class TeamReportSection(models.Model):
    """A visual grouping of widgets within a team report (collapsible header)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    layout = models.ForeignKey(
        TeamReportLayout, on_delete=models.CASCADE, related_name="sections"
    )
    title = models.CharField(
        max_length=120,
        blank=True,
        help_text="Leave blank to render widgets without a section header.",
    )
    is_collapsible = models.BooleanField(default=True)
    default_collapsed = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Team report — Section"
        verbose_name_plural = "Team report — Sections"

    def __str__(self) -> str:
        return self.title or f"Section #{self.sort_order}"


class TeamReportWidget(models.Model):
    """A single team-scoped chart on a `TeamReportLayout`.

    Mirrors per-player `Widget` shape:
    - The data binding (template + fields + aggregation) lives in one or
      more child `TeamReportWidgetDataSource` rows authored as inlines.
    - `display_config` (JSONField, optional) carries chart-type-specific
      *display* knobs only (e.g. "show_legend", "color_palette"). Default
      empty — the resolver picks sensible defaults.

    For `team_horizontal_comparison`: one data source, `aggregation=last_n`
    with `aggregation_param=N` (number of bars per player), and exactly
    one `field_keys` entry (the metric to plot).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(
        TeamReportSection, on_delete=models.CASCADE, related_name="widgets"
    )
    chart_type = models.CharField(
        max_length=40,
        choices=[
            (ChartType.TEAM_HORIZONTAL_COMPARISON.value, ChartType.TEAM_HORIZONTAL_COMPARISON.label),
            (ChartType.TEAM_ROSTER_MATRIX.value, ChartType.TEAM_ROSTER_MATRIX.label),
            (ChartType.TEAM_STATUS_COUNTS.value, ChartType.TEAM_STATUS_COUNTS.label),
            (ChartType.TEAM_TREND_LINE.value, ChartType.TEAM_TREND_LINE.label),
            (ChartType.TEAM_DISTRIBUTION.value, ChartType.TEAM_DISTRIBUTION.label),
            (ChartType.TEAM_ACTIVE_RECORDS.value, ChartType.TEAM_ACTIVE_RECORDS.label),
            (ChartType.TEAM_ACTIVITY_COVERAGE.value, ChartType.TEAM_ACTIVITY_COVERAGE.label),
            (ChartType.TEAM_LEADERBOARD.value, ChartType.TEAM_LEADERBOARD.label),
            (ChartType.TEAM_GOAL_PROGRESS.value, ChartType.TEAM_GOAL_PROGRESS.label),
            (ChartType.TEAM_ALERTS.value, ChartType.TEAM_ALERTS.label),
            (ChartType.TEAM_STACKED_BARS.value, ChartType.TEAM_STACKED_BARS.label),
            (ChartType.TEAM_MATCH_SUMMARY.value, ChartType.TEAM_MATCH_SUMMARY.label),
            (ChartType.TEAM_ACTIVITY_LOG.value, ChartType.TEAM_ACTIVITY_LOG.label),
            (ChartType.TEAM_DAILY_GROUPED_BARS.value, ChartType.TEAM_DAILY_GROUPED_BARS.label),
            (ChartType.TEAM_SEASON_STATS.value, ChartType.TEAM_SEASON_STATS.label),
        ],
    )
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=400, blank=True)
    column_span = models.PositiveSmallIntegerField(
        default=12,
        help_text="Width on a 12-column grid. 12 = full width, 6 = half, etc.",
    )
    chart_height = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Chart height in pixels. Leave blank for the per-chart-type default. "
            "For team_horizontal_comparison the default scales with roster size."
        ),
    )
    display_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Chart-specific display knobs (color palette, axis labels, etc.). "
            "Optional — sensible defaults apply when empty. The actual data "
            "binding lives in the Data Sources inline below."
        ),
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Team report — Widget"
        verbose_name_plural = "Team report — Widgets"

    def __str__(self) -> str:
        return f"{self.title} ({self.get_chart_type_display()})"


class TeamReportWidgetDataSource(models.Model):
    """One bound data feed for a `TeamReportWidget`.

    Mirrors `WidgetDataSource` exactly so the admin authoring UX is
    identical between per-player widgets and team widgets — pick a template,
    pick the field keys, pick the aggregation. Chart-type interpretation
    rules live in `dashboards/team_aggregation.py`.

    For `team_horizontal_comparison`: configure one source with
    `aggregation=last_n`, `aggregation_param=N` (e.g. 3 = the last 3
    readings), and a single field_key in `field_keys`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    widget = models.ForeignKey(
        TeamReportWidget, on_delete=models.CASCADE, related_name="data_sources"
    )
    template = models.ForeignKey(
        ExamTemplate, on_delete=models.PROTECT, related_name="team_widget_data_sources"
    )
    field_keys = ArrayField(
        models.CharField(max_length=80),
        default=list,
        help_text=(
            "Keys from the chosen template's config_schema. For "
            "team_horizontal_comparison only the first key is used; future "
            "team widgets may consume more."
        ),
    )
    aggregation = models.CharField(
        max_length=20,
        choices=Aggregation.choices,
        default=Aggregation.LAST_N,
    )
    aggregation_param = models.PositiveIntegerField(
        default=3,
        help_text="N for `last_n`. Drives bars-per-player on horizontal comparison.",
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional override for legends / axis titles.",
    )
    color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional hex color for legends / chart series, e.g. '#3b82f6'.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Team report — Widget data source"
        verbose_name_plural = "Team report — Widget data sources"

    def clean(self) -> None:
        super().clean()
        if not self.template_id:
            return

        # Field keys must exist in the template schema.
        schema_keys = {
            f.get("key")
            for f in (self.template.config_schema or {}).get("fields", [])
            if isinstance(f, dict) and f.get("key")
        }
        unknown = [k for k in (self.field_keys or []) if k not in schema_keys]
        if unknown:
            raise ValidationError(
                {
                    "field_keys": (
                        f"Unknown field key(s) for template '{self.template.name}': "
                        f"{', '.join(unknown)}. Available: "
                        f"{', '.join(sorted(schema_keys)) or '(none defined)'}"
                    )
                }
            )

        # All current team chart types tolerate cross-department sources —
        # squad availability in a Nutricional report ("who can I plan a
        # high-load meal for?"), GPS distance in a Médico report ("how
        # active are players in reintegration?"), etc. are all coherent
        # narratives. The same-club rule is still enforced below.
        #
        # When a future chart type genuinely depends on department-specific
        # config (e.g. a stat tied to the layout's department's clinic
        # protocols), add it to a deny-list and skip allowing it here.
        if self.widget_id:
            layout = self.widget.section.layout
            if (
                self.template.department_id != layout.department_id
                and self.template.department.club_id != layout.department.club_id
            ):
                raise ValidationError(
                    "Cross-department sources must still come from the same club."
                )

    def __str__(self) -> str:
        keys = ", ".join(self.field_keys[:3]) or "(no fields)"
        more = f" + {len(self.field_keys) - 3} more" if len(self.field_keys) > 3 else ""
        return f"{self.template.name} → [{keys}{more}]"


def _report_pdf_path(instance: "PlayerReportSnapshot", filename: str) -> str:
    return f"reports/{instance.kind}/{instance.player_id}/{filename}"


class PlayerReportSnapshot(models.Model):
    """Content-addressed cache of a generated player report PDF.

    Keyed on a hash of the report's *input data* (the triage payload minus
    volatile fields like generated_at) plus the LLM model and a render
    version. Same data ⇒ same `data_hash` ⇒ the stored PDF is returned
    verbatim, so an LLM-backed report is never regenerated (and never
    differs) for unchanged data. A data change yields a new hash → a new
    snapshot is generated once. See `dashboards/pdf/report_cache.py`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(
        "core.Player", on_delete=models.CASCADE, related_name="report_snapshots",
    )
    # Which report this is — lets the same machinery serve triage / department
    # / future report kinds without colliding hashes.
    kind = models.CharField(max_length=40, default="triage", db_index=True)
    # SHA-256 hex of the stable input data + model + render version.
    data_hash = models.CharField(max_length=64, db_index=True)
    # LLM model that produced the narrative (part of the hash basis too, so
    # switching models regenerates rather than serving a stale narrative).
    model = models.CharField(max_length=64, blank=True)
    # The LLM narrative, kept for audit / reuse / debugging. Null when the
    # narrative was unavailable (tables-only fallback). Format-independent —
    # shared by every rendered format of the same signature.
    narrative = models.JSONField(null=True, blank=True)
    # Rendered report files. The narrative (the expensive, non-deterministic
    # part) is cached once per signature; either format is rendered from it
    # on demand. `pdf` is legacy (reports now export as Word); `docx` is the
    # current format. Both optional so a row can hold one, the other, or both.
    # max_length well above the default 100: the upload path embeds the kind,
    # a player UUID, and a 64-char signature filename (~120+ chars), which the
    # default would silently truncate / fail to store.
    pdf = models.FileField(upload_to=_report_pdf_path, blank=True, max_length=255)
    docx = models.FileField(upload_to=_report_pdf_path, blank=True, max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["player", "kind", "data_hash"],
                name="uniq_report_snapshot_player_kind_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["player", "kind", "data_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} report · {self.player_id} · {self.data_hash[:12]}"


def _team_report_path(instance: "TeamReportSnapshot", filename: str) -> str:
    return f"reports/team/{instance.department_id}/{instance.category_id}/{filename}"


class TeamReportSnapshot(models.Model):
    """Content-addressed cache of a generated team report — the team-level
    analogue of `PlayerReportSnapshot`. Keyed on (department, category) plus
    a hash of the resolved widget data + filters + LLM model + agent config,
    so the squad-level narrative (the expensive, non-deterministic part) is
    generated once per data state and reused. See `report_cache.py`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(
        "core.Department", on_delete=models.CASCADE, related_name="team_report_snapshots",
    )
    category = models.ForeignKey(
        "core.Category", on_delete=models.CASCADE, related_name="team_report_snapshots",
    )
    data_hash = models.CharField(max_length=64, db_index=True)
    model = models.CharField(max_length=64, blank=True)
    narrative = models.JSONField(null=True, blank=True)
    # Path embeds two UUIDs + a 64-char signature filename (~150 chars) — well
    # over the default FileField max_length of 100.
    docx = models.FileField(upload_to=_team_report_path, blank=True, max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["department", "category", "data_hash"],
                name="uniq_team_report_snapshot",
            ),
        ]
        indexes = [
            models.Index(fields=["department", "category", "data_hash"]),
        ]

    def __str__(self) -> str:
        return f"team report · {self.department_id}/{self.category_id} · {self.data_hash[:12]}"


class PlayerReadiness(models.Model):
    """Cached readiness assessment per player. A deterministic base (wellness
    + ACWR + status + molestias + trend) is refined by an agent (LLM) reading
    the player's cross-area data; the result is cached by a `signature` of the
    inputs so it's only recomputed when the player's values change — not on
    every roster load. See `dashboards/readiness.py`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.OneToOneField(
        "core.Player", on_delete=models.CASCADE, related_name="readiness",
    )
    score = models.IntegerField(null=True, blank=True)          # displayed value
    deterministic = models.IntegerField(null=True, blank=True)  # base/fallback
    source = models.CharField(max_length=16, default="deterministic")  # agent|deterministic
    rationale = models.TextField(blank=True)
    flags = models.JSONField(default=list, blank=True)
    factors = models.JSONField(default=dict, blank=True)        # input breakdown
    signature = models.CharField(max_length=64, db_index=True, blank=True)
    model = models.CharField(max_length=64, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"readiness {self.score} · {self.player_id} ({self.source})"


class BriefingSnapshot(models.Model):
    """Content-addressed cache of the Centro de mando AI Briefing — the
    ranked recommendation cards generated by the department agents from the
    squad's live data. Keyed on (category, data_hash) where the hash covers
    the team snapshot + agents' config, so the (multi-call) generation runs
    once per data/agent state and the dashboard load stays fast."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        "core.Category", on_delete=models.CASCADE, related_name="briefing_snapshots",
    )
    data_hash = models.CharField(max_length=64, db_index=True)
    model = models.CharField(max_length=64, blank=True)
    items = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "data_hash"], name="uniq_briefing_snapshot",
            ),
        ]
        indexes = [models.Index(fields=["category", "data_hash"])]

    def __str__(self) -> str:
        return f"briefing · {self.category_id} · {self.data_hash[:12]}"


class InsightAgent(models.Model):
    """Editable, stage-specialized 'insight agent': a role/system prompt plus
    a knowledge base the staff can modify, used to generate the LLM narrative
    for a report stage (triage, médico, físico, …).

    This is configuration, not code — edit the prompt and knowledge in the
    admin to change how insights read, no deploy needed. The machine-readable
    output contract (the JSON shape the renderer parses) is owned by the
    renderer, NOT this prompt, so edits here can't break parsing.
    `config_fingerprint()` feeds the report signature, so editing the prompt
    or knowledge regenerates saved reports instead of serving a stale one.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(
        max_length=60, unique=True,
        help_text="Stable selector matching the report stage, e.g. 'triage'.",
    )
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    model = models.CharField(
        max_length=64, blank=True,
        help_text="Override the LLM model id; blank = settings.ANTHROPIC_MODEL.",
    )
    system_prompt = models.TextField(
        help_text=(
            "Role, tone and interpretation rules. Do NOT put the JSON output "
            "contract here — the renderer owns it."
        ),
    )
    knowledge = models.TextField(
        blank=True,
        help_text=(
            "Editable knowledge base (markdown): club methodology, reference "
            "norms, terminology. Used as interpretation context — must NOT "
            "introduce facts about a specific player."
        ),
    )
    is_active = models.BooleanField(default=True)
    # Human-facing audit counter; auto-bumped when output-affecting fields change.
    revision = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def config_fingerprint(self) -> str:
        """Short hash of the output-affecting config. Folded into the report
        signature so any prompt/knowledge/model edit invalidates saved PDFs."""
        basis = f"{self.model}\n{self.system_prompt}\n{self.knowledge}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    def save(self, *args, **kwargs):
        if self.pk:
            prev = (
                type(self).objects
                .filter(pk=self.pk)
                .only("model", "system_prompt", "knowledge")
                .first()
            )
            if prev and (
                prev.model != self.model
                or prev.system_prompt != self.system_prompt
                or prev.knowledge != self.knowledge
            ):
                self.revision = (self.revision or 0) + 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.key}) r{self.revision}"


class MetricReference(models.Model):
    """An EXTERNAL reference/benchmark for one exam metric, labeled by source.

    The single source of truth for *external* norms (ISAK, Premier/Champions
    League, scientific literature) — kept separate from the club's own
    internal bands (which live in `ExamTemplate.config_schema.reference_ranges`)
    so the two never duplicate or drift. The reference loader passes both to
    the agent, each tagged with where it came from. Stats (percentile / Z) are
    computed deterministically against these — the LLM never does the math.

    Provide whichever of range / mean+sd / percentiles the source gives.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        "exams.ExamTemplate", on_delete=models.CASCADE,
        related_name="metric_references",
    )
    field_key = models.CharField(max_length=80, db_index=True)
    source = models.CharField(
        max_length=120,
        help_text="Where the norm comes from, e.g. 'ISAK (fútbol prof.)', "
                  "'Premier League in-season', 'Holway 2010'.",
    )
    # Optional scope — leave blank to apply to everyone.
    sex = models.CharField(max_length=1, blank=True, help_text="'M'/'F' or blank (any).")
    position = models.CharField(max_length=80, blank=True, help_text="Position name or blank (any).")
    # Provide whichever the source gives:
    range_min = models.FloatField(null=True, blank=True)
    range_max = models.FloatField(null=True, blank=True)
    mean = models.FloatField(null=True, blank=True)
    sd = models.FloatField(null=True, blank=True)
    percentiles = models.JSONField(
        null=True, blank=True,
        help_text='Optional percentile map, e.g. {"p5": 33.6, "p50": 65.6, "p95": 115.9}.',
    )
    unit = models.CharField(max_length=24, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["template", "field_key", "is_active"])]

    def __str__(self) -> str:
        return f"{self.template_id}·{self.field_key} — {self.source}"


class PlayerMetricState(models.Model):
    """Materialized 'current state' of a player — the latest + derived values
    (weekly chronic load, latest tracked metrics, status) kept in one JSON
    blob for fast reads and easy evolution tracking.

    A **read model**: `ExamResult` remains the source of truth, and this is
    always rebuildable from it (`manage.py rebuild_player_state`). Maintained
    by a `post_save(ExamResult)` trigger that enqueues a Celery recompute, so
    it stays fresh without recomputing aggregations on every report request.
    Player-INTRINSIC values only — squad-relative metrics (percentile vs the
    team) are computed lazily at read time to avoid cross-player cascades.
    """

    # Bump when the recompute logic changes, so a rebuild can target stale rows.
    STATE_VERSION = 1

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.OneToOneField(
        "core.Player", on_delete=models.CASCADE, related_name="metric_state",
    )
    state = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=0)
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"state · {self.player_id} (v{self.version} @ {self.computed_at:%Y-%m-%d %H:%M})"


class PlayerStateSnapshot(models.Model):
    """A point-in-time copy of a player's `PlayerMetricState`, captured on a
    schedule (weekly) so the evolution of derived metrics — especially the
    weekly chronic load — is a cheap query instead of a recompute-from-raw.

    One row per (player, day): the weekly job `update_or_create`s today's
    snapshot, so a re-run is idempotent. Append-only history otherwise.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(
        "core.Player", on_delete=models.CASCADE, related_name="state_snapshots",
    )
    captured_on = models.DateField(db_index=True, help_text="The day this snapshot represents.")
    state = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["captured_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "captured_on"], name="uniq_state_snapshot_player_day",
            ),
        ]
        indexes = [models.Index(fields=["player", "captured_on"])]

    def __str__(self) -> str:
        return f"snapshot · {self.player_id} @ {self.captured_on}"
