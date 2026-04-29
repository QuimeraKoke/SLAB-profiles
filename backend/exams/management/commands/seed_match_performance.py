"""Seed the per-player match-performance exam template.

One ExamResult row per (player × match) capturing the box-score-style data
that lives PER PLAYER (minutes, cards, goals, etc.). Match-level data
(opponent, final score, competition) lives on `Event.metadata` instead.

Run with:

    docker compose exec backend python manage.py seed_match_performance \\
        --create-if-missing --department-slug tactico \\
        --all-applicable-categories
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


CONFIG_SCHEMA: dict = {
    "fields": [
        {"key": "started_eleven", "label": "Titular",                "type": "boolean", "group": "Convocatoria"},
        {"key": "minutes_played", "label": "Minutos jugados",        "type": "number", "unit": "min", "group": "Tiempo en cancha", "chart_type": "line"},
        {"key": "position_played","label": "Posición jugada",        "type": "categorical",
         "options": ["Portero", "Defensa", "Mediocampista", "Delantero"],
         "group": "Tiempo en cancha"},

        {"key": "goals",          "label": "Goles",                  "type": "number", "unit": "n", "group": "Producción ofensiva", "chart_type": "line"},
        {"key": "assists",        "label": "Asistencias",            "type": "number", "unit": "n", "group": "Producción ofensiva", "chart_type": "line"},
        {"key": "shots",          "label": "Remates",                "type": "number", "unit": "n", "group": "Producción ofensiva"},
        {"key": "shots_on_target","label": "Remates al arco",        "type": "number", "unit": "n", "group": "Producción ofensiva"},

        {"key": "yellow_cards",   "label": "Tarjetas amarillas",     "type": "number", "unit": "n", "group": "Disciplina"},
        {"key": "red_card",       "label": "Tarjeta roja",           "type": "boolean",             "group": "Disciplina"},
        {"key": "fouls_committed","label": "Faltas cometidas",       "type": "number", "unit": "n", "group": "Disciplina"},
        {"key": "fouls_received", "label": "Faltas recibidas",       "type": "number", "unit": "n", "group": "Disciplina"},

        {"key": "rating",         "label": "Calificación (1-10)",    "type": "number", "unit": "/10", "group": "Evaluación", "chart_type": "line"},
        {"key": "notes",          "label": "Notas tácticas",         "type": "text", "multiline": True, "rows": 4, "group": "Evaluación"},
    ],
}

INPUT_CONFIG: dict = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
    # Tells the frontend to render a "match" picker on the single-mode form.
    # When the user picks a match, the result's event FK is set and recorded_at
    # is taken from the match's starts_at server-side.
    "allow_event_link": True,
}


class Command(BaseCommand):
    help = "Seed / overwrite the per-player match-performance template in Táctico."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Rendimiento de partido",
                            help="Template name (default: Rendimiento de partido).")
        parser.add_argument("--club", default=None)
        parser.add_argument("--department-slug", default="tactico")
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true")
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        name: str = opts["name"]
        dept_slug: str = opts["department_slug"]
        club_name: str | None = opts["club"]

        clubs = Club.objects.all()
        if club_name:
            clubs = clubs.filter(name=club_name)
        if not clubs.exists():
            raise CommandError("No clubs match the filter.")
        if club_name is None and clubs.count() > 1:
            raise CommandError("Multiple clubs exist; pass --club to disambiguate.")

        for club in clubs:
            department = Department.objects.filter(club=club, slug=dept_slug).first()
            if not department:
                self.stdout.write(self.style.WARNING(
                    f"[{club.name}] no department with slug '{dept_slug}' — skipping."
                ))
                continue

            template = ExamTemplate.objects.filter(name=name, department=department).first()
            if not template:
                if not opts["create_if_missing"]:
                    self.stdout.write(self.style.WARNING(
                        f"[{club.name}] template '{name}' not found and "
                        "--create-if-missing not set — skipping."
                    ))
                    continue
                template = ExamTemplate.objects.create(
                    name=name, department=department,
                    config_schema=CONFIG_SCHEMA, input_config=INPUT_CONFIG,
                )
                if opts["all_applicable_categories"]:
                    cats = Category.objects.filter(club=club, departments=department)
                    template.applicable_categories.set(cats)
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] created template '{name}' "
                    f"({len(CONFIG_SCHEMA['fields'])} fields, "
                    f"{template.applicable_categories.count()} categories)."
                ))
                continue

            if template.is_locked and not opts["unlock"]:
                self.stdout.write(self.style.WARNING(
                    f"[{club.name}] template '{name}' is locked — pass --unlock to overwrite."
                ))
                continue
            template.config_schema = CONFIG_SCHEMA
            template.input_config = INPUT_CONFIG
            if opts["unlock"]:
                template.is_locked = False
            template.save(update_fields=["config_schema", "input_config", "is_locked", "updated_at"])
            self.stdout.write(self.style.SUCCESS(
                f"[{club.name}] updated template '{name}' "
                f"({len(CONFIG_SCHEMA['fields'])} fields)."
            ))
