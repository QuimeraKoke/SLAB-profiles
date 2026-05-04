from django.contrib import admin

from .models import Attachment


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "filename", "source_type", "field_key", "mime_type",
        "size_bytes", "uploaded_by", "uploaded_at",
    )
    list_filter = ("source_type", "mime_type")
    search_fields = ("filename", "label", "field_key")
    readonly_fields = ("size_bytes", "mime_type", "uploaded_at")
