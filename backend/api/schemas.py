"""Pydantic schemas for request/response validation (via Django Ninja)."""
from datetime import date, datetime
from typing import Any
from uuid import UUID

from ninja import Schema


class LoginIn(Schema):
    email: str
    password: str


class UserOut(Schema):
    id: int
    email: str
    username: str
    first_name: str = ""
    last_name: str = ""
    is_staff: bool
    is_superuser: bool
    # All Django permission codenames the user effectively has (group +
    # direct user perms; superusers receive a sentinel `["*"]`). The
    # frontend uses this to hide buttons / sections / pages without
    # round-tripping for each check.
    permissions: list[str] = []


class MembershipOut(Schema):
    """The current user's club + scoped categories/departments. None for platform admins."""

    club: "ClubOut"
    all_categories: bool
    categories: list["CategoryOut"]
    all_departments: bool
    departments: list["DepartmentOut"]


class MeOut(Schema):
    user: UserOut
    membership: MembershipOut | None = None


class LoginOut(Schema):
    access_token: str
    expires_at: datetime
    user: UserOut
    membership: MembershipOut | None = None


class ClubOut(Schema):
    id: UUID
    name: str


class DepartmentOut(Schema):
    id: UUID
    name: str
    slug: str
    club_id: UUID


class CategoryOut(Schema):
    id: UUID
    name: str
    club_id: UUID
    departments: list[DepartmentOut] = []


class PositionOut(Schema):
    id: UUID
    name: str
    abbreviation: str
    role: str = ""
    sort_order: int = 0
    club_id: UUID


class PlayerOut(Schema):
    """Lightweight player payload for list views."""

    id: UUID
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    sex: str = ""
    nationality: str = ""
    is_active: bool
    status: str = "available"
    category_id: UUID
    position: PositionOut | None = None
    current_weight_kg: float | None = None
    current_height_cm: float | None = None


class PlayerIn(Schema):
    """Create payload for `POST /api/players`. `category_id` is required."""

    first_name: str
    last_name: str
    date_of_birth: date | None = None
    sex: str = ""
    nationality: str = ""
    is_active: bool = True
    category_id: UUID
    position_id: UUID | None = None
    current_weight_kg: float | None = None
    current_height_cm: float | None = None


class PlayerPatchIn(Schema):
    """Partial update for `PATCH /api/players/{id}`. All fields optional —
    only the provided ones are written. `status` is **not** writable (it's
    auto-derived from open episodes via signals)."""

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    nationality: str | None = None
    is_active: bool | None = None
    category_id: UUID | None = None
    position_id: UUID | None = None
    current_weight_kg: float | None = None
    current_height_cm: float | None = None


class ContractOut(Schema):
    """Full contract payload — salary fields are nullable so non-staff users can
    receive a redacted version (see `_serialize_contract`)."""

    id: UUID
    player_id: UUID
    contract_type: str
    start_date: date
    end_date: date
    signing_date: date | None = None
    ownership_percentage: float
    total_gross_amount: float | None = None
    salary_currency: str = "CLP"
    fixed_bonus: str = ""
    variable_bonus: str = ""
    salary_increase: str = ""
    purchase_option: str = ""
    release_clause: str = ""
    renewal_option: str = ""
    agent_name: str = ""
    notes: str = ""
    season_label: str = ""
    salary_visible: bool = True


class ContractIn(Schema):
    player_id: UUID
    contract_type: str = "permanent"
    start_date: date
    end_date: date
    signing_date: date | None = None
    ownership_percentage: float = 1.0
    total_gross_amount: float | None = None
    salary_currency: str = "CLP"
    fixed_bonus: str = ""
    variable_bonus: str = ""
    salary_increase: str = ""
    purchase_option: str = ""
    release_clause: str = ""
    renewal_option: str = ""
    agent_name: str = ""
    notes: str = ""


class ContractPatchIn(Schema):
    contract_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    signing_date: date | None = None
    ownership_percentage: float | None = None
    total_gross_amount: float | None = None
    salary_currency: str | None = None
    fixed_bonus: str | None = None
    variable_bonus: str | None = None
    salary_increase: str | None = None
    purchase_option: str | None = None
    release_clause: str | None = None
    renewal_option: str | None = None
    agent_name: str | None = None
    notes: str | None = None


class PlayerDetailOut(Schema):
    """Profile-page payload, with category, club, departments, and position embedded."""

    id: UUID
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    sex: str = ""
    nationality: str = ""
    is_active: bool
    status: str = "available"
    club: ClubOut
    category: CategoryOut
    position: PositionOut | None = None
    current_contract: ContractOut | None = None
    current_weight_kg: float | None = None
    current_height_cm: float | None = None
    age: int | None = None
    open_episode_count: int = 0


class TemplateOut(Schema):
    id: UUID
    name: str
    slug: str = ""
    department: DepartmentOut
    version: int
    config_schema: dict[str, Any]
    input_config: dict[str, Any] = {}
    link_to_match: bool = False
    is_episodic: bool = False
    episode_config: dict[str, Any] = {}
    show_injuries: bool = False


class ResultIn(Schema):
    player_id: UUID
    template_id: UUID
    recorded_at: datetime
    raw_data: dict[str, Any]
    event_id: UUID | None = None
    # For episodic templates: pass an existing episode UUID to progress it,
    # or None to open a new one. Ignored for non-episodic templates.
    episode_id: UUID | None = None


class ResultEventBriefOut(Schema):
    """Minimal event info embedded in result responses — no participants list."""

    id: UUID
    event_type: str
    title: str
    starts_at: datetime
    metadata: dict[str, Any] = {}


class ResultOut(Schema):
    id: UUID
    player_id: UUID
    template_id: UUID
    recorded_at: datetime
    result_data: dict[str, Any]
    inputs_snapshot: dict[str, Any] = {}
    event: ResultEventBriefOut | None = None


class ResultPatchIn(Schema):
    """Partial update for an existing ExamResult.

    Only `raw_data` and `recorded_at` are mutable. Episode / event / template
    relationships are immutable — to "move" a result to a different episode,
    delete it and create a new one.
    """

    raw_data: dict[str, Any] | None = None
    recorded_at: datetime | None = None


class TeamResultRowIn(Schema):
    player_id: UUID
    result_data: dict[str, Any]


class TeamResultsIn(Schema):
    """Roster-style submission: shared_data merged into each non-empty row.

    Rows where every row_field is null/missing are skipped server-side so
    the doctor can leave players blank for ones they didn't sample.
    """

    template_id: UUID
    category_id: UUID
    recorded_at: datetime
    # When set, every created ExamResult is linked to this event (and
    # `recorded_at` is overridden server-side from the event's `starts_at`,
    # matching the per-player registrar behavior).
    event_id: UUID | None = None
    shared_data: dict[str, Any] = {}
    rows: list[TeamResultRowIn]


class TeamResultsOut(Schema):
    created: int
    skipped: int
    results: list[ResultOut]


# ---------- Goals & Alerts ----------

class GoalIn(Schema):
    player_id: UUID
    template_id: UUID
    field_key: str
    operator: str
    target_value: float
    due_date: date
    notes: str = ""
    # Days before due_date to start firing pre-deadline warning alerts.
    # null/0 disables warnings for this goal.
    warn_days_before: int | None = 7


class GoalPatchIn(Schema):
    """Partial update — only the fields a doctor can change post-creation."""

    operator: str | None = None
    target_value: float | None = None
    due_date: date | None = None
    notes: str | None = None
    status: str | None = None  # only "cancelled" is allowed via API
    warn_days_before: int | None = None


class GoalProgressOut(Schema):
    """Live computed progress against a goal — see list_player_goals."""

    # True when the latest reading already satisfies the operator.
    # Null when there's no reading yet (current_value is None).
    achieved: bool | None = None
    # Signed delta: current - target. Negative = below target.
    distance: float | None = None
    # Same delta as a % of target. Useful for progress bars; null when
    # target is 0 (division undefined).
    distance_pct: float | None = None


class GoalOut(Schema):
    id: UUID
    player_id: UUID
    template_id: UUID
    template_name: str
    field_key: str
    field_label: str
    field_unit: str
    operator: str
    target_value: float
    due_date: date
    notes: str = ""
    status: str
    last_value: float | None = None
    evaluated_at: datetime | None = None
    warn_days_before: int | None = None
    created_at: datetime
    # Live "current vs target" — re-computed on every list, distinct from
    # last_value which the evaluator stores at scheduled run time.
    current_value: float | None = None
    current_recorded_at: datetime | None = None
    progress: GoalProgressOut = GoalProgressOut()


class AlertOut(Schema):
    id: UUID
    player_id: UUID
    source_type: str
    source_id: UUID
    severity: str
    status: str
    message: str
    fired_at: datetime
    last_fired_at: datetime | None = None
    trigger_count: int = 1
    dismissed_at: datetime | None = None


class AlertWithPlayerOut(AlertOut):
    """Alert payload enriched with player + template summary — used by the
    global navbar dropdown so the UI doesn't have to re-fetch each player."""

    player_first_name: str = ""
    player_last_name: str = ""
    player_category_name: str = ""


class AlertPatchIn(Schema):
    status: str  # "dismissed" | "resolved"


# ---------- Episodes ----------

class EpisodeOut(Schema):
    id: UUID
    player_id: UUID
    template_id: UUID
    template_slug: str = ""
    template_name: str = ""
    status: str  # "open" | "closed"
    stage: str = ""
    title: str = ""
    started_at: datetime
    ended_at: datetime | None = None
    metadata: dict[str, Any] = {}
    result_count: int = 0
    latest_result_data: dict[str, Any] = {}


class EpisodePatchIn(Schema):
    """Manual episode patch — for now, only status closure is exposed.

    Most lifecycle changes (stage, title, ended_at) are auto-derived from
    linked results; this endpoint exists so admins can force-close an
    abandoned episode without entering a final result.
    """

    status: str | None = None  # "closed"


# ---------- Attachments ----------

class AttachmentOut(Schema):
    id: UUID
    source_type: str
    source_id: UUID
    field_key: str = ""
    filename: str
    mime_type: str = ""
    size_bytes: int = 0
    label: str = ""
    uploaded_at: datetime


# ---------- Configurable dashboards ----------

class WidgetPayloadOut(Schema):
    """A single widget on a player profile dashboard.

    `data` is the resolved chart-ready payload — its shape depends on
    `chart_type` and is documented per resolver in
    `backend/dashboards/aggregation.py`. The frontend dispatches by
    `chart_type` and reads `data` accordingly.
    """

    id: UUID
    chart_type: str
    title: str
    description: str = ""
    column_span: int = 12
    chart_height: int | None = None
    sort_order: int = 0
    display_config: dict[str, Any] = {}
    data: dict[str, Any]


class LayoutSectionOut(Schema):
    id: UUID
    title: str = ""
    is_collapsible: bool = True
    default_collapsed: bool = False
    sort_order: int = 0
    widgets: list[WidgetPayloadOut]


class DepartmentLayoutOut(Schema):
    id: UUID
    department: DepartmentOut
    category_id: UUID
    name: str
    sections: list[LayoutSectionOut]


class LayoutResponseOut(Schema):
    """Wrapper so the frontend can read `data.layout` and treat None as 'no layout'."""

    layout: DepartmentLayoutOut | None = None


# ---------- Team reports (parallel to per-player dashboards) ----------

class TeamWidgetPayloadOut(Schema):
    """A single team-scoped widget on a report layout.

    `data` is the resolved chart-ready payload — its shape depends on
    `chart_type` and is documented per resolver in
    `backend/dashboards/team_aggregation.py`. The frontend dispatches by
    `chart_type` and reads `data` accordingly.
    """

    id: UUID
    chart_type: str
    title: str
    description: str = ""
    column_span: int = 12
    chart_height: int | None = None
    sort_order: int = 0
    data: dict[str, Any]


class TeamReportSectionOut(Schema):
    id: UUID
    title: str = ""
    is_collapsible: bool = True
    default_collapsed: bool = False
    sort_order: int = 0
    widgets: list[TeamWidgetPayloadOut]


class TeamReportLayoutOut(Schema):
    id: UUID
    department: DepartmentOut
    category: CategoryOut
    name: str
    sections: list[TeamReportSectionOut] = []


class TeamReportResponseOut(Schema):
    """Wrapper so the frontend treats `layout=None` as 'no report configured'."""

    layout: TeamReportLayoutOut | None = None


# ---------- Events ----------

class EventParticipantOut(Schema):
    """Lightweight player snapshot for event participant lists."""

    id: UUID
    first_name: str
    last_name: str


class EventOut(Schema):
    id: UUID
    club: ClubOut
    department: DepartmentOut
    event_type: str
    title: str
    description: str = ""
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = ""
    scope: str
    category: CategoryOut | None = None
    participants: list[EventParticipantOut]
    metadata: dict[str, Any] = {}
    result_count: int = 0
    created_at: datetime
    updated_at: datetime


class EventIn(Schema):
    """Create or update payload. `club` is derived from department server-side."""

    department_id: UUID
    event_type: str
    title: str
    description: str = ""
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = ""
    scope: str = "individual"   # individual | category | custom
    category_id: UUID | None = None
    participant_ids: list[UUID] = []
    metadata: dict[str, Any] = {}
