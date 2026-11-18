"""Who is acting, for the audit trail.

Set once per request (the JWT auth sets the actor, the middleware the IP and
resets both), read by the change signals. Outside a request — Celery syncs,
management commands — there is no actor and the source says where the write
came from (`acting_as("sync:catapult")`).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    user_id: int | None = None
    email: str = ""
    club_id: str | None = None
    ip: str = ""
    source: str = "sistema"


_actor: ContextVar[Actor] = ContextVar("audit_actor", default=Actor())


def current() -> Actor:
    return _actor.get()


def reset(ip: str = "") -> None:
    _actor.set(Actor(ip=ip))


def set_user(user) -> None:
    """Called by the JWT auth once the token resolves to a user."""
    from core.models import StaffMembership

    club_id = (StaffMembership.objects.filter(user=user).values_list("club_id", flat=True).first())
    a = _actor.get()
    _actor.set(Actor(user_id=user.pk, email=user.email or user.get_username(),
                     club_id=str(club_id) if club_id else None, ip=a.ip, source="web"))


@contextmanager
def acting_as(source: str):
    """Label writes done outside a request (`sync:catapult`, `import:…`)."""
    token = _actor.set(Actor(source=source))
    try:
        yield
    finally:
        _actor.reset(token)
