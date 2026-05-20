"""Seed the 'Hoja diaria — Médico' exam template.

Daily medical intervention log — one ExamResult per visit/treatment.
Mirrors the legacy `hoja_diaria` table at U. de Chile (14k+ historical
rows). Per the audit, `tratamientomusculo` in the legacy actually mixed
two concepts (target muscle vs. modality), so we split them here into
`musculo_objetivo` (categorical: muscle/anatomical region) and
`modalidad` (categorical: treatment type — bicicleta, masaje, drenaje…).

Run:

    docker compose exec backend python manage.py seed_hoja_diaria_medico \\
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
        # === Identificación de la intervención ===
        {
            "key": "causa", "label": "Causa de la intervención",
            "type": "categorical", "required": True, "group": "Intervención",
            "options": [
                "Tratamiento lesión",
                "Tratamiento molestia",
                "Recuperación post-partido",
                "Recuperación post-entrenamiento",
                "Evaluación",
                "Prevención",
            ],
        },
        {
            "key": "tipo", "label": "Tipo de intervención",
            "type": "categorical", "required": True, "group": "Intervención",
            "options": [
                "Atención médica",
                "Kinesiología",
                "Fisiatría",
                "Masoterapia",
                "Recuperación física",
                "Crioterapia",
                "Termoterapia",
            ],
        },

        # === Foco del tratamiento (split del legacy `tratamientomusculo`) ===
        {
            "key": "musculo_objetivo", "label": "Músculo / región tratada",
            "type": "categorical", "group": "Tratamiento",
            "options": [
                "Isquiotibial",
                "Cuádriceps",
                "Aductores",
                "Gemelo / Sóleo",
                "Pantorrilla",
                "Tobillo",
                "Rodilla",
                "Cadera",
                "Lumbar / sacra",
                "Espalda alta",
                "Hombro",
                "Brazo",
                "Cuello / cervical",
                "Cabeza",
                "Tórax",
                "Abdomen",
                "Múltiple",
                "No aplica",
                "Otra",
            ],
            "help_text": "Zona anatómica objetivo de la intervención.",
        },
        {
            "key": "modalidad", "label": "Modalidad / técnica",
            "type": "categorical", "group": "Tratamiento",
            "options": [
                "Masaje",
                "Bicicleta",
                "Flexibilidad",
                "CORE",
                "Balance",
                "Terapia manual",
                "Botas de drenaje",
                "Vendaje funcional",
                "Tens / Ultrasonido",
                "Ejercicio terapéutico",
                "Movilidad articular",
                "Reintegro en cancha",
                "Protocolo recovery",
                "Calor",
                "Frío / crioterapia",
                "Otra",
            ],
            "help_text": "Técnica o modalidad de tratamiento aplicada.",
        },
        {
            "key": "lateralidad", "label": "Lateralidad",
            "type": "categorical", "group": "Tratamiento",
            "options": ["Izquierdo", "Derecho", "Bilateral", "No aplica"],
        },

        # === Comentarios ===
        {
            "key": "comentarios", "label": "Comentarios / observaciones",
            "type": "text", "multiline": True, "rows": 4, "group": "Notas",
            "placeholder": "Síntomas, evolución del jugador, plan de seguimiento…",
        },

        # === Workflow marker (legacy `color` column) ===
        {
            "key": "color", "label": "Marca de seguimiento",
            "type": "categorical", "group": "Seguimiento",
            "options": ["Verde", "Amarillo", "Naranja", "Rojo", "Sin marca"],
            "help_text": "Color de seguimiento usado por el área médica para priorizar casos.",
        },
    ],
}


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
}


class Command(BaseCommand):
    help = "Create or refresh the 'Hoja diaria — Médico' template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="Hoja diaria — Médico")
        parser.add_argument("--slug", default="hoja_diaria_medico")
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
