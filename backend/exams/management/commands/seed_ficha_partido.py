"""Create / overwrite the "Ficha oficial de partido" template (Táctico).

The federation's official per-player match record, as published by COMET
(Analyticom) — the platform ANFP runs. Filled automatically by
`sync_comet`; every field here is something COMET states authoritatively.

Deliberately SEPARATE from `rendimiento_de_partido`, which is the coaching
staff's own subjective sheet (rating, remates, faltas, notas). The two overlap
on minutes/goals/cards on purpose: one is the official record, the other is the
analyst's count, and being able to contrast them is the point. Nothing in this
template is hand-entered in normal operation.

What COMET does NOT provide, so is absent here: any physical/GPS metric
(distance, sprints, velocity) — that comes from Catapult — and outfield
positions, which the ANFP feed leaves blank for everyone but the goalkeeper.

    docker compose exec backend python manage.py seed_ficha_partido \\
        --create-if-missing --department-slug tactico \\
        --all-applicable-categories --club "Universidad de Chile"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate

SLUG = "ficha_partido"
NAME = "Ficha oficial de partido"

G_PART = "Participación"
G_OFENSIVA = "Ofensiva"
G_DISCIPLINA = "Disciplina"

FIELDS: list[dict] = [
    # ── Participación ────────────────────────────────────────────────────
    {
        "key": "titular", "label": "Titular", "type": "boolean",
        "group": G_PART,
        "help_text": "Estuvo en la alineación inicial (COMET: starting).",
    },
    {
        "key": "minutos", "label": "Minutos jugados", "type": "number",
        "unit": "min", "group": G_PART, "min": 0, "max": 120,
        "chart_type": "line", "direction_of_good": "up",
        "help_text": (
            "Derivado de la alineación + sustituciones: los titulares parten en 0 "
            "y los ingresos desde su minuto. Tope 90 (el registro oficial no "
            "cuenta tiempo añadido)."
        ),
    },
    {
        "key": "min_ingreso", "label": "Minuto de ingreso", "type": "number",
        "unit": "min", "group": G_PART, "min": 0, "max": 120,
        "help_text": "Vacío si fue titular.",
    },
    {
        "key": "min_salida", "label": "Minuto de salida", "type": "number",
        "unit": "min", "group": G_PART, "min": 0, "max": 120,
        "help_text": "Vacío si terminó el partido en cancha.",
    },
    {
        "key": "dorsal", "label": "Dorsal", "type": "number",
        "group": G_PART, "min": 1, "max": 99,
    },
    {
        "key": "capitan", "label": "Capitán", "type": "boolean",
        "group": G_PART,
    },
    {
        "key": "posicion_comet", "label": "Posición (COMET)", "type": "text",
        "group": G_PART,
        "help_text": (
            "Tal como la informa la federación. Hoy sólo viene poblada para el "
            "arquero (G); el resto llega vacía."
        ),
    },
    # ── Ofensiva ─────────────────────────────────────────────────────────
    {
        "key": "goles", "label": "Goles", "type": "number",
        "group": G_OFENSIVA, "min": 0, "max": 20,
        "chart_type": "bar", "direction_of_good": "up",
    },
    {
        "key": "asistencias", "label": "Asistencias", "type": "number",
        "group": G_OFENSIVA, "min": 0, "max": 20,
        "chart_type": "bar", "direction_of_good": "up",
    },
    {
        "key": "penales", "label": "Penales convertidos", "type": "number",
        "group": G_OFENSIVA, "min": 0, "max": 20,
    },
    {
        "key": "autogoles", "label": "Autogoles", "type": "number",
        "group": G_OFENSIVA, "min": 0, "max": 20, "direction_of_good": "down",
    },
    # ── Disciplina ───────────────────────────────────────────────────────
    {
        "key": "amarillas", "label": "Tarjetas amarillas", "type": "number",
        "group": G_DISCIPLINA, "min": 0, "max": 2, "direction_of_good": "down",
    },
    {
        "key": "rojas", "label": "Tarjetas rojas", "type": "number",
        "group": G_DISCIPLINA, "min": 0, "max": 1, "direction_of_good": "down",
    },
]

INPUT_CONFIG = {
    # team_table is the natural shape (a squad sheet per match) and single
    # stays available for a manual correction. No bulk_ingest: the data arrives
    # from the API, not a spreadsheet.
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "modifiers": {"prefill_from_last": False},
    # The match IS the record's identity, so the form asks for it and the
    # backend derives recorded_at from the event's kickoff.
    "allow_event_link": True,
    "team_table": {"include_inactive": False},
}

CONFIG_SCHEMA = {"fields": FIELDS}


class Command(BaseCommand):
    help = "Create/overwrite the 'Ficha oficial de partido' template (Táctico)."

    def add_arguments(self, parser):
        parser.add_argument("--club", help="Club name (exact). Omit → every club.")
        parser.add_argument("--department-slug", default="tactico")
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true")
        parser.add_argument("--unlock", action="store_true",
                            help="Overwrite even if the template is locked.")

    @transaction.atomic
    def handle(self, *args, **opts):
        clubs = (
            Club.objects.filter(name=opts["club"]) if opts["club"]
            else Club.objects.all()
        )
        if not clubs.exists():
            raise CommandError(f"No club matched {opts['club']!r}.")

        touched = 0
        for club in clubs:
            department = Department.objects.filter(
                club=club, slug=opts["department_slug"],
            ).first()
            if department is None:
                self.stdout.write(self.style.WARNING(
                    f"· {club.name}: sin departamento '{opts['department_slug']}' — omitido."
                ))
                continue

            template = ExamTemplate.objects.filter(
                slug=SLUG, department__club=club, is_active_version=True,
            ).first()
            if template is None:
                if not opts["create_if_missing"]:
                    self.stdout.write(self.style.WARNING(
                        f"· {club.name}: plantilla '{SLUG}' no existe "
                        "(pasá --create-if-missing)."
                    ))
                    continue
                template = ExamTemplate(
                    name=NAME, slug=SLUG, department=department,
                )
            elif template.is_locked and not opts["unlock"]:
                self.stdout.write(self.style.WARNING(
                    f"· {club.name}: '{template.name}' está bloqueada — "
                    "pasá --unlock para sobrescribir."
                ))
                continue
            elif opts["unlock"]:
                template.is_locked = False

            template.name = NAME
            template.department = department
            template.config_schema = CONFIG_SCHEMA
            template.input_config = INPUT_CONFIG
            # Every row belongs to a match; the event supplies recorded_at.
            template.link_to_match = True
            template.save()
            template.rebuild_template_fields()

            if opts["all_applicable_categories"]:
                cats = Category.objects.filter(club=club, departments=department)
                template.applicable_categories.set(cats)

            touched += 1
            self.stdout.write(self.style.SUCCESS(
                f"· {club.name}: '{template.name}' ({SLUG}) — "
                f"{len(FIELDS)} campos, "
                f"{template.applicable_categories.count()} categorías."
            ))

        if not touched:
            raise CommandError("No se actualizó ninguna plantilla.")
        self.stdout.write(self.style.SUCCESS(f"\nListo. {touched} plantilla(s)."))
