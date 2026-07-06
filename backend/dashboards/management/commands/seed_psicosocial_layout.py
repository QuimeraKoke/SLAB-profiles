"""Bootstrap the default Psicosocial dashboard layout per category.

Two chart widgets over the "Fatiga Central (CFF)" template:
  - Section 1 (no header): CFF media vs basal (multi-line) +
    PR / EA self-report scales (multi-line), side by side.
  - Section 2 'Notas diarias': activity log of the Notas diarias
    Psicosocial template — creating this layout replaces the legacy
    template grid on the Psicosocial tab, so the notes history keeps a
    visible surface.

Run:

    docker compose exec backend python manage.py seed_psicosocial_layout \\
        --club "Universidad de Chile" --all-applicable-categories

Re-running is idempotent: existing layouts for the targeted (dept, category)
pairs are wiped and rebuilt. Pass --skip-existing to leave them alone.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from dashboards.models import (
    Aggregation,
    ChartType,
    DepartmentLayout,
    LayoutSection,
    Widget,
    WidgetDataSource,
)
from exams.models import ExamTemplate


def _layout_spec(cff_template: ExamTemplate, notes_template: ExamTemplate | None) -> dict:
    schema_keys = {
        f["key"] for f in (cff_template.config_schema or {}).get("fields", []) if f.get("key")
    }
    cff_keys = [k for k in ("cff_mean", "cff_basal") if k in schema_keys]
    scale_keys = [k for k in ("pr", "ea") if k in schema_keys]

    sections = [
        {
            "title": "",
            "is_collapsible": False,
            "widgets": [
                {
                    "chart_type": ChartType.MULTI_LINE,
                    "title": "Fatiga central — CFF media vs basal",
                    "column_span": 6,
                    "display_config": {"colors": ["#3b82f6", "#94a3b8"]},
                    "template": cff_template,
                    "sources": [
                        {"field_keys": cff_keys, "aggregation": Aggregation.ALL},
                    ],
                },
                {
                    "chart_type": ChartType.MULTI_LINE,
                    "title": "Recuperación (PR) y estado de ánimo (EA)",
                    "column_span": 6,
                    "display_config": {
                        "colors": ["#10b981", "#f59e0b"],
                        "y_axis_title": "Escala 1–10",
                    },
                    "template": cff_template,
                    "sources": [
                        {"field_keys": scale_keys, "aggregation": Aggregation.ALL},
                    ],
                },
            ],
        },
    ]
    if notes_template is not None:
        sections.append({
            "title": "Notas diarias",
            "is_collapsible": True,
            "widgets": [
                {
                    "chart_type": ChartType.ACTIVITY_LOG,
                    "title": "Últimas notas",
                    "column_span": 12,
                    "template": notes_template,
                    "sources": [
                        {
                            "field_keys": ["asunto", "nota"],
                            "aggregation": Aggregation.LAST_N,
                            "aggregation_param": 10,
                        },
                    ],
                },
            ],
        })
    return {"sections": sections}


class Command(BaseCommand):
    help = (
        "Bootstrap the default Psicosocial dashboard layout (CFF + PR/EA charts, "
        "daily-notes log) for the targeted categories."
    )

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="psicosocial")
        parser.add_argument(
            "--template-name", default="Fatiga Central (CFF)",
            help="Name of the CFF ExamTemplate (default: 'Fatiga Central (CFF)').",
        )
        parser.add_argument("--club", default=None,
                            help="Scope to a single club by name. Required if multiple clubs exist.")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="Seed a layout for every category that opted in to the department.")
        parser.add_argument("--category-name", default=None,
                            help="Seed a layout for a single category in the resolved club.")
        parser.add_argument("--skip-existing", action="store_true",
                            help="Leave existing (department, category) layouts untouched. "
                                 "Default behavior wipes and rebuilds them.")

    @transaction.atomic
    def handle(self, *args, **options):
        club_name = options["club"]
        if club_name:
            club = Club.objects.filter(name=club_name).first()
            if club is None:
                raise CommandError(f"Club '{club_name}' not found.")
        else:
            clubs = list(Club.objects.all()[:2])
            if not clubs:
                raise CommandError("No clubs in the database.")
            if len(clubs) > 1:
                raise CommandError("Multiple clubs exist; pass --club <name> to disambiguate.")
            club = clubs[0]

        department = Department.objects.filter(club=club, slug=options["department_slug"]).first()
        if department is None:
            raise CommandError(
                f"Department slug='{options['department_slug']}' not found in club '{club.name}'."
            )

        cff_template = ExamTemplate.objects.filter(
            name=options["template_name"], department=department, is_active_version=True,
        ).first()
        if cff_template is None:
            raise CommandError(
                f"ExamTemplate '{options['template_name']}' not found in department "
                f"'{department.name}'. Run seed_fatiga_central --create-if-missing first."
            )
        notes_template = ExamTemplate.objects.filter(
            slug="notas_diarias_psicosocial", department=department, is_active_version=True,
        ).first()

        if options["all_applicable_categories"] and options["category_name"]:
            raise CommandError("Pass either --all-applicable-categories or --category-name, not both.")
        if options["all_applicable_categories"]:
            categories = list(Category.objects.filter(club=club, departments=department))
        elif options["category_name"]:
            cat = Category.objects.filter(club=club, name=options["category_name"]).first()
            if cat is None:
                raise CommandError(f"Category '{options['category_name']}' not found in club '{club.name}'.")
            if not cat.departments.filter(pk=department.pk).exists():
                raise CommandError(
                    f"Category '{cat.name}' has not opted in to department '{department.name}'."
                )
            categories = [cat]
        else:
            raise CommandError("Pass --all-applicable-categories or --category-name <name>.")

        if not categories:
            self.stdout.write(self.style.WARNING(
                f"No categories opted into department '{department.name}' yet."
            ))
            return

        spec = _layout_spec(cff_template, notes_template)

        for category in categories:
            existing = DepartmentLayout.objects.filter(
                department=department, category=category
            ).first()

            if existing and options["skip_existing"]:
                self.stdout.write(self.style.NOTICE(f"Skipping existing layout for {category.name}."))
                continue

            if existing:
                existing.sections.all().delete()
                layout = existing
                action = "Rebuilt"
            else:
                layout = DepartmentLayout.objects.create(
                    department=department,
                    category=category,
                    name="Psicosocial default",
                    is_active=True,
                )
                action = "Created"

            for section_index, section_spec in enumerate(spec["sections"]):
                section = LayoutSection.objects.create(
                    layout=layout,
                    title=section_spec["title"],
                    is_collapsible=section_spec.get("is_collapsible", True),
                    default_collapsed=section_spec.get("default_collapsed", False),
                    sort_order=section_index,
                )
                for widget_index, widget_spec in enumerate(section_spec["widgets"]):
                    widget = Widget.objects.create(
                        section=section,
                        chart_type=widget_spec["chart_type"],
                        title=widget_spec["title"],
                        description=widget_spec.get("description", ""),
                        column_span=widget_spec.get("column_span", 12),
                        display_config=widget_spec.get("display_config", {}),
                        sort_order=widget_index,
                    )
                    for src_index, src_spec in enumerate(widget_spec["sources"]):
                        WidgetDataSource.objects.create(
                            widget=widget,
                            template=widget_spec["template"],
                            field_keys=src_spec["field_keys"],
                            aggregation=src_spec["aggregation"],
                            aggregation_param=src_spec.get("aggregation_param", 3),
                            label=src_spec.get("label", ""),
                            color=src_spec.get("color", ""),
                            sort_order=src_index,
                        )

            self.stdout.write(self.style.SUCCESS(
                f"{action} layout for {department.name} → {category.name} "
                f"({len(spec['sections'])} sections)."
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Done. Processed {len(categories)} categor{'y' if len(categories) == 1 else 'ies'}."
        ))
