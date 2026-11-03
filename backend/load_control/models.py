"""Microcycle planning (PLAN_CONTROL_CARGA.md §4.0, §8.2).

A TEAM plans, not a category: in 2026 the U18 is Serie 2008 + Serie 2009
(`core.TeamSeason`), so a microcycle is anchored to (club, season, bracket).

A microcycle is the club's MICRO — its week number — and runs from match to
match: a friendly (`MD AMISTOSO`) is a match day and cuts it, so a microcycle
may hold an intermediate match (U20 M40 had Cobreloa on the 22nd and Unión
Española on the 25th). Every day is a `MicrocycleDay`; the match days among
them decide each day's MD±n label.

The staff plans each training day as a % of the MATCH REFERENCE per metric;
the target is `ref_snapshot[group][metric] × %`. The reference is frozen when
the microcycle opens, so a match played later never rewrites a closed week.
"""
from __future__ import annotations

import uuid

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import Bracket, Club
from load_control import defaults


class LoadControlConfig(models.Model):
    """A club's overrides of `load_control.defaults.DEFAULTS`."""

    club = models.OneToOneField(Club, on_delete=models.CASCADE,
                                related_name="load_control_config")
    settings = models.JSONField(
        default=dict, blank=True,
        help_text="Overrides of the module defaults, by top-level key.")
    bracket_overrides = models.JSONField(
        default=dict, blank=True,
        help_text="Per bracket code ('sub_18'): overrides on top of `settings`.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de control de carga"
        verbose_name_plural = "Configuraciones de control de carga"

    def __str__(self) -> str:
        return f"Control de carga · {self.club}"

    def clean(self):
        unknown = set(self.settings or {}) - set(defaults.DEFAULTS)
        for code, layer in (self.bracket_overrides or {}).items():
            unknown |= set(layer or {}) - set(defaults.DEFAULTS)
        if unknown:
            raise ValidationError(
                {"settings": f"Claves desconocidas: {', '.join(sorted(unknown))}"})

    @staticmethod
    def resolved(club, bracket: Bracket | None = None) -> dict:
        """The effective parameters for a club (and a team's bracket)."""
        row = LoadControlConfig.objects.filter(club=club).first()
        if row is None:
            return defaults.merged()
        override = (row.bracket_overrides or {}).get(bracket.code) if bracket else None
        return defaults.merged(row.settings, override)


class Microcycle(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Borrador"),
        (STATUS_OPEN, "Publicado"),
        (STATUS_CLOSED, "Cerrado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="microcycles")
    season = models.PositiveIntegerField(help_text="Calendar year.")
    bracket = models.ForeignKey(Bracket, on_delete=models.PROTECT,
                                related_name="microcycles",
                                help_text="The team: this bracket in this season.")
    number = models.PositiveSmallIntegerField(help_text="The club's MICRO (week number).")
    kind = models.CharField(max_length=24, blank=True,
                            help_text="Club's TIPO: mixta, amplitud, profundidad…")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    copied_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="copies")
    # {group: {metric: {"value", "n_rows"}, "n_players", "n_matches", "fallback"}}
    # plus "team" and "params" — see `load_control.reference`.
    ref_snapshot = models.JSONField(default=dict, blank=True)
    frozen_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(django_settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-season", "bracket__order", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["club", "season", "bracket", "number"],
                                    name="uniq_microcycle_per_team_number"),
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")),
                                   name="microcycle_end_after_start"),
        ]

    def __str__(self) -> str:
        return f"{self.bracket.name} {self.season} · M{self.number}"

    @property
    def is_frozen(self) -> bool:
        return self.frozen_at is not None


class MicrocycleDay(models.Model):
    KIND_TRAINING = "training"
    KIND_REST = "rest"
    KIND_OFFICIAL = "official"
    KIND_FRIENDLY = "friendly"
    KIND_CHOICES = [
        (KIND_TRAINING, "Entrenamiento"),
        (KIND_REST, "Descanso"),
        (KIND_OFFICIAL, "Partido oficial"),
        (KIND_FRIENDLY, "Partido amistoso"),
    ]
    MATCH_KINDS = frozenset({KIND_OFFICIAL, KIND_FRIENDLY})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    microcycle = models.ForeignKey(Microcycle, on_delete=models.CASCADE,
                                   related_name="days")
    date = models.DateField()
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_TRAINING)
    LABEL_CLUB = "club"
    LABEL_CALC = "calc"
    md_label = models.CharField(max_length=8, blank=True,
                                help_text="The club's GPS CÓDIGO, else derived (labels.py).")
    md_label_source = models.CharField(
        max_length=4, choices=[(LABEL_CLUB, "Planilla del club"), (LABEL_CALC, "Calculada")],
        default=LABEL_CALC)
    event = models.ForeignKey("events.Event", on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="+")
    # {metric key: % of the match reference}. Empty on match and rest days.
    targets_pct = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["microcycle", "date"],
                                    name="uniq_microcycle_day"),
        ]

    def __str__(self) -> str:
        return f"{self.microcycle} · {self.date} {self.md_label}"

    @property
    def is_match(self) -> bool:
        return self.kind in self.MATCH_KINDS

    def clean(self):
        mc = self.microcycle
        if mc and not (mc.start_date <= self.date <= mc.end_date):
            raise ValidationError({"date": "El día está fuera del microciclo."})
        if self.kind != self.KIND_TRAINING and self.targets_pct:
            raise ValidationError(
                {"targets_pct": "Sólo un día de entrenamiento lleva % (el partido vale 100%)."})
        for key, value in (self.targets_pct or {}).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 200:
                raise ValidationError({"targets_pct": f"{key}: % inválido ({value!r})."})
