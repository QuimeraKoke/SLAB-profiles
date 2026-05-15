"""Seed the 'Check-IN' daily wellness checklist template.

Five Likert (1-5) dimensions reported by the player each day, plus a
calculated `total_bienestar` (sum, range 5-25). Higher = better in all
dimensions: 1 = worst, 5 = best (e.g. 5 on DOMS means "no muscle pain",
5 on Sueño means "slept great"). This matches standard sports-science
wellness questionnaires (Hooper-Mackinnon family).

The reference_ranges below auto-wire BAND alert rules — re-running
`python manage.py seed_band_alerts` after this command creates one
rule per low-band field so a 1 or 2 on any axis fires a critical
alert into the medical team's dashboard.

Run:

    docker compose exec backend python manage.py seed_check_in \\
        --create-if-missing --department-slug medico \\
        --all-applicable-categories
    docker compose exec backend python manage.py seed_band_alerts
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


# Three-band coloring on the 1-5 axes. Boundaries inclusive on lower side;
# the per-band evaluator walks declaration order and first-match wins, so
# a value of exactly 3 lands in "Medio" not "Bueno".
LIKERT_BANDS = [
    {"label": "Bajo",       "max": 2, "color": "#dc2626"},  # 1, 2
    {"label": "Aceptable",  "min": 3, "max": 3, "color": "#f59e0b"},  # 3
    {"label": "Bueno",      "min": 4, "color": "#16a34a"},  # 4, 5
]


def _likert_field(key: str, label: str) -> dict:
    """Helper: a 1-5 Likert numeric field with consistent bands."""
    return {
        "key": key,
        "label": label,
        "type": "number",
        "unit": "pts",
        "required": True,
        "direction_of_good": "up",
        "reference_ranges": LIKERT_BANDS,
        "placeholder": "1 (peor) – 5 (mejor)",
    }


SCHEMA: dict = {
    "fields": [
        _likert_field("doms",   "DOMS (dolor muscular)"),
        _likert_field("animo",  "Estado de ánimo"),
        _likert_field("estres", "Estrés"),
        _likert_field("fatiga", "Fatiga"),
        _likert_field("sueno",  "Sueño"),
        # Calculated total — simple sum across the 5 dimensions. With each
        # axis 1-5 the total spans 5..25; bands below segment that range
        # into clinical zones for the BAND alert engine.
        {
            "key": "total_bienestar",
            "label": "Total Bienestar",
            "type": "calculated",
            "unit": "pts",
            "direction_of_good": "up",
            "formula": "[doms] + [animo] + [estres] + [fatiga] + [sueno]",
            "reference_ranges": [
                {"label": "Bajo",      "max": 12,  "color": "#dc2626"},
                {"label": "Aceptable", "min": 13, "max": 18, "color": "#f59e0b"},
                {"label": "Bueno",     "min": 19, "color": "#16a34a"},
            ],
        },
    ],
}


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
}


class Command(BaseCommand):
    help = "Create or refresh the 'Check-IN' daily-wellness template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="Check-IN")
        parser.add_argument("--slug", default="check_in")
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
