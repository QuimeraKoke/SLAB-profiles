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
    InsightAgent,
    LayoutSection,
    MetricReference,
    PlayerMetricState,
    PlayerReportSnapshot,
    PlayerStateSnapshot,
    TeamReportLayout,
    TeamReportSnapshot,
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
        "date_shift_days",
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


# ─── Insight agents (editable report prompt + knowledge base) ──────────


@admin.register(InsightAgent)
class InsightAgentAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "model_label", "revision", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("key", "name", "description")
    readonly_fields = ("revision", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("key", "name", "description", "is_active")}),
        ("Modelo", {"fields": ("model",), "description": "Vacío = modelo por defecto (settings.ANTHROPIC_MODEL)."}),
        ("Prompt y conocimiento", {
            "fields": ("system_prompt", "knowledge"),
            "description": (
                "El prompt define rol/tono/reglas. El conocimiento es la base "
                "editable (metodología, normas de referencia, terminología). "
                "El contrato de salida JSON lo controla el renderizador — no se "
                "edita aquí. Editar estos campos regenera los reportes guardados."
            ),
        }),
        ("Auditoría", {"fields": ("revision", "created_at", "updated_at")}),
    )

    @admin.display(description="Modelo")
    def model_label(self, obj: InsightAgent) -> str:
        return obj.model or "(por defecto)"


@admin.register(PlayerReportSnapshot)
class PlayerReportSnapshotAdmin(admin.ModelAdmin):
    """Read-only inspection of the content-addressed report cache."""

    list_display = ("player", "kind", "short_hash", "model", "created_at")
    list_filter = ("kind", "model")
    search_fields = ("player__first_name", "player__last_name", "data_hash")
    readonly_fields = (
        "player", "kind", "data_hash", "model", "narrative", "docx", "pdf", "created_at",
    )

    def has_add_permission(self, request) -> bool:  # cache entries are machine-written
        return False

    @admin.display(description="Hash")
    def short_hash(self, obj: PlayerReportSnapshot) -> str:
        return obj.data_hash[:12]


@admin.register(TeamReportSnapshot)
class TeamReportSnapshotAdmin(admin.ModelAdmin):
    """Read-only inspection of the content-addressed team-report cache."""

    list_display = ("department", "category", "short_hash", "model", "created_at")
    list_filter = ("model", "department", "category")
    search_fields = ("department__name", "category__name", "data_hash")
    readonly_fields = (
        "department", "category", "data_hash", "model", "narrative", "docx", "created_at",
    )

    def has_add_permission(self, request) -> bool:  # cache entries are machine-written
        return False

    @admin.display(description="Hash")
    def short_hash(self, obj: TeamReportSnapshot) -> str:
        return obj.data_hash[:12]


@admin.register(MetricReference)
class MetricReferenceAdmin(admin.ModelAdmin):
    """External norms (ISAK, league, literature) per exam metric — the
    structured home for reference values that must NOT live in the KB."""

    list_display = ("template", "field_key", "source", "scope", "values_label", "is_active")
    list_filter = ("is_active", "source", "template")
    search_fields = ("field_key", "source", "template__name", "note")
    fieldsets = (
        (None, {"fields": ("template", "field_key", "source", "is_active")}),
        ("Ámbito (opcional)", {"fields": ("sex", "position"), "description": "Dejar en blanco = aplica a todos."}),
        ("Valores (usa los que dé la fuente)", {
            "fields": ("range_min", "range_max", "mean", "sd", "percentiles", "unit"),
        }),
        ("Notas", {"fields": ("note",)}),
    )

    @admin.display(description="Ámbito")
    def scope(self, obj: MetricReference) -> str:
        return " / ".join(x for x in (obj.sex, obj.position) if x) or "(todos)"

    @admin.display(description="Valores")
    def values_label(self, obj: MetricReference) -> str:
        if obj.range_min is not None or obj.range_max is not None:
            return f"{obj.range_min}–{obj.range_max}{(' ' + obj.unit) if obj.unit else ''}"
        if obj.mean is not None:
            return f"μ={obj.mean} σ={obj.sd}"
        if obj.percentiles:
            return "percentiles"
        return "—"


@admin.register(PlayerMetricState)
class PlayerMetricStateAdmin(admin.ModelAdmin):
    """Read-only view of the materialized player state (a read model —
    rebuild from raw with `manage.py rebuild_player_state`)."""

    list_display = ("player", "version", "weekly_load_summary", "computed_at")
    search_fields = ("player__first_name", "player__last_name")
    readonly_fields = ("player", "state", "version", "computed_at")

    def has_add_permission(self, request) -> bool:
        return False

    @admin.display(description="Carga semanal")
    def weekly_load_summary(self, obj: PlayerMetricState) -> str:
        wl = (obj.state or {}).get("weekly_load")
        if not wl:
            return "—"
        flags = [m for m in wl.get("metrics", []) if m.get("status") != "within"]
        return f"{len(wl.get('metrics', []))} métricas, {len(flags)} fuera de rango"


@admin.register(PlayerStateSnapshot)
class PlayerStateSnapshotAdmin(admin.ModelAdmin):
    """Read-only player-state history (weekly snapshots → evolution)."""

    list_display = ("player", "captured_on", "version", "created_at")
    list_filter = ("captured_on",)
    search_fields = ("player__first_name", "player__last_name")
    readonly_fields = ("player", "captured_on", "state", "version", "created_at")
    date_hierarchy = "captured_on"

    def has_add_permission(self, request) -> bool:
        return False
