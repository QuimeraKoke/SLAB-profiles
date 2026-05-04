"""Seed (or refresh) a 'Notas diarias <Department>' template, per department.

Each submission is one daily entry: the doctor sets the date (defaults to today
in the form), an optional subject line, and a free-form note body.

Examples:

    # Stand up daily-notes templates in EVERY department of the club:
    docker compose exec backend python manage.py seed_daily_notes \
        --create-if-missing --all-applicable-categories

    # Single department only:
    docker compose exec backend python manage.py seed_daily_notes \
        --department-slug medico --create-if-missing --all-applicable-categories

Refresh-only (templates must already exist):

    docker compose exec backend python manage.py seed_daily_notes
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate

DAILY_NOTES_SCHEMA: dict = {
    "fields": [
        {
            "key": "fecha", "label": "Fecha", "type": "date",
            "group": "Encabezado", "required": True,
        },
        {
            "key": "asunto", "label": "Asunto", "type": "text", "group": "Encabezado",
            "placeholder": "Ej: Sesión de entrenamiento, consulta, observación…",
        },
        {
            "key": "nota", "label": "Nota", "type": "text",
            "multiline": True, "rows": 8, "required": True,
            "placeholder": "Observaciones del día, intervenciones, hallazgos…",
        },
    ]
}


class Command(BaseCommand):
    help = "Create or refresh a 'Notas diarias <Department>' template per department."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default=None,
                            help="Optional department slug. When omitted, every department is processed.")
        parser.add_argument("--club", default=None,
                            help="Required when more than one club exists.")
        parser.add_argument("--name", default=None,
                            help="Override the template name. Only valid with --department-slug. "
                                 "Defaults to 'Notas diarias <DepartmentName>'.")
        parser.add_argument("--create-if-missing", action="store_true",
                            help="Create the template if it doesn't exist.")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="When creating, attach to every category in the club whose departments "
                                 "list includes the target department.")
        parser.add_argument("--unlock", action="store_true",
                            help="Clear is_locked. Use only if you accept that historical entries may not "
                                 "match the new schema.")

    def handle(self, *args, **options):
        department_slug = options["department_slug"]
        club_name = options["club"]
        explicit_name = options["name"]
        create = options["create_if_missing"]
        attach_all = options["all_applicable_categories"]
        unlock = options["unlock"]

        if explicit_name and not department_slug:
            raise CommandError("--name only makes sense together with --department-slug.")

        club = self._resolve_club(club_name)

        if department_slug:
            department = Department.objects.filter(club=club, slug=department_slug).first()
            if department is None:
                raise CommandError(
                    f"Department slug='{department_slug}' not found in club '{club.name}'. "
                    "Create it in Django Admin (Core → Departments → Add)."
                )
            departments = [department]
        else:
            departments = list(Department.objects.filter(club=club))
            if not departments:
                raise CommandError(
                    f"Club '{club.name}' has no departments yet. Create some in Django Admin first."
                )

        for department in departments:
            self._sync_department(
                department=department,
                club=club,
                name=explicit_name or f"Notas diarias {department.name}",
                create=create,
                attach_all=attach_all,
                unlock=unlock,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(departments)} department(s) processed."
        ))

    def _resolve_club(self, club_name: str | None) -> Club:
        if club_name:
            club = Club.objects.filter(name=club_name).first()
            if club is None:
                raise CommandError(f"Club '{club_name}' not found.")
            return club
        clubs = list(Club.objects.all()[:2])
        if len(clubs) == 0:
            raise CommandError("No clubs in the database. Create one in Django Admin first.")
        if len(clubs) > 1:
            raise CommandError("Multiple clubs exist; pass --club <name> to disambiguate.")
        return clubs[0]

    def _sync_department(self, *, department: Department, club: Club, name: str,
                         create: bool, attach_all: bool, unlock: bool) -> None:
        template = ExamTemplate.objects.filter(name=name, department=department).first()
        if template is None:
            if not create:
                self.stdout.write(self.style.WARNING(
                    f"Skipped '{department.name}': no template '{name}' "
                    "(pass --create-if-missing to create it)."
                ))
                return
            template = self._create_template(name, department, club, attach_all)

        template.config_schema = DAILY_NOTES_SCHEMA
        update_fields = ["config_schema", "updated_at"]
        if unlock and template.is_locked:
            template.is_locked = False
            update_fields.append("is_locked")
        template.save(update_fields=update_fields)

        # Honor `--all-applicable-categories` on UPDATE too. Templates created
        # without categories on a prior run would otherwise stay detached and
        # `seed_fake_exams` would silently skip them.
        if attach_all:
            categories = Category.objects.filter(club=club, departments=department)
            template.applicable_categories.set(categories)

        self.stdout.write(self.style.SUCCESS(
            f"Updated '{template.name}' (department: {department.name}, "
            f"categories: {template.applicable_categories.count()})."
        ))

    @transaction.atomic
    def _create_template(self, name: str, department: Department, club: Club,
                         attach_all: bool) -> ExamTemplate:
        template = ExamTemplate.objects.create(
            name=name, department=department, config_schema={},
        )
        if attach_all:
            categories = Category.objects.filter(club=club, departments=department)
            template.applicable_categories.set(categories)
            self.stdout.write(self.style.NOTICE(
                f"Attached '{template.name}' to {categories.count()} categories "
                f"({', '.join(c.name for c in categories) or 'none'})."
            ))
        else:
            self.stdout.write(self.style.NOTICE(
                f"Created '{template.name}' with no applicable_categories — set them "
                "in Django Admin or re-run with --all-applicable-categories."
            ))
        return template
