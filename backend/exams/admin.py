from django.contrib import admin
from django.utils.html import format_html

from .models import ExamResult, ExamTemplate, TemplateField


class TemplateFieldInline(admin.StackedInline):
    """Friendly inline editor for `ExamTemplate.config_schema['fields']`.

    Each field is its own card with structured inputs — no JSON typing. The
    parent admin's `save_related()` regenerates `config_schema` from these
    rows after the formset saves.
    """

    model = TemplateField
    extra = 0
    fields = (
        ("sort_order", "key", "label"),
        ("type", "unit", "group"),
        "options",
        "formula",
        ("chart_type", "required"),
        ("multiline", "rows", "placeholder"),
    )
    classes = ("collapse",)
    ordering = ("sort_order", "key")


@admin.register(ExamTemplate)
class ExamTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "department",
        "club_name",
        "field_count",
        "input_modes_summary",
        "version",
        "is_locked",
        "updated_at",
    )
    list_filter = ("department__club", "department", "is_locked")
    search_fields = ("name", "department__name")
    filter_horizontal = ("applicable_categories",)
    readonly_fields = (
        "version", "is_locked", "created_at", "updated_at",
        "config_schema_preview",
    )
    autocomplete_fields = ("department",)
    inlines = [TemplateFieldInline]

    fieldsets = (
        (None, {
            "fields": ("name", "department", "applicable_categories"),
        }),
        ("Configuración de entrada (input_config)", {
            "fields": ("input_config",),
            "description": (
                "Modos de carga (single, bulk_ingest, etc.), modificadores y "
                "mapeo de columnas para Excel. Estructura documentada en "
                "ExamTemplate.input_config."
            ),
        }),
        ("Esquema de campos (config_schema)", {
            "fields": ("config_schema_preview",),
            "description": (
                "Edita los campos abajo (sección 'Template fields'). "
                "El JSON canónico se regenera automáticamente al guardar."
            ),
        }),
        ("Estado", {
            "fields": ("version", "is_locked", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    # --- Display columns ------------------------------------------------------

    def input_modes_summary(self, obj: ExamTemplate) -> str:
        cfg = obj.input_config or {}
        modes = cfg.get("input_modes") or []
        return ", ".join(modes) or "—"

    input_modes_summary.short_description = "Input modes"

    def club_name(self, obj: ExamTemplate) -> str:
        return obj.department.club.name

    club_name.short_description = "Club"
    club_name.admin_order_field = "department__club__name"

    def field_count(self, obj: ExamTemplate) -> int:
        return obj.template_fields.count()

    field_count.short_description = "# campos"

    def config_schema_preview(self, obj: ExamTemplate) -> str:
        """Read-only preview of the generated JSON, for traceability."""
        if not obj.pk:
            return "(se llena al guardar)"
        import json
        try:
            pretty = json.dumps(obj.config_schema or {}, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            pretty = str(obj.config_schema)
        return format_html(
            "<pre style='max-height: 280px; overflow: auto; "
            "background: #f3f4f6; padding: 12px; border-radius: 4px; "
            "font-size: 0.78rem; line-height: 1.4;'>{}</pre>",
            pretty,
        )

    config_schema_preview.short_description = "Vista previa del JSON generado"

    # --- Field-picker scoping -------------------------------------------------

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Limit applicable_categories to those that opted in to this department."""
        if db_field.name == "applicable_categories":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                template = ExamTemplate.objects.filter(pk=object_id).select_related("department").first()
                if template:
                    from core.models import Category

                    kwargs["queryset"] = Category.objects.filter(
                        club=template.department.club,
                        departments=template.department,
                    )
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    # --- Sync hook ------------------------------------------------------------

    def save_related(self, request, form, formsets, change):
        """After saving the inline TemplateField rows, regenerate config_schema."""
        super().save_related(request, form, formsets, change)
        template = form.instance
        template.regenerate_config_schema_from_fields()


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ("player", "template", "recorded_at", "event")
    list_filter = ("template__department",)
    list_select_related = ("player", "template", "event")
    date_hierarchy = "recorded_at"
    raw_id_fields = ("event",)
