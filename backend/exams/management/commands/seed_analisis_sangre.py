"""Seed the 'Análisis de sangre' consolidated lab-panel template.

Replaces the legacy EAV `examenes` table where each (jugador, fecha,
nombre_examen, valor, unidad) row is one lab measurement. Instead of
13 separate per-test templates, we use ONE template with 13 numeric
fields — easier clinical reading (full panel at a glance) and aligns
with how blood tests are ordered in practice (all 13 from the same
draw on the same day).

The migration command groups source rows by (player, fecha_examen) and
populates whichever fields are present.

Note: `ck` (creatine kinase) has its own dedicated template in SLAB
(separate sampling cadence and standalone alerting), so CK rows in the
legacy `examenes` table land in `ck`, not here.

Run:

    docker compose exec backend python manage.py seed_analisis_sangre \\
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
        # === Hemograma básico ===
        {"key": "hematocrito",        "label": "Hematocrito",        "type": "number", "unit": "%",      "group": "Hemograma"},
        {"key": "hemoglobina",        "label": "Hemoglobina",        "type": "number", "unit": "g/dL",   "group": "Hemograma"},

        # === Hierro y vitaminas ===
        {"key": "ferritina",          "label": "Ferritina",          "type": "number", "unit": "ng/mL",  "group": "Hierro y vitaminas"},
        {"key": "vitamina_b12",       "label": "Vitamina B12",       "type": "number", "unit": "pg/mL",  "group": "Hierro y vitaminas"},
        {"key": "vitamina_d",         "label": "Vitamina D",         "type": "number", "unit": "ng/mL",  "group": "Hierro y vitaminas"},

        # === Eje hormonal ===
        {"key": "testosterona_total", "label": "Testosterona total", "type": "number", "unit": "ng/dL",  "group": "Hormonal"},
        {"key": "testosterona_libre", "label": "Testosterona libre", "type": "number", "unit": "pg/mL",  "group": "Hormonal"},
        {"key": "cortisol",           "label": "Cortisol",           "type": "number", "unit": "µg/dL",  "group": "Hormonal"},

        # === Tiroides ===
        {"key": "tsh",                "label": "TSH",                "type": "number", "unit": "µUI/mL", "group": "Tiroides"},
        {"key": "t3",                 "label": "T3",                 "type": "number", "unit": "ng/dL",  "group": "Tiroides"},
        {"key": "t4_libre",           "label": "T4 libre",           "type": "number", "unit": "ng/dL",  "group": "Tiroides"},

        # === Otras mediciones ===
        {"key": "densidad_urinaria",  "label": "Densidad urinaria",  "type": "number", "unit": "g/mL",   "group": "Otros",
         "help_text": "Indicador de hidratación. También disponible como variable en 'Fase densidad'."},

        # === Calculados ===
        {
            "key": "indice_testo_cortisol", "label": "Índice T/C", "type": "calculated", "unit": "",
            "formula": "[testosterona_total] / [cortisol]",
            "chart_type": "line",
            "help_text": "Indicador de estado anabólico/catabólico (sobre-entrenamiento).",
        },

        # === Notas + adjuntos ===
        {
            "key": "notas", "label": "Notas / interpretación",
            "type": "text", "multiline": True, "rows": 4, "group": "Notas",
            "placeholder": "Observaciones del médico, contexto del muestreo, valores fuera de banda…",
        },
        {
            "key": "informe", "label": "Informe de laboratorio",
            "type": "file", "group": "Adjuntos",
            "placeholder": "PDF / imagen del informe del laboratorio.",
        },
    ],
}


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
}


class Command(BaseCommand):
    help = "Create or refresh the 'Análisis de sangre' consolidated lab-panel template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="Análisis de sangre")
        parser.add_argument("--slug", default="analisis_sangre")
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
