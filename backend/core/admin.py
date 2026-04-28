from django.contrib import admin

from .models import Category, Club, Department, Player, Position, StaffMembership


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
    list_display = ("first_name", "last_name", "category", "position", "nationality", "is_active")
    list_filter = ("category", "position", "is_active")
    search_fields = ("first_name", "last_name", "nationality")
    autocomplete_fields = ("position",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limit the position dropdown to the player's own club."""
        if db_field.name == "position":
            object_id = request.resolver_match.kwargs.get("object_id")
            if object_id:
                player = Player.objects.filter(pk=object_id).select_related("category__club").first()
                if player and player.category_id:
                    kwargs["queryset"] = Position.objects.filter(club=player.category.club)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
