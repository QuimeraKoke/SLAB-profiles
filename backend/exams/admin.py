from django.contrib import admin
from django.utils.html import format_html

from .models import Episode, ExamResult, ExamTemplate, TemplateField


class AlertRuleInline(admin.TabularInline):
    """Inline AlertRule editing on the ExamTemplate change page.

    Lets admins set up bound / variation rules right next to the field
    definitions. The model lives in `goals.models.AlertRule`.
    """

    from goals.models import AlertRule  # local import — avoid app-load cycle

    model = AlertRule
    extra = 0
    fields = ("field_key", "kind", "severity", "category", "config", "is_active")
    autocomplete_fields = ("category",)


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
        "option_labels",
        "option_regions",
        "formula",
        ("chart_type", "required"),
        ("multiline", "rows", "placeholder"),
        "writes_to_player_field",
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
        "link_to_match",
        "version",
        "is_locked",
        "updated_at",
    )
    list_filter = ("department__club", "department", "is_locked", "link_to_match")
    search_fields = ("name", "department__name")
    filter_horizontal = ("applicable_categories",)
    readonly_fields = (
        "version", "is_locked", "created_at", "updated_at",
        "config_schema_preview",
    )
    autocomplete_fields = ("department",)
    inlines = [TemplateFieldInline, AlertRuleInline]

    fieldsets = (
        (None, {
            "fields": ("name", "slug", "department", "applicable_categories"),
        }),
        ("Asociación a partido", {
            "fields": ("link_to_match",),
            "description": (
                "Cuando está activado, el formulario de carga muestra un selector "
                "de partido. La fecha del partido sobreescribe la fecha del "
                "formulario y se guarda la relación con el evento. Aplica a "
                "single, bulk-ingest y team-table."
            ),
        }),
        ("Plantilla episódica", {
            "fields": ("is_episodic", "episode_config"),
            "description": (
                "Cuando está activada, los resultados forman Episodios "
                "encadenados (ej. lesiones, cirugías). episode_config debe "
                "definir <code>stage_field</code>, <code>open_stages</code> "
                "(peor → mejor), <code>closed_stage</code>, y opcionalmente "
                "<code>title_template</code>."
            ),
        }),
        ("Mostrar lesiones en el formulario", {
            "fields": ("show_injuries",),
            "description": (
                "Cuando está activada, el formulario de carga muestra un "
                "panel con las lesiones abiertas del jugador y un botón para "
                "registrar una nueva lesión sin salir del formulario. Útil "
                "para plantillas de notas diarias o seguimiento donde el "
                "doctor necesita contexto sobre lesiones activas."
            ),
        }),
        ("Configuración de entrada (input_config)", {
            "fields": ("input_config",),
            "description": (
                "Modos de carga (single, bulk_ingest, etc.), modificadores y "
                "mapeo de columnas para Excel. Estructura documentada en "
                "ExamTemplate.input_config. (El campo allow_event_link se "
                "sincroniza automáticamente desde el checkbox de arriba.)"
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
    list_display = ("player", "template", "recorded_at", "event", "episode")
    list_filter = ("template__department",)
    list_select_related = ("player", "template", "event", "episode")
    date_hierarchy = "recorded_at"
    raw_id_fields = ("event", "episode")


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = (
        "title", "player", "template", "status", "stage",
        "started_at", "ended_at",
    )
    list_filter = ("status", "template", "stage")
    search_fields = (
        "title", "player__first_name", "player__last_name",
        "template__name", "template__slug",
    )
    autocomplete_fields = ("player", "template", "created_by")
    readonly_fields = (
        "stage", "title", "started_at", "ended_at", "created_at", "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("player", "template", "status")}),
        ("Estado derivado", {
            "fields": ("stage", "title", "started_at", "ended_at"),
            "description": "Campos auto-derivados del último resultado vinculado al episodio.",
        }),
        ("Metadata", {"fields": ("metadata",), "classes": ("collapse",)}),
        ("Auditoría", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
