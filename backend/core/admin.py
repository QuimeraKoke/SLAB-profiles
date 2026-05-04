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
    list_display = ("name", "club", "department_summary")
    list_filter = ("club",)
    search_fields = ("name", "club__name")
    filter_horizontal = ("departments",)

    def department_summary(self, obj: Category) -> str:
        return ", ".join(d.name for d in obj.departments.all()) or "—"

    department_summary.short_description = "Departments"

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
