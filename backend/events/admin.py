from django.contrib import admin

from core.models import Category, Department, Player

from .models import Event, EventParticipant, MatchData, OpponentScouting


class EventParticipantInline(admin.TabularInline):
    """Inline form for managing Event ↔ Player participation. Replaces
    the old `filter_horizontal` picker — needed because `participants`
    now uses a `through=` model that carries per-row attendance + match
    attributes."""

    model = EventParticipant
    extra = 0
    autocomplete_fields = ("player", "position_played")
    fields = (
        "player", "attendance", "absence_reason", "match_role",
        "position_played", "minutes_played", "goals",
        "yellow_cards", "red_cards", "post_event_notes",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title", "event_type", "department", "club", "scope",
        "starts_at", "participant_count",
    )
    list_filter = ("club", "department", "event_type", "scope")
    search_fields = ("title", "description", "location")
    autocomplete_fields = ("department",)
    inlines = (EventParticipantInline,)
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

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id and request.user.is_authenticated:
            obj.created_by = request.user
        # Auto-derive club from department if missing.
        if obj.department_id and not obj.club_id:
            obj.club = obj.department.club
        super().save_model(request, obj, form, change)


@admin.register(EventParticipant)
class EventParticipantAdmin(admin.ModelAdmin):
    """Standalone admin (alongside the Event inline) so participants
    can be browsed by player, status, or match role."""

    list_display = (
        "player", "event", "attendance", "match_role",
        "minutes_played", "goals",
    )
    list_filter = ("attendance", "match_role", "event__event_type")
    search_fields = (
        "player__first_name", "player__last_name", "event__title",
    )
    autocomplete_fields = ("event", "player", "position_played")
    readonly_fields = ("external_id", "legacy_raw", "created_at", "updated_at")


@admin.register(MatchData)
class MatchDataAdmin(admin.ModelAdmin):
    """Read-only view of imported match results + tactical data
    (API-Football). Machine-written by the fixture sync."""

    list_display = ("event", "source", "fixture_id", "synced_at")
    list_filter = ("source",)
    search_fields = ("event__title", "fixture_id")
    readonly_fields = (
        "event", "source", "fixture_id", "lineups", "events",
        "team_statistics", "player_statistics", "synced_at",
    )

    def has_add_permission(self, request) -> bool:  # written by the sync, not by hand
        return False


@admin.register(OpponentScouting)
class OpponentScoutingAdmin(admin.ModelAdmin):
    """Hidden opponent scouting store (API-Football). Staff-only prep — not
    surfaced in the player/team/Centro-de-mando views."""

    list_display = ("team_name", "club", "season", "source", "synced_at")
    list_filter = ("season", "club", "source")
    search_fields = ("team_name", "team_id")
    readonly_fields = (
        "club", "team_id", "team_name", "season", "source",
        "recent_form", "last_lineup", "synced_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
