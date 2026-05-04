"""Bootstrap the Universidad de Chile club skeleton.

Creates the club, 5 departments, the Primer Equipo category attached to
all of them, and the four positions (POR / DF / MC / DEL). Idempotent —
re-running is safe; existing rows are left alone.

Run before `seed_uchile_2026` (which inserts players and assumes the
skeleton is already in place):

    docker compose exec backend python manage.py seed_uchile_skeleton
    docker compose exec backend python manage.py seed_uchile_2026
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Category, Club, Department, Position


# Five departments — matches what `seed_uchile_2026` and the demo layouts
# expect. Psicosocial stays in the skeleton even though it's not part of
# the dashboards demo (the platform shows it as a tab).
DEPARTMENTS: list[tuple[str, str]] = [
    ("Médico", "medico"),
    ("Físico", "fisico"),
    ("Nutricional", "nutricional"),
    ("Táctico", "tactico"),
    ("Psicosocial", "psicosocial"),
]

POSITIONS: list[tuple[str, str, int]] = [
    ("Arquero", "POR", 0),
    ("Defensor", "DF", 1),
    ("Mediocampista", "MC", 2),
    ("Delantero", "DEL", 3),
]


class Command(BaseCommand):
    help = (
        "Ensure the Universidad de Chile club exists with departments, "
        "Primer Equipo category, and positions. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument("--club-name", default="Universidad de Chile")
        parser.add_argument("--category-name", default="Primer Equipo")

    @transaction.atomic
    def handle(self, *args, **opts):
        club_name: str = opts["club_name"]
        category_name: str = opts["category_name"]

        club, club_created = Club.objects.get_or_create(name=club_name)
        self.stdout.write(self.style.SUCCESS(
            f"Club '{club.name}': {'created' if club_created else 'already existed'}."
        ))

        # Departments
        departments: list[Department] = []
        for dept_name, dept_slug in DEPARTMENTS:
            dept, dept_created = Department.objects.get_or_create(
                club=club, slug=dept_slug,
                defaults={"name": dept_name},
            )
            departments.append(dept)
            if dept_created:
                self.stdout.write(f"  · Department '{dept_name}': created.")
            else:
                self.stdout.write(self.style.NOTICE(
                    f"  · Department '{dept_name}': already existed."
                ))

        # Category attached to every department.
        category, cat_created = Category.objects.get_or_create(
            club=club, name=category_name,
        )
        if cat_created:
            self.stdout.write(f"  · Category '{category.name}': created.")
        else:
            self.stdout.write(self.style.NOTICE(
                f"  · Category '{category.name}': already existed."
            ))
        category.departments.set(departments)
        self.stdout.write(
            f"    attached to {len(departments)} department(s)."
        )

        # Positions
        for pos_name, abbrev, sort_order in POSITIONS:
            _, pos_created = Position.objects.get_or_create(
                club=club, abbreviation=abbrev,
                defaults={"name": pos_name, "sort_order": sort_order},
            )
            if pos_created:
                self.stdout.write(f"  · Position '{abbrev} – {pos_name}': created.")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Skeleton ready for '{club.name}'."
        ))
