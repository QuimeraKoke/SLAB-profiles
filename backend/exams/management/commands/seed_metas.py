"""Seed (or refresh) a 'Metas <Department>' goals template, per department.

Each submission of this template is one clinical goal: free-form objective,
optional related metric (any field key from any template), target value,
deadline, status, plan of action, and observations the patient will see.

Examples:

    # Stand up a 'Metas <name>' template in EVERY department of the club:
    docker compose exec backend python manage.py seed_metas \
        --create-if-missing --all-applicable-categories

    # Single department only:
    docker compose exec backend python manage.py seed_metas \
        --department-slug medico --create-if-missing --all-applicable-categories

    # Multi-club setup — disambiguate with --club:
    ... --club "Demo FC"

Refresh-only (templates must already exist):

    docker compose exec backend python manage.py seed_metas
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate

METAS_SCHEMA: dict = {
    "fields": [
        {
            "key": "asunto", "label": "Objetivo", "type": "text",
            "group": "Encabezado", "required": True,
            "placeholder": "Ej: Reducir masa adiposa",
        },
        {
            "key": "metrica_relacionada", "label": "Métrica relacionada", "type": "text",
            "group": "Encabezado",
            "placeholder": "Ej: masa_adiposa, suma_pliegues, imc",
        },
        {
            "key": "valor_objetivo", "label": "Valor objetivo", "type": "text", "group": "Encabezado",
            "placeholder": "Ej: < 10 kg, > 75 kg, ≤ 12%",
        },
        {
            "key": "plazo", "label": "Plazo", "type": "categorical", "group": "Encabezado",
            "options": ["1 semana", "2 semanas", "1 mes", "3 meses", "6 meses", "1 año", "Sin plazo"],
        },
        {
            "key": "estado", "label": "Estado", "type": "categorical", "group": "Encabezado",
            "options": ["Activa", "En progreso", "Cumplida", "No cumplida"],
        },
        {
            "key": "plan_accion", "label": "Plan de acción", "type": "text",
            "multiline": True, "rows": 6, "required": True,
            "placeholder": "Intervenciones, indicaciones, seguimiento…",
        },
        {
            "key": "observaciones_paciente", "label": "Observaciones para el paciente",
            "type": "text", "multiline": True, "rows": 4,
            "placeholder": "Lo que el paciente verá en su perfil (APP)…",
        },
    ]
}


class Command(BaseCommand):
    help = "Create or refresh a 'Metas <Department>' goals template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default=None,
                            help="Optional department slug (e.g. 'medico', 'nutricional'). "
                                 "When omitted, every department in the club is processed.")
        parser.add_argument("--club", default=None,
                            help="Required when more than one club exists.")
        parser.add_argument("--name", default=None,
                            help="Override the template name. Only valid with --department-slug. "
                                 "Defaults to 'Metas <DepartmentName>' for each department.")
        parser.add_argument("--create-if-missing", action="store_true",
                            help="Create the template if it doesn't exist.")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="When creating, attach to every category in the club whose departments "
                                 "list includes the target department.")
        parser.add_argument("--unlock", action="store_true",
                            help="Clear is_locked. Use only if you accept that historical goals may not "
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
                name=explicit_name or f"Metas {department.name}",
                create=create,
                attach_all=attach_all,
                unlock=unlock,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(departments)} department(s) processed."
        ))

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

        template.config_schema = METAS_SCHEMA
        update_fields = ["config_schema", "updated_at"]
        if unlock and template.is_locked:
            template.is_locked = False
            update_fields.append("is_locked")
        template.save(update_fields=update_fields)

        self.stdout.write(self.style.SUCCESS(
            f"Updated '{template.name}' (department: {department.name})."
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
