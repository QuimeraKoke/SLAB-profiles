"""Create the "Peso y Talla" template for the Nutricional area.

Two anthropometry inputs — peso (kg) and altura (cm) — plus a calculated IMC
(índice de masa corporal / BMI). Altura is entered in centimetres, so the
formula converts to metres inside the BMI expression:

    IMC = peso(kg) / altura(m)²  =  peso / (altura/100)²  =  peso / altura² · 10000

The formula engine's `round()` takes a single argument (int ndigits coerces to
float and Python's round rejects that), so two-decimal rounding is written as
`round(x * 100) / 100` — same idiom as seed_fatiga_central.

    docker compose exec backend python manage.py seed_peso_talla \\
        --create-if-missing --club "Universidad de Chile"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department


# Standard WHO BMI categories — informational colouring only (no `alert`):
# athletes routinely read "sobrepeso" from muscle mass, so firing alerts here
# would be noise.
_BMI_BANDS = [
    {"max": 18.5, "label": "Bajo peso", "color": "#f59e0b"},
    {"min": 18.5, "max": 25, "label": "Normal", "color": "#16a34a"},
    {"min": 25, "max": 30, "label": "Sobrepeso", "color": "#f59e0b"},
    {"min": 30, "label": "Obesidad", "color": "#dc2626"},
]


SCHEMA: dict = {
    "fields": [
        {
            "key": "peso", "label": "Peso", "type": "number", "unit": "kg",
            "group": "Antropometría", "chart_type": "line",
            "min": 30, "max": 200,
        },
        {
            "key": "altura", "label": "Altura", "type": "number", "unit": "cm",
            "group": "Antropometría", "chart_type": "line",
            "min": 120, "max": 230,
        },
        {
            "key": "imc", "label": "IMC", "type": "calculated", "unit": "kg/m²",
            "group": "Antropometría", "chart_type": "line",
            # peso / (altura/100)² to 2 decimals; altura in cm.
            "formula": "round([peso] / ([altura] * [altura]) * 1000000) / 100",
            "reference_ranges": _BMI_BANDS,
        },
    ],
}

INPUT_CONFIG: dict = {
    # team_table = multi-player grid; bulk_ingest = "Subir archivo" (load from
    # file); single ("Individual") is always offered by the Subir-datos hub.
    "input_modes": ["team_table", "bulk_ingest"],
    "default_input_mode": "team_table",
    # Let staff set WHEN the measurement was taken (a date input appears in the
    # single, team-table, and file flows) instead of defaulting to "now".
    "modifiers": {"allow_custom_date": True},
    "team_table": {"shared_fields": []},
}

NAME = "Peso y Talla"
SLUG = "peso_talla"


class Command(BaseCommand):
    help = "Create/refresh the Nutricional 'Peso y Talla' template (peso, altura, IMC)."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="nutricional")
        parser.add_argument("--club", default=None)
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        from exams.models import ExamTemplate

        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No clubs found.")
        if clubs.count() > 1 and not opts["club"]:
            raise CommandError("Multiple clubs exist; pass --club <name>.")

        for club in clubs:
            dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
            if dept is None:
                raise CommandError(f"Department '{opts['department_slug']}' not in '{club.name}'.")

            template = ExamTemplate.objects.filter(department=dept, slug=SLUG).first()
            if template is None:
                template = ExamTemplate.objects.filter(department=dept, name=NAME).first()
            if template is None:
                if not opts["create_if_missing"]:
                    self.stdout.write(self.style.WARNING(
                        f"[{club.name}] '{NAME}' not found (pass --create-if-missing)."))
                    continue
                template = ExamTemplate(name=NAME, slug=SLUG, department=dept,
                                        config_schema=SCHEMA, input_config=INPUT_CONFIG)
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"[{club.name}] '{template.name}' is locked; pass --unlock."))
                    continue
                template.config_schema = SCHEMA
                template.input_config = INPUT_CONFIG
                if opts["unlock"]:
                    template.is_locked = False
                template.save()
                action = "refreshed"

            template.rebuild_template_fields()
            cats = Category.objects.filter(club=club, departments=dept)
            template.applicable_categories.set(cats)
            self.stdout.write(self.style.SUCCESS(
                f"[{club.name}] {action} '{template.name}' (slug={template.slug}); "
                f"categories: {', '.join(c.name for c in cats) or '(none)'}"
            ))
