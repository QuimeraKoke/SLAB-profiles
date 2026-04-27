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


class ResultIn(Schema):
    player_id: UUID
    template_id: UUID
    recorded_at: datetime
    raw_data: dict[str, Any]


class ResultOut(Schema):
    id: UUID
    player_id: UUID
    template_id: UUID
    recorded_at: datetime
    result_data: dict[str, Any]
