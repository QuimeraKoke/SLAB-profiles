from django.contrib import admin

from core.models import Category, Department, Player

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title", "event_type", "department", "club", "scope",
        "starts_at", "participant_count",
    )
    list_filter = ("club", "department", "event_type", "scope")
    search_fields = ("title", "description", "location")
    autocomplete_fields = ("department",)
    filter_horizontal = ("participants",)
    readonly_fields = ("created_by", "created_at", "updated_at")
    date_hierarchy = "starts_at"

    def participant_count(self, obj: Event) -> int:
        return obj.participants.count()

    participant_count.short_description = "Participantes"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limit category dropdown to the event's club."""
        if db_field.name == "category":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                event = Event.objects.filter(pk=object_id).select_related("club").first()
                if event:
                    kwargs["queryset"] = Category.objects.filter(club=event.club)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Limit participants picker to the event's club."""
        if db_field.name == "participants":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                event = Event.objects.filter(pk=object_id).select_related("club").first()
                if event:
                    kwargs["queryset"] = Player.objects.filter(
                        category__club=event.club, is_active=True,
                    )
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id and request.user.is_authenticated:
            obj.created_by = request.user
        # Auto-derive club from department if missing.
        if obj.department_id and not obj.club_id:
            obj.club = obj.department.club
        super().save_model(request, obj, form, change)
