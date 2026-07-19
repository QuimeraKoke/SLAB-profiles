"""Seed the 'Masoterapia' department + exam template — treated-zone logging for
the massage-therapy team, using the interactive `bodymap` field type on the
full-body diagram.

Unlike podología, the Masoterapia department doesn't exist yet, so this command
also creates it (idempotent) and links it to the same categories that already
run the `medico` department (so it shows up for, e.g., Primer Equipo). Each
record is a flat `ExamResult`: the therapist drops pins on the front/back body
figure (zone auto-detected) and writes one comment.

    docker compose exec backend python manage.py seed_masoterapia_template \\
        --club "Universidad de Chile" --create-if-missing --all-applicable-categories
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


def _build_schema() -> dict:
    return {
        "fields": [
            {
                "key": "fecha",
                "label": "Fecha de atención",
                "type": "date",
                "group": "Atención",
                "required": True,
            },
            {
                "key": "zonas",
                "label": "Zonas tratadas",
                "type": "bodymap",
                "diagram": "body",
                "group": "Atención",
                "required": True,
            },
            {
                "key": "comentario",
                "label": "Comentario",
                "type": "text",
                "multiline": True,
                "rows": 4,
                "group": "Atención",
                "placeholder": "Técnica aplicada, hallazgos, indicaciones…",
            },
        ],
    }


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
}


class Command(BaseCommand):
    help = "Create the Masoterapia department + its bodymap template (full-body, flat)."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="masoterapia")
        parser.add_argument("--department-name", default="Masoterapia")
        parser.add_argument("--club", default=None, help="Limit to one club by name.")
        parser.add_argument("--name", default="Masoterapia")
        parser.add_argument("--slug", default="masoterapia")
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true")
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        schema = _build_schema()

        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No clubs found.")

        for club in clubs:
            # 1. Ensure the department exists.
            dept, dept_created = Department.objects.get_or_create(
                club=club, slug=opts["department_slug"],
                defaults={"name": opts["department_name"]},
            )
            if dept_created:
                self.stdout.write(f"[{club.name}] departamento '{dept.name}' creado.")

            # 2. Make it visible where the medical dept already runs (so the
            #    template's applicable_categories aren't empty).
            medico = Department.objects.filter(club=club, slug="medico").first()
            if medico:
                med_cats = Category.objects.filter(club=club, departments=medico)
                for cat in med_cats:
                    cat.departments.add(dept)

            # 3. Create / refresh the template.
            template = ExamTemplate.objects.filter(department=dept, name=opts["name"]).first()
            if template is None:
                if not opts["create_if_missing"]:
                    raise CommandError(
                        f"Template '{opts['name']}' not found in {dept}; "
                        f"pass --create-if-missing to create it."
                    )
                template = ExamTemplate(
                    name=opts["name"],
                    slug=opts["slug"],
                    department=dept,
                    config_schema=schema,
                    input_config=INPUT_CONFIG,
                    is_episodic=False,
                    show_injuries=False,
                )
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"Template '{template.name}' is locked; pass --unlock to refresh."
                    ))
                    continue
                template.config_schema = schema
                template.input_config = INPUT_CONFIG
                template.is_episodic = False
                template.episode_config = {}
                if opts["unlock"]:
                    template.is_locked = False
                template.save()
                action = "refreshed"

            template.rebuild_template_fields()

            if opts["all_applicable_categories"]:
                cats = Category.objects.filter(club=club, departments=dept)
                template.applicable_categories.set(cats)
                cats_label = ", ".join(c.name for c in cats) or "(none)"
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' "
                    f"(slug={template.slug}); categorías: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' (slug={template.slug})"
                ))
