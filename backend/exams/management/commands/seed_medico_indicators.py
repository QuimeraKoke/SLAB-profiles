"""Create the three small clinical-indicator templates for Médico:
CK, Densidad urinaria, and CMJ.

These were originally authored ad-hoc via Django Admin; this command
makes them reproducible so a fresh DB boots into the full demo state.

Run:

    docker compose exec backend python manage.py seed_medico_indicators \\
        --create-if-missing --department-slug medico \\
        --all-applicable-categories --club "Universidad de Chile"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


# --- CK (creatine kinase) — single numeric reading per take ---
CK_SCHEMA: dict = {
    "fields": [
        {"key": "fecha", "label": "Fecha", "type": "date", "group": "Toma", "required": True},
        {
            "key": "valor", "label": "CK", "type": "number",
            "unit": "U/L", "group": "Toma", "chart_type": "line",
        },
        {
            "key": "nota", "label": "Notas", "type": "text",
            "multiline": True, "rows": 2, "group": "Toma",
        },
    ],
}

CK_INPUT_CONFIG: dict = {
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": ["fecha"]},
}


# --- Densidad urinaria (formerly "Hidratación") — urine specific gravity ---
DENSIDAD_URINARIA_SCHEMA: dict = {
    "fields": [
        {"key": "fecha", "label": "Fecha", "type": "date", "group": "Toma", "required": True},
        {
            "key": "densidad_urinaria", "label": "Densidad urinaria",
            "type": "number", "group": "Toma", "chart_type": "line",
        },
        {
            "key": "notas", "label": "Notas", "type": "text",
            "multiline": True, "rows": 2, "group": "Toma",
        },
    ],
}

DENSIDAD_URINARIA_INPUT_CONFIG: dict = {
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": ["fecha"]},
}


# --- CMJ (countermovement jump) — height + technique tag ---
CMJ_SCHEMA: dict = {
    "fields": [
        {
            "key": "contramovimiento", "label": "Salto contramovimiento",
            "type": "number", "unit": "cm", "group": "Test",
            "chart_type": "line",
            # Reference bands (G. Tapia / club): 40–45 cm media; alto = mejor.
            "direction_of_good": "up",
            "reference_ranges": [
                {"max": 40, "label": "Bajo", "color": "#dc2626"},
                {"min": 40, "max": 45, "label": "En rango", "color": "#f59e0b"},
                {"min": 45, "label": "Óptimo", "color": "#16a34a"},
            ],
        },
        {
            "key": "vuelta_carnero", "label": "Vuelta de carnero",
            "type": "categorical", "group": "Test",
            "options": ["Si", "No"],
            "option_labels": {"Si": "Sí", "No": "No"},
        },
        {
            "key": "salto_mt", "label": "Salto en metros",
            "type": "calculated", "unit": "m", "group": "Test",
            "formula": "[contramovimiento] / 100",
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

CMJ_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


# --- Nórdico (eccentric hamstring strength, NordBord) — per-leg force ---
# Reference bands (G. Tapia / club): 350–400 N por pierna; alto = mejor.
# Relative N/kg (4.0–4.5) lives as physiological context; absolute N is the
# tracked value. Asymmetry: lower = better.
_NORDIC_FORCE_BANDS = [
    {"max": 350, "label": "Bajo", "color": "#dc2626"},
    {"min": 350, "max": 400, "label": "En rango", "color": "#f59e0b"},
    {"min": 400, "label": "Óptimo", "color": "#16a34a"},
]

NORDICO_SCHEMA: dict = {
    "fields": [
        {
            "key": "fuerza_izq", "label": "Fuerza nórdica – Izquierda",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _NORDIC_FORCE_BANDS,
        },
        {
            "key": "fuerza_der", "label": "Fuerza nórdica – Derecha",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _NORDIC_FORCE_BANDS,
        },
        {
            "key": "asimetria", "label": "Asimetría",
            "type": "number", "unit": "%", "group": "Test",
            "chart_type": "line", "direction_of_good": "down",
            "reference_ranges": [
                {"max": 10, "label": "Simétrico", "color": "#16a34a"},
                {"min": 10, "max": 15, "label": "Leve", "color": "#f59e0b"},
                {"min": 15, "label": "Marcada", "color": "#dc2626"},
            ],
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

NORDICO_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


# --- Fuerza isométrica en prono (rodilla casi extendida) — per-leg force ---
# Reference bands (G. Tapia / club): 290–320 N por pierna (~3.5 N/kg); alto =
# mejor. Sensible al ángulo: a 30° de flexión (ISO 30) asciende a ~350–370 N
# (anotar el protocolo en Notas).
_ISO_PRONO_BANDS = [
    {"max": 290, "label": "Bajo", "color": "#dc2626"},
    {"min": 290, "max": 320, "label": "En rango", "color": "#f59e0b"},
    {"min": 320, "label": "Óptimo", "color": "#16a34a"},
]

ISO_PRONO_SCHEMA: dict = {
    "fields": [
        {
            "key": "fuerza_izq", "label": "Fuerza isométrica – Izquierda",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _ISO_PRONO_BANDS,
        },
        {
            "key": "fuerza_der", "label": "Fuerza isométrica – Derecha",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _ISO_PRONO_BANDS,
        },
        {
            "key": "protocolo", "label": "Protocolo (ángulo)",
            "type": "categorical", "group": "Test",
            "options": ["extension", "iso30"],
            "option_labels": {"extension": "Rodilla casi extendida", "iso30": "ISO 30°"},
        },
        {
            "key": "asimetria", "label": "Asimetría",
            "type": "number", "unit": "%", "group": "Test",
            "chart_type": "line", "direction_of_good": "down",
            "reference_ranges": [
                {"max": 10, "label": "Simétrico", "color": "#16a34a"},
                {"min": 10, "max": 15, "label": "Leve", "color": "#f59e0b"},
                {"min": 15, "label": "Marcada", "color": "#dc2626"},
            ],
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

ISO_PRONO_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


TEMPLATES = [
    ("CK", "ck", CK_SCHEMA, CK_INPUT_CONFIG),
    ("Densidad urinaria", "densidad_urinaria", DENSIDAD_URINARIA_SCHEMA, DENSIDAD_URINARIA_INPUT_CONFIG),
    ("CMJ", "cmj", CMJ_SCHEMA, CMJ_INPUT_CONFIG),
    ("Nórdico", "nordico", NORDICO_SCHEMA, NORDICO_INPUT_CONFIG),
    ("Fuerza isométrica (prono)", "iso_prono", ISO_PRONO_SCHEMA, ISO_PRONO_INPUT_CONFIG),
]


class Command(BaseCommand):
    help = (
        "Create / refresh the Médico clinical-indicator templates "
        "(CK, Densidad urinaria, CMJ)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
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
                    f"Department '{opts['department_slug']}' not found in '{club.name}'."
                )

            for name, slug, schema, input_config in TEMPLATES:
                template = ExamTemplate.objects.filter(
                    department=dept, name=name,
                ).first()
                if template is None:
                    if not opts["create_if_missing"]:
                        self.stdout.write(self.style.WARNING(
                            f"Skipping '{name}' (not found, --create-if-missing not passed)."
                        ))
                        continue
                    template = ExamTemplate(
                        name=name, slug=slug, department=dept,
                        config_schema=schema, input_config=input_config,
                    )
                    template.save()
                    action = "created"
                else:
                    if template.is_locked and not opts["unlock"]:
                        self.stdout.write(self.style.WARNING(
                            f"'{template.name}' is locked; pass --unlock to refresh."
                        ))
                        continue
                    template.config_schema = schema
                    template.input_config = input_config
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
                        f"(slug={template.slug}); attached to: {cats_label}"
                    ))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"[{club.name}] {action} '{template.name}' (slug={template.slug})"
                    ))
