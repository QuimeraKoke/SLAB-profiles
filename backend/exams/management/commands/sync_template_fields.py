"""Rebuild `TemplateField` rows from each template's `config_schema['fields']`.

Run this after a seed command (e.g. `seed_pentacompartimental`,
`seed_gps_match`) so the new template's JSON is reflected as inline-editable
rows in Django Admin.

Idempotent: replaces all rows for the targeted template(s).

Examples:

    # Sync every template
    docker compose exec backend python manage.py sync_template_fields --all

    # Sync one specific template by name
    docker compose exec backend python manage.py sync_template_fields \\
        --name "GPS – Rendimiento físico de partido"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from exams.models import ExamTemplate


class Command(BaseCommand):
    help = "Rebuild TemplateField rows from each ExamTemplate's config_schema JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", action="append", default=None,
            help="Template name to sync (repeatable). Mutually exclusive with --all.",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Sync every template in the system.",
        )

    def handle(self, *args, **opts):
        names: list[str] | None = opts["name"]
        do_all: bool = opts["all"]

        if not names and not do_all:
            raise CommandError("Pasa --all o al menos un --name <plantilla>.")
        if names and do_all:
            raise CommandError("--all y --name son mutuamente excluyentes.")

        qs = ExamTemplate.objects.all()
        if names:
            qs = qs.filter(name__in=names)
            if not qs.exists():
                raise CommandError(f"No se encontraron plantillas con nombre en: {names}")

        for template in qs:
            template.rebuild_template_fields()
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {template.name}  ({template.template_fields.count()} campos)"
            ))
