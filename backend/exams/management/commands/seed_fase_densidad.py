"""Seed the 'Fase / Densidad' template.

Mirrors the legacy `fase_densidad` table — a tall EAV with 4 distinct
`variable` values (Densidad Urinaria, Fase Ciclo Menstrual, Índice MAD,
Edad PHV) grouped per (player, fecha_evaluacion). Consolidated into one
template with 4 fields so each evaluation is a single ExamResult.

Densidad urinaria intentionally also exists on the `analisis_sangre`
panel — pre-2025 legacy stored it under `examenes`, 2025+ under
`fase_densidad`. Filling it in either one is fine; the migration uses
whichever source row it sees.

Run:

    docker compose exec backend python manage.py seed_fase_densidad \\
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
            "key": "densidad_urinaria", "label": "Densidad urinaria",
            "type": "number", "unit": "g/mL", "group": "Hidratación",
            "help_text": "Indicador de hidratación pre-entrenamiento (referencia 1.020–1.030).",
            "direction_of_good": "down",
            "reference_ranges": [
                {"label": "Hidratado",      "max": 1.020,             "color": "#16a34a"},
                {"label": "Amarillo",       "min": 1.020, "max": 1.030, "color": "#f59e0b"},
                {"label": "Deshidratado",   "min": 1.030,             "color": "#dc2626"},
            ],
        },
        {
            "key": "fase_ciclo_menstrual", "label": "Fase ciclo menstrual",
            "type": "categorical", "group": "Hormonal",
            "options": [
                "Menstrual",
                "Folicular",
                "Ovulatoria",
                "Lútea",
                "No aplica",
            ],
            "help_text": "Sólo para categorías femeninas. Útil para correlacionar carga / fatiga / hidratación.",
        },
        {
            "key": "indice_mad", "label": "Índice MAD",
            "type": "number", "unit": "", "group": "Madurez biológica",
            "help_text": "Índice Maturity-Age-Decimalized (proxy de madurez biológica relativa a la edad).",
        },
        {
            "key": "edad_phv", "label": "Edad PHV",
            "type": "number", "unit": "años", "group": "Madurez biológica",
            "help_text": "Peak Height Velocity — edad en años a la que el jugador alcanzó/alcanzará su mayor velocidad de crecimiento.",
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 3, "group": "Notas",
            "placeholder": "Contexto del muestreo, observaciones del staff…",
        },
    ],
}


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
}


class Command(BaseCommand):
    help = "Create or refresh the 'Fase / Densidad' template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="Fase / Densidad")
        parser.add_argument("--slug", default="fase_densidad")
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
            dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
            if dept is None:
                raise CommandError(
                    f"Department '{opts['department_slug']}' not found in club '{club.name}'."
                )

            template = ExamTemplate.objects.filter(
                department=dept, name=opts["name"],
            ).first()

            if template is None:
                if not opts["create_if_missing"]:
                    raise CommandError(
                        f"Template '{opts['name']}' not found in {dept}; "
                        f"pass --create-if-missing."
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
                        f"Template '{template.name}' is locked; pass --unlock to refresh."
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
                    f"[{club.name}] {action} '{template.name}' (slug={template.slug}); "
                    f"attached to: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' (slug={template.slug})"
                ))
