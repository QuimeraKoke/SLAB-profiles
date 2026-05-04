"""Create / overwrite a GPS template for training sessions.

A simpler sibling of `seed_gps_match` — same physical-load metrics but
flat (no Primer Tiempo / Segundo Tiempo split) since trainings don't
naturally split into halves. Each entry is one player's training-day
totals: distance, max velocity, accelerations, player load, etc.

Run:

    docker compose exec backend python manage.py seed_gps_training \\
        --create-if-missing --department-slug fisico \\
        --all-applicable-categories
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


CONFIG_SCHEMA: dict = {
    "fields": [
        {
            "key": "fecha", "label": "Fecha del entrenamiento",
            "type": "date", "group": "Sesión", "required": True,
        },
        {
            "key": "tipo_sesion", "label": "Tipo de sesión",
            "type": "categorical", "group": "Sesión",
            "options": ["Tactico", "Fisico", "Tecnico", "Recuperacion", "Pre-partido", "Otro"],
            "option_labels": {
                "Tactico": "Táctico",
                "Fisico": "Físico",
                "Tecnico": "Técnico",
                "Recuperacion": "Recuperación",
                "Pre-partido": "Pre-partido",
                "Otro": "Otro",
            },
        },
        {
            "key": "tot_dur", "label": "Duración total",
            "type": "number", "unit": "min", "group": "Carga",
            "chart_type": "line",
        },
        {
            "key": "tot_dist", "label": "Distancia total",
            "type": "number", "unit": "m", "group": "Distancia",
            "chart_type": "line",
        },
        {
            "key": "hsr", "label": "HSR > 19,8 km/h",
            "type": "number", "unit": "m", "group": "Distancia",
            "chart_type": "line",
        },
        {
            "key": "sprint", "label": "Sprint > 25 km/h",
            "type": "number", "unit": "m", "group": "Distancia",
            "chart_type": "line",
        },
        {
            "key": "max_vel", "label": "Velocidad máxima",
            "type": "number", "unit": "km/h", "group": "Velocidad",
            "chart_type": "line",
        },
        {
            "key": "acc", "label": "Aceleraciones ≥3",
            "type": "number", "unit": "n", "group": "Aceleración",
        },
        {
            "key": "dec", "label": "Desaceleraciones ≥3",
            "type": "number", "unit": "n", "group": "Aceleración",
        },
        {
            "key": "hiaa", "label": "HIAA",
            "type": "number", "unit": "n", "group": "Carga",
        },
        {
            "key": "hmld", "label": "HMLD",
            "type": "number", "unit": "m", "group": "Distancia",
        },
        {
            "key": "player_load", "label": "Player Load",
            "type": "number", "unit": "a.u.", "group": "Carga",
            "chart_type": "line",
        },
        # Cross-field rates derived from totals.
        {
            "key": "mpm", "label": "Metros por minuto",
            "type": "calculated", "unit": "m/min", "group": "Ritmo",
            "formula": "coalesce([tot_dist] / [tot_dur], 0)",
        },
        {
            "key": "hsr_rel", "label": "HSR relativo",
            "type": "calculated", "unit": "m/min", "group": "Ritmo",
            "formula": "coalesce([hsr] / [tot_dur], 0)",
        },
        {
            "key": "rpe", "label": "RPE (esfuerzo percibido 1-10)",
            "type": "number", "unit": "", "group": "Sensaciones",
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "group": "Sensaciones",
            "multiline": True, "rows": 3,
        },
    ],
}


INPUT_CONFIG: dict = {
    # Roster-style entry — one row per player per training day. The
    # `fecha` and `tipo_sesion` cells become shared fields so the staffer
    # types them once.
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "modifiers": {"prefill_from_last": False},
    "team_table": {
        "shared_fields": ["fecha", "tipo_sesion"],
        # row_fields defaults to "everything not in shared_fields and not calculated".
    },
}


class Command(BaseCommand):
    help = "Create / refresh the 'GPS Entrenamiento' template (Físico, training-day totals)."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="fisico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="GPS Entrenamiento")
        parser.add_argument("--slug", default="gps_entrenamiento")
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
                    config_schema=CONFIG_SCHEMA,
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
                template.config_schema = CONFIG_SCHEMA
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
                    f"[{club.name}] {action} '{template.name}' "
                    f"(slug={template.slug}); attached to: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' (slug={template.slug})"
                ))
