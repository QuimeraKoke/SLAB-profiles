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

        # Template's department must match the layout's department.
        if self.widget_id:
            layout = self.widget.section.layout
            if self.template.department_id != layout.department_id:
                # cross_exam_line is the only chart type that allows mixing,
                # but its sources must still belong to the same club.
                if self.widget.chart_type != ChartType.CROSS_EXAM_LINE:
                    raise ValidationError(
                        f"Template '{self.template.name}' is in department "
                        f"'{self.template.department}', but this widget lives in "
                        f"department '{layout.department}'. Use a "
                        f"'{ChartType.CROSS_EXAM_LINE.label}' widget if you intend "
                        f"to mix departments."
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
