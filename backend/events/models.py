"""Calendar events scheduled for one or more players.

An Event is owned by a Department (whose calendar it lives on) and points
at a set of Player participants. The `scope` field captures how the
participant list was built so the UI can render "team speech for First Team"
differently from "1-on-1 medical checkup for Player X" even when the
participants M2M happens to contain the same number of rows.

Participants are eagerly expanded at create time — a player who joins the
category next week is NOT auto-invited to last week's event. Past events
keep an accurate roster snapshot.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from core.models import Category, Club, Department, Player


class Event(models.Model):
    TYPE_MATCH = "match"
    TYPE_TRAINING = "training"
    TYPE_MEDICAL_CHECKUP = "medical_checkup"
    TYPE_PHYSICAL_TEST = "physical_test"
    TYPE_TEAM_SPEECH = "team_speech"
    TYPE_NUTRITION = "nutrition"
    TYPE_OTHER = "other"
    EVENT_TYPE_CHOICES = [
        (TYPE_MATCH, "Partido"),
        (TYPE_TRAINING, "Entrenamiento"),
        (TYPE_MEDICAL_CHECKUP, "Chequeo médico"),
        (TYPE_PHYSICAL_TEST, "Test físico"),
        (TYPE_TEAM_SPEECH, "Charla / reunión"),
        (TYPE_NUTRITION, "Nutricional"),
        (TYPE_OTHER, "Otro"),
    ]

    SCOPE_INDIVIDUAL = "individual"
    SCOPE_CATEGORY = "category"
    SCOPE_CUSTOM = "custom"
    SCOPE_CHOICES = [
        (SCOPE_INDIVIDUAL, "Individual"),
        (SCOPE_CATEGORY, "Categoría completa"),
        (SCOPE_CUSTOM, "Personalizado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="events")
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="events"
    )
    event_type = models.CharField(max_length=32, choices=EVENT_TYPE_CHOICES)
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)

    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_INDIVIDUAL)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        help_text="Set when the event was created for an entire category. "
                  "Informational — participants are still listed explicitly.",
    )
    participants = models.ManyToManyField(
        Player, related_name="events", blank=True,
    )
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text="Reserved for type-specific fields (e.g. opponent for matches).",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["club", "starts_at"]),
            models.Index(fields=["department", "starts_at"]),
        ]
        ordering = ("-starts_at",)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.department_id and self.club_id and self.department.club_id != self.club_id:
            raise ValidationError({"department": "Department must belong to the event's club."})
        if self.category_id and self.club_id and self.category.club_id != self.club_id:
            raise ValidationError({"category": "Category must belong to the event's club."})
        if self.ends_at and self.starts_at and self.ends_at < self.starts_at:
            raise ValidationError({"ends_at": "ends_at must be on or after starts_at."})

    def __str__(self) -> str:
        return f"{self.title} ({self.starts_at:%Y-%m-%d %H:%M})"
