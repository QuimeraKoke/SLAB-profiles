"""Seed the two canonical permission groups + backfill existing users.

Two groups:

- **Editor** — full CRUD on the operational models a doctor/physio/etc.
  works with (ExamResult, Episode, Goal, Event, Player, Attachment,
  AlertRule). Does NOT include contract permissions — those are
  granular and assigned directly to users via the admin UI.

- **Solo Lectura** — only `view_*` on the same models. A user in this
  group sees the data their `StaffMembership` lets them see but
  cannot create, edit or delete anything.

Contract visibility (`view_contract`) is intentionally left OUT of
both groups. Admins grant it per-user from `/admin/auth/user/<id>/`
→ User permissions, on a case-by-case basis.

The two groups are ORTHOGONAL to `StaffMembership` scoping:
- StaffMembership says "what slice of data you see" (club / categories
  / departments).
- Group says "what actions you can take on that slice".

A "Doctor de Sub-20, solo lectura" = StaffMembership(departments=Médico,
categories=Sub-20) + Group("Solo Lectura").

Backfill semantics:
- Idempotent. Running twice is a no-op.
- Every active User WITHOUT any group (and not a superuser) gets
  assigned to Editor — preserves the current "everyone can edit"
  behavior so the demo doesn't break overnight.
- Users that already belong to a group are left alone.
- Superusers are skipped — they bypass perms regardless.

Run:

    docker compose exec backend python manage.py seed_role_groups
"""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand


# (app_label, model_name) tuples for the operational surface that the
# Editor / Solo Lectura groups gate. Adding a new model to the
# read/edit story is one line here.
OPERATIONAL_MODELS: list[tuple[str, str]] = [
    ("exams", "examresult"),
    ("exams", "episode"),
    ("goals", "goal"),
    ("goals", "alert"),
    ("goals", "alertrule"),
    ("events", "event"),
    ("core", "player"),
    ("attachments", "attachment"),
]


def _perms_for(actions: list[str]) -> list[Permission]:
    """Resolve `Permission` objects for each (action, app_label, model)
    tuple. Missing perms (e.g. before migrations) silently drop —
    `_seed_group` reports the gap via `set()` count change."""
    codenames = [
        f"{action}_{model}"
        for action in actions
        for _, model in OPERATIONAL_MODELS
    ]
    qs = Permission.objects.filter(
        content_type__app_label__in=[app for app, _ in OPERATIONAL_MODELS],
        codename__in=codenames,
    )
    return list(qs)


def _seed_group(name: str, actions: list[str]) -> tuple[Group, bool]:
    """Create/update the group with the given action perms.
    Returns (group, created)."""
    group, created = Group.objects.get_or_create(name=name)
    group.permissions.set(_perms_for(actions))
    return group, created


class Command(BaseCommand):
    help = "Seed Editor + Solo Lectura groups and backfill ungrouped users."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-backfill", action="store_true",
            help="Just (re)seed the groups; don't touch existing user assignments.",
        )

    def handle(self, *args, **opts):
        editor_group, editor_created = _seed_group(
            "Editor",
            actions=["view", "add", "change", "delete"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if editor_created else 'Updated'} group 'Editor' "
            f"with {editor_group.permissions.count()} permissions."
        ))

        reader_group, reader_created = _seed_group(
            "Solo Lectura",
            actions=["view"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if reader_created else 'Updated'} group 'Solo Lectura' "
            f"with {reader_group.permissions.count()} permissions."
        ))

        if opts["skip_backfill"]:
            self.stdout.write(self.style.NOTICE(
                "Skipping user backfill (--skip-backfill)."
            ))
            return

        # Backfill: assign ungrouped, non-superuser, active users to Editor.
        # Migrating an existing demo to the permissions world without
        # silently locking everyone out.
        ungrouped = (
            User.objects
            .filter(is_active=True, is_superuser=False, groups__isnull=True)
            .distinct()
        )
        count = 0
        for user in ungrouped:
            user.groups.add(editor_group)
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Backfill: assigned {count} ungrouped user(s) to 'Editor'."
        ))
