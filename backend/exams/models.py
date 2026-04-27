import uuid

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from core.models import Category, Department, Player


class ExamTemplate(models.Model):
    """Configuration-driven exam definition.

    config_schema follows the structure described in PROJECT.md, e.g.:
        {"fields": [{"key": "...", "label": "...", "type": "...", "chart_type": "..."}]}
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="exam_templates"
    )
    applicable_categories = models.ManyToManyField(Category, related_name="exam_templates")
    config_schema = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    is_locked = models.BooleanField(
        default=False,
        help_text="Once results exist, the template is locked. New changes spawn a new version.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [GinIndex(fields=["config_schema"])]

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.department})"


class ExamResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="exam_results")
    template = models.ForeignKey(ExamTemplate, on_delete=models.PROTECT, related_name="results")
    recorded_at = models.DateTimeField()
    result_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            GinIndex(fields=["result_data"]),
            models.Index(fields=["player", "recorded_at"]),
        ]
        ordering = ("-recorded_at",)

    def __str__(self) -> str:
        return f"{self.template.name} – {self.player} @ {self.recorded_at:%Y-%m-%d}"
