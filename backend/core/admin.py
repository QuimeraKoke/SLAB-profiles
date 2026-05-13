from django.contrib import admin

from .models import (
    Category,
    Club,
    Contract,
    Department,
    Player,
    PlayerAlias,
    Position,
    StaffMembership,
)


class PlayerAliasInline(admin.TabularInline):
    model = PlayerAlias
    extra = 0
    fields = ("kind", "source", "value")


class ContractInline(admin.StackedInline):
    model = Contract
    extra = 0
    fields = (
        ("contract_type", "ownership_percentage"),
        ("start_date", "end_date", "signing_date"),
        ("total_gross_amount", "salary_currency"),
        "fixed_bonus",
        "variable_bonus",
        "salary_increase",
        ("purchase_option", "release_clause"),
        "renewal_option",
        ("agent_name", "notes"),
    )
    classes = ("collapse",)
    show_change_link = True


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "club", "slug")
    list_filter = ("club",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "club", "department_summary", "external_provider")
    list_filter = ("club",)
    search_fields = ("name", "club__name")
    filter_horizontal = ("departments",)
    fieldsets = (
        (None, {"fields": ("club", "name", "departments")}),
        ("Integración externa", {
            "fields": ("external_config",),
            "description": (
                "Para vincular esta categoría con API-Football, completa el "
                "JSON: <code>{\"provider\": \"api_football\", \"team_id\": "
                "257, \"season\": 2026}</code>. Trae automáticamente todos "
                "los partidos del equipo en esa temporada (liga, copa, "
                "continental, amistosos). Para restringir a competiciones "
                "específicas agrega <code>\"league_ids\": [265, 270]</code>. "
                "Deja vacío (<code>{}</code>) para categorías no cubiertas "
                "por el proveedor (juveniles / cadetes)."
            ),
            "classes": ("collapse",),
        }),
    )

    def department_summary(self, obj: Category) -> str:
        return ", ".join(d.name for d in obj.departments.all()) or "—"

    department_summary.short_description = "Departments"

    def external_provider(self, obj: Category) -> str:
        cfg = obj.external_config or {}
        provider = cfg.get("provider")
        if not provider:
            return "—"
        team_id = cfg.get("team_id")
        return f"{provider} (team {team_id})" if team_id else str(provider)

    external_provider.short_description = "Proveedor externo"

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Limit the departments picker to those of the category's own club."""
        if db_field.name == "departments":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                from .models import Department

                category = Category.objects.filter(pk=object_id).first()
                if category:
                    kwargs["queryset"] = Department.objects.filter(club=category.club)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("abbreviation", "name", "role", "club", "sort_order")
    list_filter = ("club",)
    search_fields = ("name", "abbreviation")
    ordering = ("club", "sort_order", "abbreviation")


@admin.register(StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "club", "all_categories", "all_departments")
    list_filter = ("club", "all_categories", "all_departments")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    filter_horizontal = ("categories", "departments")

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Restrict the categories/departments pickers to the membership's club."""
        if db_field.name in {"categories", "departments"}:
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                membership = StaffMembership.objects.filter(pk=object_id).select_related("club").first()
                if membership:
                    if db_field.name == "categories":
                        kwargs["queryset"] = Category.objects.filter(club=membership.club)
                    else:
                        kwargs["queryset"] = Department.objects.filter(club=membership.club)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # Anyone we give a membership to should be able to sign into Django Admin.
        if obj.user_id and not obj.user.is_staff:
            obj.user.is_staff = True
            obj.user.save(update_fields=["is_staff"])
        super().save_model(request, obj, form, change)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = (
        "first_name", "last_name", "category", "position", "sex",
        "current_weight_kg", "current_height_cm",
        "nationality", "is_active",
    )
    list_filter = ("category", "position", "sex", "is_active")
    search_fields = ("first_name", "last_name", "nationality")
    autocomplete_fields = ("position",)
    inlines = [PlayerAliasInline, ContractInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limit the position dropdown to the player's own club."""
        if db_field.name == "position":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                player = Player.objects.filter(pk=object_id).select_related("category__club").first()
                if player and player.category_id:
                    kwargs["queryset"] = Position.objects.filter(club=player.category.club)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "player", "contract_type", "start_date", "end_date",
        "ownership_percentage", "total_gross_amount", "salary_currency",
    )
    list_filter = ("contract_type", "salary_currency")
    search_fields = (
        "player__first_name", "player__last_name", "agent_name", "notes",
    )
    autocomplete_fields = ("player",)
    fieldsets = (
        (None, {
            "fields": (
                "player", "contract_type",
                ("start_date", "end_date", "signing_date"),
                ("ownership_percentage", "total_gross_amount", "salary_currency"),
            ),
        }),
        ("Bonos y opciones", {
            "fields": (
                "fixed_bonus",
                "variable_bonus",
                "salary_increase",
                "purchase_option",
                "release_clause",
                "renewal_option",
            ),
            "description": (
                "Texto libre. Convención: 'NO' = no aplica; en otro caso, "
                "describir monto y condiciones."
            ),
        }),
        ("Provenance", {
            "fields": ("agent_name", "notes", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")


# --- User admin override: require first/last name + email at create time ----
#
# Django's default User add form only requires `username` + password. In our
# app the login is by email (see api/auth.py) and the sidebar surfaces the
# user's display name via "First Last" → username fallback. Empty name/email
# fields produce a degraded UX, so we gate creation at the admin layer.
#
# The model still has `blank=True` on these — programmatic creation (CLI,
# fixtures, tests, `createsuperuser`) is unaffected.

from django import forms
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class RequiredFieldsUserCreationForm(UserCreationForm):
    """Like UserCreationForm but with first_name, last_name and email required."""

    first_name = forms.CharField(max_length=150, required=True, label="Nombre")
    last_name = forms.CharField(max_length=150, required=True, label="Apellido")
    email = forms.EmailField(required=True, label="Email")

    class Meta(UserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email")


class SLABUserAdmin(UserAdmin):
    add_form = RequiredFieldsUserCreationForm
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username", "first_name", "last_name", "email",
                "password1", "password2",
            ),
        }),
    )
    # Make the existing edit-view list_display surface the name too, so
    # admins can spot users with empty profiles at a glance.
    list_display = (
        "username", "email", "first_name", "last_name",
        "is_staff", "is_active",
    )


# Re-register the auth User with the custom admin. The default is registered
# automatically by django.contrib.auth's AppConfig, so we unregister first.
admin.site.unregister(User)
admin.site.register(User, SLABUserAdmin)
