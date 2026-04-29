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
    is_staff: bool
    is_superuser: bool


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
    nationality: str = ""
    is_active: bool
    category_id: UUID
    position: PositionOut | None = None


class PlayerDetailOut(Schema):
    """Profile-page payload, with category, club, departments, and position embedded."""

    id: UUID
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    nationality: str = ""
    is_active: bool
    club: ClubOut
    category: CategoryOut
    position: PositionOut | None = None


class TemplateOut(Schema):
    id: UUID
    name: str
    department: DepartmentOut
    version: int
    config_schema: dict[str, Any]
    input_config: dict[str, Any] = {}


class ResultIn(Schema):
    player_id: UUID
    template_id: UUID
    recorded_at: datetime
    raw_data: dict[str, Any]
    event_id: UUID | None = None


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
    event: ResultEventBriefOut | None = None


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
