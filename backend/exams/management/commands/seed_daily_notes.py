"""Seed (or refresh) the 'Notas diarias' template of every department.

Each submission is one daily entry: the doctor sets the date (defaults to today
in the form), an optional subject line, a free-form note body, and optionally
attaches documents (a report, an image, a PDF).

One name, one identity per department
-------------------------------------
The template is called **"Notas diarias" in every department** (it used to be
"Notas diarias Físico", "Notas diarias Médico"…): inside a department tab the
suffix only repeated the tab, and the screens that list exams across
departments already show the department next to it.

The NAME is therefore not an identity — eight templates share it — so a
template is found by its **slug**, `notas_diarias_<department slug>`, which is
unique club-wide and is what formulas, layouts and history hang from. Renaming
never touches the slug. The old suffixed name is still recognised, so a
department seeded before the rename is renamed in place instead of duplicated.

Categories are only ever ADDED (`--all-applicable-categories`): every category
that shows the department's tab gets the template. Nothing is detached, because
the per-player registration screen lists exams by applicability, not by tab.

Examples:

    # Stand up daily-notes templates in EVERY department of the club:
    docker compose exec backend python manage.py seed_daily_notes \
        --create-if-missing --all-applicable-categories

    # Single department only:
    docker compose exec backend python manage.py seed_daily_notes \
        --department-slug medico --create-if-missing --all-applicable-categories

Refresh-only (templates must already exist):

    docker compose exec backend python manage.py seed_daily_notes
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate

NAME = "Notas diarias"

DAILY_NOTES_SCHEMA: dict = {
    "fields": [
        {
            "key": "fecha", "label": "Fecha", "type": "date",
            "group": "Encabezado", "required": True,
        },
        {
            "key": "asunto", "label": "Asunto", "type": "text", "group": "Encabezado",
            "placeholder": "Ej: Sesión de entrenamiento, consulta, observación…",
        },
        {
            "key": "nota", "label": "Nota", "type": "text",
            "multiline": True, "rows": 8, "required": True,
            "placeholder": "Observaciones del día, intervenciones, hallazgos…",
        },
        {
            # Optional, and stored as attachments (AttachmentSource.EXAM_FIELD,
            # field_key="documentos"), not in result_data — so adding it to a
            # template that already has entries changes none of them.
            "key": "documentos", "label": "Documentos", "type": "file",
            "placeholder": "Informe, imagen o PDF relacionado con la nota.",
        },
    ]
}


class Command(BaseCommand):
    help = "Create or refresh the 'Notas diarias' template of each department."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default=None,
                            help="Optional department slug. When omitted, every department is processed.")
        parser.add_argument("--club", default=None,
                            help="Required when more than one club exists.")
        parser.add_argument("--name", default=None,
                            help="Override the template name. Only valid with --department-slug. "
                                 "Defaults to 'Notas diarias'.")
        parser.add_argument("--create-if-missing", action="store_true",
                            help="Create the template if it doesn't exist.")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="Attach to every category in the club whose departments list "
                                 "includes the target department (add-only: never detaches).")
        parser.add_argument("--unlock", action="store_true",
                            help="Clear is_locked. Use only if you accept that historical entries may not "
                                 "match the new schema.")

    def handle(self, *args, **options):
        department_slug = options["department_slug"]
        club_name = options["club"]
        explicit_name = options["name"]
        create = options["create_if_missing"]
        attach_all = options["all_applicable_categories"]
        unlock = options["unlock"]

        if explicit_name and not department_slug:
            raise CommandError("--name only makes sense together with --department-slug.")

        club = self._resolve_club(club_name)

        if department_slug:
            department = Department.objects.filter(club=club, slug=department_slug).first()
            if department is None:
                raise CommandError(
                    f"Department slug='{department_slug}' not found in club '{club.name}'. "
                    "Create it in Django Admin (Core → Departments → Add)."
                )
            departments = [department]
        else:
            departments = list(Department.objects.filter(club=club))
            if not departments:
                raise CommandError(
                    f"Club '{club.name}' has no departments yet. Create some in Django Admin first."
                )

        for department in departments:
            self._sync_department(
                department=department,
                club=club,
                name=explicit_name or NAME,
                create=create,
                attach_all=attach_all,
                unlock=unlock,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(departments)} department(s) processed."
        ))

    def _resolve_club(self, club_name: str | None) -> Club:
        if club_name:
            club = Club.objects.filter(name=club_name).first()
            if club is None:
                raise CommandError(f"Club '{club_name}' not found.")
            return club
        clubs = list(Club.objects.all()[:2])
        if len(clubs) == 0:
            raise CommandError("No clubs in the database. Create one in Django Admin first.")
        if len(clubs) > 1:
            raise CommandError("Multiple clubs exist; pass --club <name> to disambiguate.")
        return clubs[0]

    def _sync_department(self, *, department: Department, club: Club, name: str,
                         create: bool, attach_all: bool, unlock: bool) -> None:
        slug = slug_for(department)
        template = (
            ExamTemplate.objects.filter(department=department, slug=slug,
                                        is_active_version=True).first()
            # Seeded before slugs were set explicitly: found by its old name.
            or ExamTemplate.objects.filter(department=department, is_active_version=True,
                                           name=f"{NAME} {department.name}").first()
        )
        if template is None:
            if not create:
                self.stdout.write(self.style.WARNING(
                    f"Skipped '{department.name}': no '{NAME}' "
                    "(pass --create-if-missing to create it)."
                ))
                return
            template = self._create_template(name, slug, department)

        antes = template.name
        template.name = name
        template.config_schema = DAILY_NOTES_SCHEMA
        update_fields = ["name", "config_schema", "updated_at"]
        if unlock and template.is_locked:
            template.is_locked = False
            update_fields.append("is_locked")
        template.save(update_fields=update_fields)
        # The normalised field rows follow the JSON, as in every other seed.
        template.rebuild_template_fields()

        # Honor `--all-applicable-categories` on UPDATE too. Templates created
        # without categories on a prior run would otherwise stay detached and
        # `seed_fake_exams` would silently skip them. Add-only — see module doc.
        nuevas = 0
        if attach_all:
            faltan = (Category.objects.filter(club=club, departments=department)
                      .exclude(pk__in=template.applicable_categories.values("pk")))
            nuevas = faltan.count()
            template.applicable_categories.add(*faltan)

        renombre = f" (renamed from '{antes}')" if antes != name else ""
        self.stdout.write(self.style.SUCCESS(
            f"'{template.name}' · {department.name} · slug={template.slug}{renombre} · "
            f"+{nuevas} categories → {template.applicable_categories.count()}"
        ))

    @transaction.atomic
    def _create_template(self, name: str, slug: str, department: Department) -> ExamTemplate:
        # The slug is explicit: derived from the shared name it would collide
        # in every department after the first.
        template = ExamTemplate.objects.create(
            name=name, slug=slug, department=department, config_schema={},
        )
        self.stdout.write(self.style.NOTICE(f"Created '{name}' in {department.name}."))
        return template


def slug_for(department: Department) -> str:
    return f"notas_diarias_{department.slug.replace('-', '_')}"
