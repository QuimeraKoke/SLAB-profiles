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
