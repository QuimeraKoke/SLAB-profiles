"""Admin UI for dashboards.

Three nested inline levels:

    DepartmentLayoutAdmin
      └── LayoutSectionInline (TabularInline)
            └── (sections edited inline, then drill-down to LayoutSectionAdmin
                 to add Widgets — Django doesn't support 3-level nested inlines
                 out of the box without a third-party package.)

To keep V1 dependency-free, we register `LayoutSection` and `Widget` as
top-level admin entries with their own inlines (Widgets inside Section,
WidgetDataSources inside Widget). The "Edit" links from each inline drill
down to the next level.
"""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from core.models import Category, Department
from exams.models import ExamTemplate

from .models import (
    DepartmentLayout,
    LayoutSection,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
    Widget,
    WidgetDataSource,
)


class WidgetDataSourceInline(admin.StackedInline):
    model = WidgetDataSource
    extra = 0
    fields = (
        "template",
        "field_keys",
        "aggregation",
        "aggregation_param",
        "label",
        "color",
        "sort_order",
    )
    autocomplete_fields = ("template",)


@admin.register(Widget)
class WidgetAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "chart_type",
        "section",
        "layout_name",
        "column_span",
        "chart_height",
        "sort_order",
    )
    list_filter = (
        "chart_type",
        "section__layout__department",
        "section__layout__category",
    )
    search_fields = ("title", "description")
    autocomplete_fields = ("section",)
    fields = (
        "section",
        "chart_type",
        "title",
        "description",
        "column_span",
        "chart_height",
        "display_config",
        "sort_order",
    )
    inlines = [WidgetDataSourceInline]

    def layout_name(self, obj: Widget) -> str:
        return f"{obj.section.layout.department} – {obj.section.layout.category}"

    layout_name.short_description = "Layout"


class WidgetInline(admin.TabularInline):
    model = Widget
    extra = 0
    fields = (
        "title",
        "chart_type",
        "column_span",
        "chart_height",
        "sort_order",
        "edit_link",
    )
    readonly_fields = ("edit_link",)
    show_change_link = True

    def edit_link(self, obj: Widget) -> str:
        if not obj.pk:
            return "—"
        url = reverse("admin:dashboards_widget_change", args=[obj.pk])
        return format_html(
            '<a href="{}">Edit data sources →</a>', url
        )

    edit_link.short_description = "Data sources"


@admin.register(LayoutSection)
class LayoutSectionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "layout", "sort_order", "is_collapsible", "default_collapsed")
    list_filter = ("layout__department", "layout__category")
    search_fields = ("title",)
    autocomplete_fields = ("layout",)
    inlines = [WidgetInline]


class LayoutSectionInline(admin.TabularInline):
    model = LayoutSection
    extra = 0
    fields = ("title", "sort_order", "is_collapsible", "default_collapsed", "edit_link")
    readonly_fields = ("edit_link",)
    show_change_link = True

    def edit_link(self, obj: LayoutSection) -> str:
        if not obj.pk:
            return "—"
        url = reverse("admin:dashboards_layoutsection_change", args=[obj.pk])
        return format_html('<a href="{}">Edit widgets →</a>', url)

    edit_link.short_description = "Widgets"


@admin.register(DepartmentLayout)
class DepartmentLayoutAdmin(admin.ModelAdmin):
    list_display = (
        "department",
        "category",
        "name",
        "is_active",
        "section_count",
        "widget_count",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "department__club",
        "department",
    )
    search_fields = ("name", "department__name", "category__name")
    autocomplete_fields = ("department", "category")
    inlines = [LayoutSectionInline]

    def section_count(self, obj: DepartmentLayout) -> int:
        return obj.sections.count()

    section_count.short_description = "Sections"

    def widget_count(self, obj: DepartmentLayout) -> int:
        return Widget.objects.filter(section__layout=obj).count()

    widget_count.short_description = "Widgets"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Filter dropdowns to keep admin from cross-wiring clubs."""
        object_id = request.resolver_match.kwargs.get("object_id")
        if not object_id:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        layout = DepartmentLayout.objects.filter(pk=object_id).select_related(
            "department__club", "category__club"
        ).first()
        if layout:
            club = layout.department.club
            if db_field.name == "department":
                kwargs["queryset"] = Department.objects.filter(club=club)
            elif db_field.name == "category":
                kwargs["queryset"] = Category.objects.filter(
                    club=club, departments=layout.department
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# Make Widget / Section searchable so autocomplete on inlines / FKs works.
WidgetAdmin.search_fields = ("title", "description")
LayoutSectionAdmin.search_fields = ("title", "layout__department__name", "layout__category__name")


# =============================================================================
# Team report layouts (parallel admin tree)
# =============================================================================


class TeamReportWidgetDataSourceInline(admin.StackedInline):
    model = TeamReportWidgetDataSource
    extra = 0
    fields = (
        "template",
        "field_keys",
        "aggregation",
        "aggregation_param",
        "label",
        "color",
        "sort_order",
    )
    autocomplete_fields = ("template",)


@admin.register(TeamReportWidget)
class TeamReportWidgetAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "chart_type",
        "section",
        "layout_name",
        "column_span",
        "chart_height",
        "sort_order",
    )
    list_filter = (
        "chart_type",
        "section__layout__department",
        "section__layout__category",
    )
    search_fields = ("title", "description")
    autocomplete_fields = ("section",)
    fields = (
        "section",
        "chart_type",
        "title",
        "description",
        "column_span",
        "chart_height",
        "display_config",
        "sort_order",
    )
    inlines = [TeamReportWidgetDataSourceInline]

    def layout_name(self, obj: TeamReportWidget) -> str:
        return f"{obj.section.layout.department} – {obj.section.layout.category}"

    layout_name.short_description = "Layout"


class TeamReportWidgetInline(admin.TabularInline):
    model = TeamReportWidget
    extra = 0
    fields = (
        "title",
        "chart_type",
        "column_span",
        "chart_height",
        "sort_order",
        "edit_link",
    )
    readonly_fields = ("edit_link",)
    show_change_link = True

    def edit_link(self, obj: TeamReportWidget) -> str:
        if not obj.pk:
            return "—"
        url = reverse("admin:dashboards_teamreportwidget_change", args=[obj.pk])
        return format_html('<a href="{}">Edit data sources →</a>', url)

    edit_link.short_description = "Data sources"


@admin.register(TeamReportSection)
class TeamReportSectionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "layout", "sort_order", "is_collapsible", "default_collapsed")
    list_filter = ("layout__department", "layout__category")
    search_fields = ("title",)
    autocomplete_fields = ("layout",)
    inlines = [TeamReportWidgetInline]


class TeamReportSectionInline(admin.TabularInline):
    model = TeamReportSection
    extra = 0
    fields = ("title", "sort_order", "is_collapsible", "default_collapsed", "edit_link")
    readonly_fields = ("edit_link",)
    show_change_link = True

    def edit_link(self, obj: TeamReportSection) -> str:
        if not obj.pk:
            return "—"
        url = reverse("admin:dashboards_teamreportsection_change", args=[obj.pk])
        return format_html('<a href="{}">Edit widgets →</a>', url)

    edit_link.short_description = "Widgets"


@admin.register(TeamReportLayout)
class TeamReportLayoutAdmin(admin.ModelAdmin):
    list_display = (
        "department",
        "category",
        "name",
        "is_active",
        "section_count",
        "widget_count",
        "updated_at",
    )
    list_filter = ("is_active", "department__club", "department")
    search_fields = ("name", "department__name", "category__name")
    autocomplete_fields = ("department", "category")
    inlines = [TeamReportSectionInline]

    def section_count(self, obj: TeamReportLayout) -> int:
        return obj.sections.count()

    section_count.short_description = "Sections"

    def widget_count(self, obj: TeamReportLayout) -> int:
        return TeamReportWidget.objects.filter(section__layout=obj).count()

    widget_count.short_description = "Widgets"


TeamReportSectionAdmin.search_fields = (
    "title",
    "layout__department__name",
    "layout__category__name",
)
