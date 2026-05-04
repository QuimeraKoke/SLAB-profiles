"""Bootstrap the bare SLAB club skeleton — club + four departments only.

No categories, no players, no templates, no layouts — just the empty
shell so an admin can take over from Django Admin and configure it
however they want. Useful for showing the platform's multi-tenant
setup alongside the populated Universidad de Chile demo.

Idempotent: safe to re-run; existing club + departments are left
alone.

Run:

    docker compose exec backend python manage.py seed_slab_skeleton
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Club, Department


# Mirrors the four demo departments configured for U. de Chile so the
# two clubs have the same surface for cross-comparison demos.
DEPARTMENTS: list[tuple[str, str]] = [
    ("Médico", "medico"),
    ("Físico", "fisico"),
    ("Nutricional", "nutricional"),
    ("Táctico", "tactico"),
]


class Command(BaseCommand):
    help = "Ensure the SLAB club exists with the four demo departments. Nothing else."

    def add_arguments(self, parser):
        parser.add_argument(
            "--club-name", default="SLAB",
            help="Override the club name (default: 'SLAB').",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        club_name: str = opts["club_name"]

        club, club_created = Club.objects.get_or_create(name=club_name)
        self.stdout.write(self.style.SUCCESS(
            f"Club '{club.name}': {'created' if club_created else 'already existed'}."
        ))

        created_count = 0
        for dept_name, dept_slug in DEPARTMENTS:
            _, dept_created = Department.objects.get_or_create(
                club=club, slug=dept_slug,
                defaults={"name": dept_name},
            )
            if dept_created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  · Department '{dept_name}' (slug={dept_slug}): created."
                ))
            else:
                self.stdout.write(self.style.NOTICE(
                    f"  · Department '{dept_name}' (slug={dept_slug}): already existed."
                ))

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created_count} new department(s) on '{club.name}'."
        ))
