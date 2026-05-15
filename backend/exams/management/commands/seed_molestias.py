"""Seed the 'Molestias' daily-log exam template.

Models the medical-department daily discomfort log from the PEM medical
report: each entry captures `tipo` (kinesiology / chiropractic / etc.),
the affected `zona`, and free-text `comentarios`. Non-episodic — every
result is a standalone session. Players can have multiple entries per
day; the timeline / activity-log widgets surface them newest-first.

Run:

    docker compose exec backend python manage.py seed_molestias \\
        --create-if-missing --department-slug medico \\
        --all-applicable-categories
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


SCHEMA: dict = {
    "fields": [
        {
            "key": "tipo",
            "label": "Tipo",
            "type": "categorical",
            "required": True,
            "options": [
                "Kinesiología",
                "Quiropráctica",
                "Fisiatría",
                "Masoterapia",
                "Crioterapia",
                "Termoterapia",
                "Otro",
            ],
        },
        {
            "key": "zona",
            "label": "Zona",
            "type": "categorical",
            "options": [
                "Cabeza", "Cuello",
                "Hombro izq.", "Hombro der.",
                "Brazo izq.", "Brazo der.",
                "Espalda alta", "Espalda baja",
                "Cadera / pelvis",
                "Muslo izq.", "Muslo der.",
                "Rodilla izq.", "Rodilla der.",
                "Pantorrilla izq.", "Pantorrilla der.",
                "Tobillo izq.", "Tobillo der.",
                "Pie izq.", "Pie der.",
            ],
            # Body-map regions — reuses the same canonical names as the
            # Lesiones template so a single heatmap can overlay both.
            "option_regions": {
                "Cabeza": "head",
                "Cuello": "neck",
                "Hombro izq.": "left_shoulder",
                "Hombro der.": "right_shoulder",
                "Brazo izq.": "left_arm",
                "Brazo der.": "right_arm",
                "Espalda alta": "upper_back",
                "Espalda baja": "lower_back",
                "Cadera / pelvis": "pelvis",
                "Muslo izq.": "left_thigh",
                "Muslo der.": "right_thigh",
                "Rodilla izq.": "left_knee",
                "Rodilla der.": "right_knee",
                "Pantorrilla izq.": "left_calf",
                "Pantorrilla der.": "right_calf",
                "Tobillo izq.": "left_calf",
                "Tobillo der.": "right_calf",
                "Pie izq.": "left_foot",
                "Pie der.": "right_foot",
            },
        },
        {
            "key": "comentarios",
            "label": "Comentarios",
            "type": "text",
            "multiline": True,
            "rows": 3,
            "placeholder": "Detalle del tratamiento aplicado o molestia reportada…",
        },
    ],
}


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
}


class Command(BaseCommand):
    help = "Create or refresh the 'Molestias' daily-log template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico",
                            help="Department slug (default: 'medico').")
        parser.add_argument("--club", default=None,
                            help="Required when more than one club exists.")
        parser.add_argument("--name", default="Molestias")
        parser.add_argument("--slug", default="molestias")
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true")
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No clubs found.")
        if clubs.count() > 1 and not opts["club"]:
            raise CommandError("Multiple clubs exist; pass --club <name>.")

        for club in clubs:
            dept = Department.objects.filter(
                club=club, slug=opts["department_slug"],
            ).first()
            if dept is None:
                raise CommandError(
                    f"Department '{opts['department_slug']}' not found in {club}."
                )

            template = ExamTemplate.objects.filter(
                department=dept, name=opts["name"],
            ).first()
            if template is None:
                if not opts["create_if_missing"]:
                    raise CommandError(
                        f"Template '{opts['name']}' not found; pass "
                        "--create-if-missing to create."
                    )
                template = ExamTemplate(
                    name=opts["name"],
                    slug=opts["slug"],
                    department=dept,
                    config_schema=SCHEMA,
                    input_config=INPUT_CONFIG,
                )
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"'{template.name}' is locked — pass --unlock."
                    ))
                    continue
                template.config_schema = SCHEMA
                template.input_config = INPUT_CONFIG
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
                    f"[{club.name}] {action} '{template.name}'; categories: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}'."
                ))
