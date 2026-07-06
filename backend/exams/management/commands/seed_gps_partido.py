"""Create / overwrite the per-session MATCH GPS template ("GPS Partido").

The match half of the live GPS pair: every result is one player's totals for
one match, linked to its Event (`link_to_match`). Field keys are identical to
the training sibling `gps_sesion` (see `seed_gps_session`) so load consumers
(ACWR, weekly load, match references) read both without key translation.

Written by the match side of `/gps-sessions/upload` and by
`import_gps_sessions` for season backfills. Existing clubs coming from the
combined `gps_sesion` template are migrated by `split_gps_partido`.

Run:

    docker compose exec backend python manage.py seed_gps_partido \\
        --create-if-missing --department-slug fisico \\
        --all-applicable-categories
"""
from __future__ import annotations

import copy

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate
from exams.management.commands.seed_gps_session import CONFIG_SCHEMA as _SESSION_SCHEMA


def build_config_schema() -> dict:
    """The training schema with match-only session types (and no RPE —
    subjective effort is logged on trainings, not matches)."""
    schema = copy.deepcopy(_SESSION_SCHEMA)
    schema["fields"] = [f for f in schema["fields"] if f["key"] != "rpe"]
    for field in schema["fields"]:
        if field["key"] == "tipo_sesion":
            field["options"] = ["partido", "amistoso"]
            field["option_labels"] = {"partido": "Partido", "amistoso": "Amistoso"}
    return schema


INPUT_CONFIG: dict = {
    # Manual-entry fallback only — matches normally arrive via the
    # /gps-sessions/upload endpoint (kind="match").
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "modifiers": {"prefill_from_last": False},
    "team_table": {
        "shared_fields": ["fecha", "sesion", "tipo_sesion"],
    },
}


class Command(BaseCommand):
    help = "Create / refresh the match GPS template (Físico, one row per player per match)."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="fisico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="GPS Partido")
        parser.add_argument("--slug", default="gps_partido")
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

        config_schema = build_config_schema()
        for club in clubs:
            dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
            if dept is None:
                raise CommandError(
                    f"Department '{opts['department_slug']}' not found in club '{club.name}'."
                )

            template = ExamTemplate.objects.filter(department=dept, slug=opts["slug"]).first()
            if template is None:
                if not opts["create_if_missing"]:
                    raise CommandError(
                        f"Template '{opts['slug']}' not found in {dept}; "
                        f"pass --create-if-missing to create it."
                    )
                template = ExamTemplate(
                    name=opts["name"],
                    slug=opts["slug"],
                    department=dept,
                    config_schema=config_schema,
                    input_config=INPUT_CONFIG,
                    # Every match session carries an Event FK; the selector is
                    # surfaced for manual entry too.
                    link_to_match=True,
                )
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"Template '{template.name}' is locked; pass --unlock to refresh."
                    ))
                    continue
                template.name = opts["name"]
                template.config_schema = config_schema
                template.input_config = INPUT_CONFIG
                template.link_to_match = True
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
