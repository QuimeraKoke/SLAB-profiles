"""Generic file attachments.

`Attachment.source_type` + `source_id` is a polymorphic pointer back to
whatever the file is attached to (a `Contract`, an `ExamResult` field, etc.).
The same model serves contracts, exam results, and any future "we want files
here" surface — mirrors the (source_type, source_id) pattern used by Alert.

Files live in S3 (or any S3-compatible endpoint, e.g. MinIO for local dev)
via Django's storage backend. Files are NEVER served directly: the API
download endpoint scope-checks the source row, then returns a short-lived
pre-signed URL (Django redirects to it).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AttachmentSource(models.TextChoices):
    CONTRACT = "contract", "Contrato"
    EXAM_FIELD = "exam_field", "Campo de examen"
    EXAM_RESULT = "exam_result", "Resultado de examen (general)"
    EVENT = "event", "Evento"


# Allowlist for upload validation. The set is intentionally conservative —
# medical/sports records are documents and images, not arbitrary files.
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
}

MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB


def attachment_upload_path(instance: "Attachment", filename: str) -> str:
    """Storage path for the file under the configured backend.

    Layout: attachments/<source_type>/<YYYY-MM>/<attachment_id>__<sanitized_filename>
    Including the UUID prevents accidental collisions across uploads of the
    same filename, and the YYYY-MM partition keeps the bucket browseable.
    """
    now = datetime.utcnow()
    safe_name = filename.replace("/", "_").replace("\\", "_")[:120]
    return f"attachments/{instance.source_type}/{now:%Y-%m}/{instance.id}__{safe_name}"


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Polymorphic pointer back to the owning row.
    source_type = models.CharField(max_length=20, choices=AttachmentSource.choices)
    source_id = models.UUIDField(
        help_text="UUID of the source row (Contract.id, ExamResult.id, …)."
    )
    # When source_type='exam_field', this pins the attachment to a specific
    # field of an exam result (e.g. 'foto_pliegues'). For other source types
    # it stays empty.
    field_key = models.CharField(max_length=80, blank=True)

    file = models.FileField(upload_to=attachment_upload_path, max_length=255)
    filename = models.CharField(
        max_length=200,
        help_text="Original filename as uploaded — preserved for display.",
    )
    mime_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    label = models.CharField(max_length=200, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_attachments",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["source_type", "source_id", "field_key"]),
        ]

    def clean(self) -> None:
        super().clean()
        if self.source_type == AttachmentSource.EXAM_FIELD and not self.field_key:
            raise ValidationError(
                {"field_key": "field_key is required when source_type='exam_field'."}
            )
        if (
            self.source_type != AttachmentSource.EXAM_FIELD
            and self.field_key
        ):
            raise ValidationError(
                {"field_key": "field_key only applies to source_type='exam_field'."}
            )

    def __str__(self) -> str:
        return f"{self.source_type}:{self.filename}"
