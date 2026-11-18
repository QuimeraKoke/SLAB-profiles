"""Audit trail: who changed what, who saw what, and the backups.

Both logs are append-only: no foreign keys (a deleted player or user must not
erase or rewrite his trail), names copied at write time, and a database
trigger rejects UPDATE and DELETE on them (migration 0002). Nobody — not the
app, not the admin — can edit or remove an entry without dropping that
trigger by hand.
"""
from __future__ import annotations

from django.db import models


class ChangeEvent(models.Model):
    CREATE, UPDATE, DELETE = "create", "update", "delete"
    ACTIONS = [(CREATE, "Creó"), (UPDATE, "Editó"), (DELETE, "Borró")]

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=8, choices=ACTIONS)
    model = models.CharField(max_length=60)          # "exams.ExamResult"
    object_id = models.CharField(max_length=64)
    object_label = models.CharField(max_length=200, blank=True)  # "Check-in físico · 12-11-2026"
    club_id = models.CharField(max_length=64, blank=True, db_index=True)
    player_id = models.CharField(max_length=64, blank=True, db_index=True)
    player_name = models.CharField(max_length=200, blank=True)
    actor_id = models.IntegerField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True)
    source = models.CharField(max_length=60, default="sistema")  # web | sistema | sync:…
    ip = models.CharField(max_length=64, blank=True)
    # update: {"campo": [antes, después]}; create/delete: the full row.
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ("-at", "-id")
        indexes = [models.Index(fields=["club_id", "-at"]), models.Index(fields=["model", "object_id"])]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.actor_email or self.source} {self.action} {self.model}"


class AccessEvent(models.Model):
    """A staff user opened a player's record or downloaded a report."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=20)    # ficha | lesiones | notas | contratos | adjunto | descarga | exportacion | ingreso
    club_id = models.CharField(max_length=64, blank=True, db_index=True)
    player_id = models.CharField(max_length=64, blank=True, db_index=True)
    player_name = models.CharField(max_length=200, blank=True)
    actor_id = models.IntegerField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True)
    ip = models.CharField(max_length=64, blank=True)
    path = models.CharField(max_length=300, blank=True)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ("-at", "-id")
        indexes = [models.Index(fields=["club_id", "-at"]),
                   models.Index(fields=["actor_id", "player_id", "kind", "-at"])]


class BackupRun(models.Model):
    """One run of the daily database backup (`audit.backup`)."""

    OK, FAILED = "ok", "failed"
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default=FAILED)
    key = models.CharField(max_length=300, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    tables = models.IntegerField(null=True, blank=True)   # entries pg_restore --list read back
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-started_at",)
