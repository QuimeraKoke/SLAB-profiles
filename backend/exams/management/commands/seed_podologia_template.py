"""Seed the 'Podología' exam template — treated-zone logging for the podiatry
department, using the interactive `bodymap` field type.

Each record is a flat `ExamResult` (no episode lifecycle): the podiatrist drops
pins on the plantar/dorsal foot diagram (BOTH feet are shown, so the foot side
is implicit in the zone) and writes one comment. The `bodymap` field's value is
`{"zones": [...], "pins": [{"view","x","y","zone"}]}` (zone auto-detected from
the pin); the frontend resolves the `diagram: "foot"` key against its diagram
registry (`lib/bodyDiagrams.ts`).

Only clubs that actually have a `podologia` department are touched (today just
Universidad de Chile). Run:

    docker compose exec backend python manage.py seed_podologia_template \\
        --create-if-missing --all-applicable-categories
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
                "diagram": "foot",
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
                "placeholder": "Procedimiento realizado, hallazgos, indicaciones…",
            },
        ],
    }


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
}


class Command(BaseCommand):
    help = "Create or refresh the 'Podología' template (bodymap zonas + comentario, flat)."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="podologia")
        parser.add_argument("--club", default=None, help="Limit to one club by name.")
        parser.add_argument("--name", default="Podología")
        parser.add_argument("--slug", default="podologia")
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

        touched = 0
        for club in clubs:
            dept = Department.objects.filter(
                club=club, slug=opts["department_slug"],
            ).first()
            if dept is None:
                # Podiatry isn't a department in every club — skip quietly.
                self.stdout.write(
                    f"[{club.name}] sin departamento '{opts['department_slug']}' — omitido."
                )
                continue

            template = ExamTemplate.objects.filter(
                department=dept, name=opts["name"],
            ).first()

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
            touched += 1

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

        if touched == 0:
            self.stdout.write(self.style.WARNING(
                "Ningún club tenía el departamento de podología — nada que hacer."
            ))
