from django.contrib import admin

from .models import ExamResult, ExamTemplate


@admin.register(ExamTemplate)
class ExamTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "club_name", "version", "is_locked", "updated_at")
    list_filter = ("department__club", "department", "is_locked")
    search_fields = ("name", "department__name")
    filter_horizontal = ("applicable_categories",)
    readonly_fields = ("version", "is_locked", "created_at", "updated_at")
    autocomplete_fields = ("department",)

    def club_name(self, obj: ExamTemplate) -> str:
        return obj.department.club.name

    club_name.short_description = "Club"
    club_name.admin_order_field = "department__club__name"

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


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ("player", "template", "recorded_at")
    list_filter = ("template__department",)
    date_hierarchy = "recorded_at"
