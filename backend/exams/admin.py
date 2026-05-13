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
        ("chart_type", "direction_of_good", "required"),
        "reference_ranges",
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
        "is_active_version",
        "is_locked",
        "updated_at",
    )
    list_filter = (
        "department__club", "department", "is_active_version",
        "is_locked", "link_to_match",
    )
    search_fields = ("name", "department__name")
    filter_horizontal = ("applicable_categories",)
    readonly_fields = (
        "version", "family_id", "is_active_version",
        "is_locked", "created_at", "updated_at",
        "config_schema_preview",
    )
    autocomplete_fields = ("department",)
    inlines = [TemplateFieldInline, AlertRuleInline]
    actions = ["fork_new_version_action"]

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
        ("Estado / versionado", {
            "fields": (
                "version", "is_active_version", "family_id",
                "is_locked", "created_at", "updated_at",
            ),
            "description": (
                "<code>family_id</code> agrupa todas las versiones de la "
                "misma plantilla. Para crear una versión nueva, selecciona "
                "esta fila en el listado y elige "
                "<b>«Crear nueva versión»</b> en el menú de acciones. "
                "Los resultados de versiones anteriores siguen visibles en "
                "los dashboards — campos eliminados o renombrados en la nueva "
                "versión se ocultarán automáticamente para esas filas."
            ),
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
        """After saving the inline TemplateField rows, regenerate config_schema.

        Also: if this template is a non-v1 (i.e. a forked version), compare
        its field keys against the prior version's and warn about any keys
        that disappeared. Those keys still exist on historical ExamResults
        from older versions but won't be picked up by widgets bound to
        this version's schema — option (a)+(c) from the design pitch.
        """
        from django.contrib import messages

        super().save_related(request, form, formsets, change)
        template = form.instance
        template.regenerate_config_schema_from_fields()

        if template.version > 1:
            removed = _removed_field_keys_vs_previous_version(template)
            if removed:
                self.message_user(
                    request,
                    (
                        f"Atención: los siguientes campos están en versiones "
                        f"anteriores pero no en v{template.version}: "
                        f"{', '.join(sorted(removed))}. "
                        "Los resultados históricos con datos en esos campos "
                        "no aparecerán en dashboards que apunten a esta versión."
                    ),
                    level=messages.WARNING,
                )

    # --- Versioning action ----------------------------------------------------

    @admin.action(description="Crear nueva versión (forkear)")
    def fork_new_version_action(self, request, queryset):
        """Fork the selected template(s) into v+1.

        Designed for single-select use — picking multiple rows still works
        but is unusual. Each fork is independent; if one fails the rest
        continue (Django messages.warning each individually so the admin
        can audit which succeeded).
        """
        from django.contrib import messages

        count_ok = 0
        for template in queryset:
            if not template.is_active_version:
                self.message_user(
                    request,
                    f"'{template.name}' v{template.version} no es la versión "
                    "activa de su familia — forkear desde una versión "
                    "histórica está deshabilitado para evitar cadenas "
                    "ambiguas. Forkeá desde la versión activa.",
                    level=messages.WARNING,
                )
                continue
            try:
                new_version = template.fork_new_version()
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request,
                    f"Falló el fork de '{template.name}': {exc}",
                    level=messages.ERROR,
                )
                continue
            self.message_user(
                request,
                (
                    f"Versión {new_version.version} creada para "
                    f"'{new_version.name}'. ⚠ Si renombrás o eliminás campos "
                    "en esta versión, los resultados de versiones anteriores "
                    "con datos en esos campos quedarán fuera de los "
                    "dashboards que usen esta plantilla."
                ),
                level=messages.SUCCESS,
            )
            count_ok += 1

        if count_ok == 0:
            self.message_user(
                request,
                "Ninguna versión fue creada.",
                level=messages.WARNING,
            )


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


def _removed_field_keys_vs_previous_version(template: ExamTemplate) -> set[str]:
    """Return field keys present in v(N-1) but missing in `template`'s
    current `config_schema`. Used to surface a schema-drift warning when
    the admin saves a forked version. Lazy / silent: returns an empty
    set if the previous version can't be found, never raises."""
    previous = (
        ExamTemplate.objects
        .filter(family_id=template.family_id, version=template.version - 1)
        .first()
    )
    if previous is None:
        return set()

    def _keys(schema: dict) -> set[str]:
        out: set[str] = set()
        for f in (schema or {}).get("fields", []) or []:
            if isinstance(f, dict) and isinstance(f.get("key"), str):
                out.add(f["key"])
        return out

    return _keys(previous.config_schema or {}) - _keys(template.config_schema or {})
