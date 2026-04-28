"""Bootstrap a default Nutricional dashboard layout per category.

Mirrors the designer's mockup:
  - Section 1 (no header): Comparison table (last 3 takes) + Line chart with selector
  - Section 2 'Fraccionamiento 5 masas': donut per result, one slice per body mass
  - Section 3 'Análisis M. adiposa y M. muscular': grouped bar chart

Run:

    docker compose exec backend python manage.py seed_nutricional_layout \\
        --department-slug nutricional --all-applicable-categories

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


# Color palette aligned with the mockup's body-composition donut/bars.
MASS_COLORS = {
    "masa_muscular": "#3b82f6",  # blue
    "masa_adiposa":  "#f97316",  # orange
    "masa_osea":     "#10b981",  # green
    "masa_residual": "#f59e0b",  # amber
    "masa_piel":     "#a855f7",  # purple
}


def _layout_spec(template: ExamTemplate) -> dict:
    """Returns the section/widget tree for a Pentacompartimental-fed layout."""
    schema_keys = {
        f["key"] for f in (template.config_schema or {}).get("fields", []) if f.get("key")
    }

    # Build mass-key list robust to schema gaps.
    mass_keys = [k for k in MASS_COLORS if k in schema_keys]
    mass_colors = [MASS_COLORS[k] for k in mass_keys]

    comparison_keys = [
        k for k in [
            "peso", "talla", "masa_adiposa", "masa_muscular",
            "masa_osea", "masa_piel", "masa_residual", "suma_pliegues",
        ]
        if k in schema_keys
    ]

    line_selector_keys = [
        k for k in [
            "peso", "imc", "grasa_faulkner",
            "masa_adiposa", "masa_muscular", "masa_osea",
            "masa_residual", "masa_piel", "suma_pliegues",
        ]
        if k in schema_keys
    ]

    grouped_bar_keys = [
        k for k in ["masa_adiposa", "masa_muscular"] if k in schema_keys
    ]

    return {
        "sections": [
            {
                "title": "",
                "is_collapsible": False,
                "widgets": [
                    {
                        "chart_type": ChartType.COMPARISON_TABLE,
                        "title": "Evolución antropométrica — últimas 3 tomas",
                        "column_span": 6,
                        "sources": [
                            {
                                "field_keys": comparison_keys,
                                "aggregation": Aggregation.LAST_N,
                                "aggregation_param": 3,
                            },
                        ],
                    },
                    {
                        "chart_type": ChartType.LINE_WITH_SELECTOR,
                        "title": "Evolución en el tiempo",
                        "column_span": 6,
                        "sources": [
                            {
                                "field_keys": line_selector_keys,
                                "aggregation": Aggregation.ALL,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "Fraccionamiento 5 masas",
                "is_collapsible": True,
                "widgets": [
                    {
                        "chart_type": ChartType.MULTI_LINE,
                        "title": "Evolución de las 5 masas",
                        "column_span": 12,
                        "display_config": {"colors": mass_colors},
                        "sources": [
                            {
                                "field_keys": mass_keys,
                                "aggregation": Aggregation.ALL,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "Análisis M. adiposa y M. muscular",
                "is_collapsible": True,
                "widgets": [
                    {
                        "chart_type": ChartType.GROUPED_BAR,
                        "title": "En kilogramos",
                        "column_span": 12,
                        "display_config": {
                            "colors": [MASS_COLORS.get(k, "") for k in grouped_bar_keys],
                        },
                        "sources": [
                            {
                                "field_keys": grouped_bar_keys,
                                "aggregation": Aggregation.LAST_N,
                                "aggregation_param": 3,
                            },
                        ],
                    },
                ],
            },
        ],
    }


class Command(BaseCommand):
    help = (
        "Bootstrap a default Nutricional dashboard layout (table + line + donut + bar) "
        "for every applicable category in the club."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--department-slug",
            default="nutricional",
            help="Department slug to seed the layout under (default: 'nutricional').",
        )
        parser.add_argument(
            "--template-name",
            default="Pentacompartimental",
            help="Name of the source ExamTemplate (default: 'Pentacompartimental').",
        )
        parser.add_argument(
            "--club",
            default=None,
            help="Scope to a single club by name. Required if multiple clubs exist.",
        )
        parser.add_argument(
            "--all-applicable-categories",
            action="store_true",
            help="Seed a layout for every category that opted in to the department.",
        )
        parser.add_argument(
            "--category-name",
            default=None,
            help="Seed a layout for a single category in the resolved club.",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Leave existing (department, category) layouts untouched. "
                 "Default behavior wipes and rebuilds them.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        department_slug = options["department_slug"]
        template_name = options["template_name"]
        club_name = options["club"]
        attach_all = options["all_applicable_categories"]
        category_name = options["category_name"]
        skip_existing = options["skip_existing"]

        # Resolve club.
        if club_name:
            club = Club.objects.filter(name=club_name).first()
            if club is None:
                raise CommandError(f"Club '{club_name}' not found.")
        else:
            clubs = list(Club.objects.all()[:2])
            if not clubs:
                raise CommandError("No clubs in the database. Create one in Django Admin first.")
            if len(clubs) > 1:
                raise CommandError("Multiple clubs exist; pass --club <name> to disambiguate.")
            club = clubs[0]

        # Resolve department.
        department = Department.objects.filter(club=club, slug=department_slug).first()
        if department is None:
            raise CommandError(
                f"Department slug='{department_slug}' not found in club '{club.name}'. "
                "Create it in Django Admin first."
            )

        # Resolve template.
        template = ExamTemplate.objects.filter(
            name=template_name, department=department
        ).first()
        if template is None:
            raise CommandError(
                f"ExamTemplate '{template_name}' not found in department "
                f"'{department.name}'. Run seed_pentacompartimental "
                "--create-if-missing first."
            )

        # Resolve categories.
        if attach_all and category_name:
            raise CommandError("Pass either --all-applicable-categories or --category-name, not both.")
        if attach_all:
            categories = list(
                Category.objects.filter(club=club, departments=department)
            )
        elif category_name:
            cat = Category.objects.filter(club=club, name=category_name).first()
            if cat is None:
                raise CommandError(
                    f"Category '{category_name}' not found in club '{club.name}'."
                )
            if not cat.departments.filter(pk=department.pk).exists():
                raise CommandError(
                    f"Category '{cat.name}' has not opted in to department "
                    f"'{department.name}'."
                )
            categories = [cat]
        else:
            raise CommandError(
                "Pass --all-applicable-categories or --category-name <name>."
            )

        if not categories:
            self.stdout.write(self.style.WARNING(
                f"No categories opted into department '{department.name}' yet. "
                "Configure categories in Django Admin first."
            ))
            return

        spec = _layout_spec(template)

        for category in categories:
            existing = DepartmentLayout.objects.filter(
                department=department, category=category
            ).first()

            if existing and skip_existing:
                self.stdout.write(self.style.NOTICE(
                    f"Skipping existing layout for {category.name}."
                ))
                continue

            if existing:
                # Wipe sections (cascade kills widgets + sources).
                existing.sections.all().delete()
                layout = existing
                action = "Rebuilt"
            else:
                layout = DepartmentLayout.objects.create(
                    department=department,
                    category=category,
                    name="Nutricional default",
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
                            template=template,
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
            f"Done. Processed {len(categories)} categor"
            f"{'y' if len(categories) == 1 else 'ies'}."
        ))
