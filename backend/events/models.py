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
        Player,
        through="EventParticipant",
        related_name="events",
        blank=True,
    )
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text="Reserved for type-specific fields (e.g. opponent for matches).",
    )
    legacy_raw = models.JSONField(
        default=dict, blank=True,
        help_text="Source row(s) from a legacy system this event was migrated from.",
    )
    # For matches: the rival, as a reference entity. `metadata.opponent` /
    # `opponent_team_id` are kept for display/back-compat; this FK is the
    # structured link (set by the sync + the match-create form).
    opponent_team = models.ForeignKey(
        "ExternalTeam", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="matches",
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


class EventParticipant(models.Model):
    """Through model for `Event.participants`.

    Carries per-(event, player) attributes that the plain M2M can't.
    Two layers of fields:

    - GENERIC (apply to ANY event type — training, medical checkup,
      physical test, charla, nutrition meeting, match…):
        * `attendance` — did the player show up?
        * `absence_reason` — only meaningful when missed/excused
        * `post_event_notes` — staff observations AFTER the event

    - MATCH-SPECIFIC (only meaningful when `event.event_type='match'`,
      enforced by `clean()`):
        * `match_role` — citation status: Titular / Suplente ingresa /
          Lesionado / etc.
        * `position_played` — actual position played that match
        * `minutes_played`, `goals`, `yellow_cards`, `red_cards` —
          basic per-match stats

    The migration command from the legacy `citaciones` table populates
    `match_role` + `position_played`, and the merge from
    `estadistica_interna` populates the basic stats."""

    class Attendance(models.TextChoices):
        SCHEDULED = "scheduled", "Programado"
        ATTENDED  = "attended",  "Asistió"
        MISSED    = "missed",    "No asistió"
        EXCUSED   = "excused",   "Justificado"

    class MatchRole(models.TextChoices):
        TITULAR             = "titular",             "Titular"
        SUPLENTE_INGRESA    = "suplente_ingresa",    "Suplente — ingresa"
        SUPLENTE_NO_INGRESA = "suplente_no_ingresa", "Suplente — no ingresa"
        NO_CITADO           = "no_citado",           "No citado"
        LESIONADO           = "lesionado",           "Lesionado"
        SUSPENDIDO          = "suspendido",          "Suspendido"
        SELECCION           = "seleccion",           "Selección"
        PROMOVIDO           = "promovido",           "Promovido"
        CITADO_NO_VESTIR    = "citado_no_vestir",    "Citado sin vestir"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="event_participants",
    )
    player = models.ForeignKey(
        "core.Player", on_delete=models.CASCADE, related_name="event_participations",
    )

    # --- Generic ----------------------------------------------------
    attendance = models.CharField(
        max_length=12, choices=Attendance.choices,
        default=Attendance.SCHEDULED, db_index=True,
    )
    absence_reason = models.CharField(
        max_length=200, blank=True,
        help_text="Why the player didn't attend. Only applies when "
                  "attendance is 'missed' or 'excused'.",
    )
    post_event_notes = models.TextField(
        blank=True,
        help_text="Staff observations after the event — treatment given, "
                  "follow-up needed, etc.",
    )

    # --- Match-specific (nullable for non-match events) -------------
    match_role = models.CharField(
        max_length=24, choices=MatchRole.choices,
        null=True, blank=True, db_index=True,
        help_text="Citation status. Only set when event.event_type='match'.",
    )
    position_played = models.ForeignKey(
        "core.Position",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="event_participations",
        help_text="Position actually played in this match (may differ "
                  "from Player.position for utility players).",
    )
    minutes_played = models.PositiveSmallIntegerField(null=True, blank=True)
    goals = models.PositiveSmallIntegerField(null=True, blank=True)
    yellow_cards = models.PositiveSmallIntegerField(null=True, blank=True)
    red_cards = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- Provenance -------------------------------------------------
    external_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="Legacy citaciones.id_citaciones for migration idempotency.",
    )
    legacy_raw = models.JSONField(
        default=dict, blank=True,
        help_text="Source row(s) from a legacy system this row was migrated from.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("event", "player")]
        indexes = [
            models.Index(fields=["player", "match_role"]),
            models.Index(fields=["event", "attendance"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        is_match = (
            self.event_id is not None
            and self.event.event_type == Event.TYPE_MATCH
        )
        match_fields = [
            "match_role", "position_played", "minutes_played",
            "goals", "yellow_cards", "red_cards",
        ]
        if not is_match:
            offenders = [f for f in match_fields if getattr(self, f) is not None]
            if offenders:
                raise ValidationError({
                    f: "Sólo aplica cuando event.event_type='match'."
                    for f in offenders
                })
        if self.absence_reason and self.attendance not in (
            self.Attendance.MISSED, self.Attendance.EXCUSED,
        ):
            raise ValidationError({
                "absence_reason": "Sólo aplica cuando attendance='missed' o 'excused'.",
            })

    def __str__(self) -> str:
        return f"{self.player} @ {self.event} ({self.attendance})"


class MatchData(models.Model):
    """Imported results + tactical data for a match `Event`, from an external
    provider (API-Football). Kept off `Event.metadata` because lineups +
    events + per-player stats are large JSON blobs. One row per match;
    re-syncing updates it in place.

    NOTE: this is tactical/technical data only (lineups, formations, events,
    team & per-player match statistics). PHYSICAL / GPS data (distance,
    sprints) is NOT available from public APIs — the squad's own physical
    data comes from SLAB's GPS ingest, not from here.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="match_data",
    )
    source = models.CharField(max_length=32, default="api_football")
    fixture_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    # Raw provider `response[]` arrays, stored as-is so new fields cost no
    # migration. Both teams' data is included (it's our match).
    lineups = models.JSONField(default=list, blank=True)
    events = models.JSONField(default=list, blank=True)
    team_statistics = models.JSONField(default=list, blank=True)
    player_statistics = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"MatchData · {self.event_id} (fixture {self.fixture_id})"


class OpponentScouting(models.Model):
    """Imported scouting data about an OPPONENT team (API-Football), saved
    per club + team + season. Deliberately NOT surfaced in the player/team/
    Centro-de-mando views — it's staff-only prep material, exposed only under
    a Scouting context / admin. (Per request: "save it in the app, without
    showing it.")

    Holds the opponent's recent form (results) and most recent lineup/
    formation — enough to brief against an upcoming rival.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    club = models.ForeignKey(
        Club, on_delete=models.CASCADE, related_name="opponent_scouting",
        help_text="The club doing the scouting (data scoping), not the opponent.",
    )
    team_id = models.BigIntegerField(help_text="API-Football team id of the opponent.")
    team_name = models.CharField(max_length=140)
    season = models.IntegerField()
    source = models.CharField(max_length=32, default="api_football")
    # Opponent's recent fixtures (most recent first): date, comp, vs, score, result.
    recent_form = models.JSONField(default=list, blank=True)
    # Opponent's most recent lineup + formation (raw provider shape).
    last_lineup = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["club", "team_id", "season"], name="uniq_opponent_scouting",
            ),
        ]
        indexes = [models.Index(fields=["club", "team_id", "season"])]

    def __str__(self) -> str:
        return f"Scouting · {self.team_name} ({self.season})"


class ExternalTeam(models.Model):
    """A rival/opponent team from an external provider (API-Football).

    Deliberately separate from the internal `Club` model — `Club` is the
    operator's own clubs (with departments, categories, players); rivals are
    reference data identified by the provider's team id. One row per provider
    team (the provider conflates club + senior team for opponents).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32, default="api_football")
    external_id = models.IntegerField(help_text="Provider team id (e.g. API-Football).")
    name = models.CharField(max_length=140)
    country = models.CharField(max_length=80, blank=True)
    code = models.CharField(max_length=12, blank=True)
    logo_url = models.CharField(max_length=300, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"], name="uniq_external_team",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "external_id"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self) -> str:
        return self.name


class Competition(models.Model):
    """An external competition for a season (league/cup) with its date window
    and the teams that play it — reference data for the match-create dropdowns.
    Refreshed by the API-Football sync.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32, default="api_football")
    external_id = models.IntegerField(help_text="Provider league id.")
    season = models.IntegerField()
    name = models.CharField(max_length=140)
    country = models.CharField(max_length=80, blank=True)
    logo_url = models.CharField(max_length=300, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    teams = models.ManyToManyField(ExternalTeam, related_name="competitions", blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id", "season"],
                name="uniq_competition_season",
            ),
        ]
        indexes = [models.Index(fields=["provider", "external_id", "season"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.season})"
