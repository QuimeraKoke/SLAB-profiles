from django.contrib import admin

from load_control.models import LoadControlConfig, Microcycle, MicrocycleDay


@admin.register(LoadControlConfig)
class LoadControlConfigAdmin(admin.ModelAdmin):
    list_display = ("club", "updated_at")


class MicrocycleDayInline(admin.TabularInline):
    model = MicrocycleDay
    extra = 0
    fields = ("date", "kind", "md_label", "targets_pct", "event")
    readonly_fields = ("md_label",)
    raw_id_fields = ("event",)


@admin.register(Microcycle)
class MicrocycleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "club", "kind", "start_date", "end_date", "status", "frozen_at")
    list_filter = ("club", "season", "bracket", "status")
    readonly_fields = ("ref_snapshot", "frozen_at", "created_at", "updated_at")
    raw_id_fields = ("copied_from",)
    inlines = [MicrocycleDayInline]
