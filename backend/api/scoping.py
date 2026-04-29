"""Per-user access scoping helpers.

A user with a StaffMembership is filtered to their club, plus their assigned
categories and departments (unless the corresponding 'all' flag is set).
A user without a membership is treated as platform-wide and sees everything —
this is the platform owner / superuser persona.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet

from core.models import StaffMembership

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser


def get_membership(user: "AbstractBaseUser | None") -> StaffMembership | None:
    if user is None or not user.is_authenticated:
        return None
    return (
        StaffMembership.objects.filter(user=user)
        .select_related("club")
        .prefetch_related("categories", "departments")
        .first()
    )


def has_full_access(membership: StaffMembership | None) -> bool:
    """True when the user has no membership (platform admin)."""
    return membership is None


def scope_clubs(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    return qs.filter(pk=membership.club_id)


def scope_categories(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    qs = qs.filter(club=membership.club)
    if not membership.all_categories:
        qs = qs.filter(pk__in=membership.categories.values_list("pk", flat=True))
    return qs


def scope_departments(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    qs = qs.filter(club=membership.club)
    if not membership.all_departments:
        qs = qs.filter(pk__in=membership.departments.values_list("pk", flat=True))
    return qs


def scope_positions(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    return qs.filter(club=membership.club)


def scope_players(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    qs = qs.filter(category__club=membership.club)
    if not membership.all_categories:
        qs = qs.filter(category__in=membership.categories.all())
    return qs


def scope_templates(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    qs = qs.filter(department__club=membership.club)
    if not membership.all_departments:
        qs = qs.filter(department__in=membership.departments.all())
    return qs


def scope_results(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    if has_full_access(membership):
        return qs
    qs = qs.filter(player__category__club=membership.club)
    if not membership.all_categories:
        qs = qs.filter(player__category__in=membership.categories.all())
    if not membership.all_departments:
        qs = qs.filter(template__department__in=membership.departments.all())
    return qs


def scope_events(qs: QuerySet, membership: StaffMembership | None) -> QuerySet:
    """Events visible to a user: same club + accessible department.

    Note: we don't additionally filter by participants' categories — if the
    user can see the department, they can see the event roster. Future
    refinement may restrict participant visibility per category, but for
    now the assumption is "if you have access to the medical department,
    you see all medical events including the player names involved."
    """
    if has_full_access(membership):
        return qs
    qs = qs.filter(club=membership.club)
    if not membership.all_departments:
        qs = qs.filter(department__in=membership.departments.all())
    return qs
