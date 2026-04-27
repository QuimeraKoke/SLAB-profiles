"""Overwrite the Pentacompartimental template's config_schema.

Run with:

    docker compose exec backend python manage.py seed_pentacompartimental

By default it updates every ExamTemplate named "Pentacompartimental". Pass
--name to target a different label, --club to scope to a single club, or
--unlock to clear the is_locked flag (use with care — only meaningful for
templates that already have results).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate

PENTACOMPARTIMENTAL_SCHEMA: dict = {
    "fields": [
        {"key": "peso",                  "label": "Peso",                   "type": "number", "unit": "kg", "group": "Datos básicos", "required": True},
        {"key": "talla",                 "label": "Talla",                  "type": "number", "unit": "cm", "group": "Datos básicos", "required": True},
        {"key": "sexo",                  "label": "Sexo (1=M, 0=F)",        "type": "number",               "group": "Datos básicos", "required": True},

        {"key": "humero",                "label": "Húmero",                 "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "femur",                 "label": "Fémur",                  "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "biestiloideo",          "label": "Biestiloideo (Muñeca)",  "type": "number", "unit": "cm", "group": "Diámetros"},

        {"key": "torax",                 "label": "Tórax",                  "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "cintura",               "label": "Cintura",                "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "caderas",               "label": "Caderas",                "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "perim_brazo_relajado",  "label": "Brazo Relajado",         "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "muslo_gluteo",          "label": "Muslo 1cm glúteo",       "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "muslo_medio",           "label": "Muslo medio",            "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "pierna_perim",          "label": "Pierna",                 "type": "number", "unit": "cm", "group": "Perímetros"},

        {"key": "pliegue_triceps",       "label": "Tríceps",                "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_subescapular",  "label": "Subescapular",           "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_supra",         "label": "Supraespinal",           "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_abdomen",       "label": "Abdominal",              "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_muslo",         "label": "Muslo",                  "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_pierna",        "label": "Pierna",                 "type": "number", "unit": "mm", "group": "Pliegues"},

        {"key": "envergadura",           "label": "Envergadura",            "type": "number", "unit": "cm", "group": "Otras medidas (opcional)"},
        {"key": "long_brazo",            "label": "Long. brazo",            "type": "number", "unit": "cm", "group": "Otras medidas (opcional)"},
        {"key": "long_pierna",           "label": "Long. pierna",           "type": "number", "unit": "cm", "group": "Otras medidas (opcional)"},

        {
            "key": "imc", "label": "IMC", "type": "calculated", "unit": "kg/m²",
            "formula": "[peso] / (([talla] / 100) ** 2)",
            "chart_type": "line",
        },
        {
            "key": "suma_pliegues", "label": "Σ 4 pliegues", "type": "calculated", "unit": "mm",
            "formula": "[pliegue_supra] + [pliegue_abdomen] + [pliegue_muslo] + [pliegue_pierna]",
            "chart_type": "line",
        },
        {
            "key": "grasa_faulkner", "label": "% Grasa (Faulkner)", "type": "calculated", "unit": "%",
            "formula": "0.153 * ([pliegue_supra] + [pliegue_abdomen] + [pliegue_muslo] + [pliegue_pierna]) + 5.783",
            "chart_type": "line",
        },
        {
            "key": "masa_piel", "label": "Masa Piel", "type": "calculated", "unit": "kg",
            "formula": "(([peso] ** 0.425) * ([talla] ** 0.725) * 71.84 / 10000) * 2.0",
            "chart_type": "line",
        },
        {
            "key": "masa_osea", "label": "Masa Ósea", "type": "calculated", "unit": "kg",
            "formula": "3.02 * ((([talla]/100)**2) * ([humero]/100) * ([femur]/100) * 400)**0.712",
            "chart_type": "line",
        },
        {
            "key": "masa_adiposa", "label": "Masa Adiposa", "type": "calculated", "unit": "kg",
            "formula": "(([pliegue_triceps] + [pliegue_subescapular] + [pliegue_supra] + [pliegue_abdomen] + [pliegue_muslo] + [pliegue_pierna]) * 0.145) + 0.64",
            "chart_type": "line",
        },
        {
            "key": "masa_residual", "label": "Masa Residual", "type": "calculated", "unit": "kg",
            "formula": "[peso] * (0.241 if [sexo] == 1 else 0.209)",
            "chart_type": "line",
        },
        {
            "key": "masa_muscular", "label": "Masa Muscular", "type": "calculated", "unit": "kg",
            "formula": "[peso] - ([masa_adiposa] + [masa_osea] + [masa_piel] + [masa_residual])",
            "chart_type": "line",
        },
    ]
}


class Command(BaseCommand):
    help = "Overwrite the config_schema of the Pentacompartimental ExamTemplate(s)."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Pentacompartimental",
                            help="Template name to match (default: 'Pentacompartimental').")
        parser.add_argument("--club", default=None,
                            help="Scope to templates whose department belongs to a club with this name. "
                                 "Required for --create-if-missing if more than one club exists.")
        parser.add_argument("--department-slug", default=None,
                            help="Department slug (e.g. 'nutricional'). Required for --create-if-missing.")
        parser.add_argument("--create-if-missing", action="store_true",
                            help="Create the template if no match exists. Requires --department-slug "
                                 "and --club (when multi-club).")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="When creating, attach to every category in the club that has the "
                                 "given department enabled. Default: attach to none — set them in admin.")
        parser.add_argument("--unlock", action="store_true",
                            help="Also clear is_locked. Use only if you accept that historical results may not "
                                 "match the new schema.")

    def handle(self, *args, **options):
        name = options["name"]
        club_name = options["club"]
        department_slug = options["department_slug"]
        create_if_missing = options["create_if_missing"]
        attach_all = options["all_applicable_categories"]
        unlock = options["unlock"]

        qs = ExamTemplate.objects.filter(name=name).select_related("department__club")
        if club_name:
            qs = qs.filter(department__club__name=club_name)

        templates = list(qs)

        if not templates and create_if_missing:
            templates = [self._create_template(name, club_name, department_slug, attach_all)]

        if not templates:
            raise CommandError(
                f"No ExamTemplate found with name='{name}'"
                + (f" in club='{club_name}'" if club_name else "")
                + ". Either create the shell in Django Admin "
                  "(Exams → Exam templates → Add) and re-run, or pass "
                  "--create-if-missing --department-slug <slug> [--club <name>]."
            )

        for template in templates:
            template.config_schema = PENTACOMPARTIMENTAL_SCHEMA
            update_fields = ["config_schema", "updated_at"]
            if unlock and template.is_locked:
                template.is_locked = False
                update_fields.append("is_locked")
            template.save(update_fields=update_fields)
            self.stdout.write(self.style.SUCCESS(
                f"Updated '{template.name}' (club: {template.department.club.name}, "
                f"department: {template.department.name})"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(templates)} template(s) updated."
        ))

    @transaction.atomic
    def _create_template(self, name: str, club_name: str | None, department_slug: str | None,
                         attach_all: bool) -> ExamTemplate:
        if not department_slug:
            raise CommandError("--create-if-missing requires --department-slug.")

        # Resolve the club. If only one exists and --club wasn't given, use it.
        if club_name:
            club = Club.objects.filter(name=club_name).first()
            if club is None:
                raise CommandError(f"Club '{club_name}' not found.")
        else:
            clubs = list(Club.objects.all()[:2])
            if len(clubs) == 0:
                raise CommandError("No clubs in the database. Create one in Django Admin first.")
            if len(clubs) > 1:
                raise CommandError("Multiple clubs exist; pass --club <name> to disambiguate.")
            club = clubs[0]

        department = Department.objects.filter(club=club, slug=department_slug).first()
        if department is None:
            raise CommandError(
                f"Department slug='{department_slug}' not found in club '{club.name}'. "
                "Create it in Django Admin (Core → Departments → Add)."
            )

        template = ExamTemplate.objects.create(
            name=name,
            department=department,
            config_schema={},
        )

        if attach_all:
            categories = Category.objects.filter(club=club, departments=department)
            template.applicable_categories.set(categories)
            self.stdout.write(self.style.NOTICE(
                f"Attached '{template.name}' to {categories.count()} categories "
                f"({', '.join(c.name for c in categories) or 'none'})."
            ))
        else:
            self.stdout.write(self.style.NOTICE(
                f"Created '{template.name}' with no applicable_categories — set them "
                "in Django Admin or re-run with --all-applicable-categories."
            ))

        return template
