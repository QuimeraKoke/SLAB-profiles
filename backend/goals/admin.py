from django.contrib import admin

from .models import Alert, AlertRule, Goal


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "template",
        "field_key",
        "operator",
        "target_value",
        "due_date",
        "status",
        "last_value",
        "evaluated_at",
    )
    list_filter = ("status", "template__department", "due_date")
    search_fields = ("player__first_name", "player__last_name", "field_key", "notes")
    autocomplete_fields = ("player", "template", "created_by")
    readonly_fields = ("evaluated_at", "last_value", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": (
                "player", "template", "field_key",
                "operator", "target_value", "due_date", "notes",
            ),
        }),
        ("Estado", {
            "fields": ("status", "last_value", "evaluated_at"),
        }),
        ("Auditoría", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "severity",
        "status",
        "source_type",
        "message_short",
        "fired_at",
    )
    list_filter = ("status", "severity", "source_type")
    search_fields = ("player__first_name", "player__last_name", "message")
    autocomplete_fields = ("player", "dismissed_by")
    readonly_fields = ("fired_at", "dismissed_at")

    def message_short(self, obj: Alert) -> str:
        return obj.message[:80] + ("…" if len(obj.message) > 80 else "")

    message_short.short_description = "Mensaje"


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = (
        "template", "field_key", "kind", "category",
        "severity", "is_active", "config_preview",
    )
    list_filter = ("kind", "severity", "is_active", "template")
    search_fields = (
        "template__name", "template__slug", "field_key",
        "message_template",
    )
    autocomplete_fields = ("template", "category", "created_by")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": (
                ("template", "field_key"),
                ("category", "is_active"),
                ("kind", "severity"),
            ),
        }),
        ("Configuración", {
            "fields": ("config", "message_template"),
            "description": (
                "<b>Bound:</b> <code>{\"upper\": 1500, \"lower\": null}</code><br>"
                "<b>Variation:</b> <code>{\"window\": {\"kind\": \"last_n\", \"n\": 4}, "
                "\"threshold_pct\": 5, \"direction\": \"any\"}</code>"
            ),
        }),
        ("Auditoría", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def config_preview(self, obj: AlertRule) -> str:
        import json
        try:
            return json.dumps(obj.config, ensure_ascii=False)[:80]
        except (TypeError, ValueError):
            return str(obj.config)[:80]

    config_preview.short_description = "config"
