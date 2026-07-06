"""Create the "Fatiga Central (CFF)" template for the Psicosocial area.

Mirrors the club's "Histórico Fatiga Central" workbook: three flicker-fusion
readings (I1/I2/I3 in Hz), the session mean, a per-player CFF basal, and two
self-reported scales — PR (Percepción de Recuperación, TQR-style 1–10) and
EA (Estado de Ánimo, 1–10).

The basal is NOT re-measured every session: it comes from a dedicated basal
test. The form models that with the `actualizar_basal` checkbox — ticking it
makes THIS session's CFF media the player's new basal; leaving it off carries
the previous basal forward via the self-referencing formula
`[fatiga_central.cff_basal]` (the formula engine resolves a template's own
slug to the player's latest saved result). First-ever measurement with the box
off falls back to its own mean (Δ% = 0). Caveat: the carry-forward reads the
*latest* result by recorded_at, so back-dating an entry older than the newest
one picks up the current basal, not the historical one — fine in practice,
and the historical importer writes basals explicitly anyway.

Clinical bands follow the workbook's criteria: |Δ% vs basal| ≥ 5 → alerta,
Var % intra-sesión ≥ 5 → alerta, PR/EA rojo ≤3 · amarillo 4–6 · verde 7+.

    docker compose exec backend python manage.py seed_fatiga_central \\
        --create-if-missing --club "Universidad de Chile"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department


_BANDS_PR_EA = [
    {"max": 3.5, "label": "Bajo", "color": "#dc2626", "alert": True},
    {"min": 3.5, "max": 6.5, "label": "Vigilar", "color": "#f59e0b"},
    {"min": 6.5, "label": "Bueno", "color": "#16a34a"},
]
_BANDS_DELTA = [
    {"max": -5, "label": "Alerta (caída ≥5%)", "color": "#dc2626", "alert": True},
    {"min": -5, "max": 5, "label": "Estable", "color": "#16a34a"},
    {"min": 5, "label": "Alerta (alza ≥5%)", "color": "#dc2626", "alert": True},
]
_BANDS_VAR = [
    {"max": 5, "label": "Normal", "color": "#16a34a"},
    {"min": 5, "label": "Alta variabilidad", "color": "#dc2626", "alert": True},
]


def _hz(key: str, label: str) -> dict:
    return {
        "key": key, "label": label, "type": "number", "unit": "Hz",
        "group": "Test CFF (flicker)", "min": 10, "max": 60,
    }


def _scale(key: str, label: str) -> dict:
    return {
        "key": key, "label": label, "type": "number", "unit": "",
        "group": "Autorreporte", "chart_type": "line",
        "direction_of_good": "up", "min": 1, "max": 10,
        "reference_ranges": _BANDS_PR_EA,
    }


SCHEMA: dict = {
    "fields": [
        _hz("i1", "I1"),
        _hz("i2", "I2"),
        _hz("i3", "I3"),
        {
            "key": "actualizar_basal",
            "label": "Establecer como nuevo CFF basal (test basal)",
            "type": "boolean", "group": "Test CFF (flicker)",
        },
        {
            "key": "cff_mean", "label": "CFF media",
            "type": "calculated", "unit": "Hz",
            "group": "Test CFF (flicker)", "chart_type": "line",
            # round() only takes one argument in the formula engine.
            "formula": "round(([i1] + [i2] + [i3]) / 3 * 100) / 100",
        },
        {
            "key": "cff_basal", "label": "CFF basal",
            "type": "calculated", "unit": "Hz",
            "group": "Test CFF (flicker)", "chart_type": "line",
            # Checkbox on → this session's mean becomes the new basal.
            # Off → carry the previous result's basal forward; first-ever
            # measurement falls back to its own mean (Δ% = 0).
            "formula": (
                "[cff_mean] if coalesce([actualizar_basal], 0) "
                "else coalesce([fatiga_central.cff_basal], [cff_mean])"
            ),
        },
        {
            "key": "delta_basal_pct", "label": "Δ% vs basal",
            "type": "calculated", "unit": "%",
            "group": "Test CFF (flicker)", "chart_type": "line",
            "formula": "round(([cff_mean] / [cff_basal] - 1) * 10000) / 100",
            "reference_ranges": _BANDS_DELTA,
        },
        {
            "key": "var_intra_pct", "label": "Var % intra-sesión",
            "type": "calculated", "unit": "%",
            "group": "Test CFF (flicker)", "chart_type": "line",
            "formula": (
                "round((max([i1], [i2], [i3]) - min([i1], [i2], [i3])) "
                "/ [cff_mean] * 10000) / 100"
            ),
            "reference_ranges": _BANDS_VAR,
        },
        _scale("pr", "PR — Percepción de recuperación (TQR 1–10)"),
        _scale("ea", "EA — Estado de ánimo (1–10)"),
        {
            "key": "observaciones", "label": "Observaciones",
            "type": "text", "group": "Autorreporte",
            "multiline": True, "rows": 2,
        },
    ],
}

INPUT_CONFIG: dict = {
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": []},
}

NAME = "Fatiga Central (CFF)"
SLUG = "fatiga_central"


class Command(BaseCommand):
    help = "Create/refresh the Psicosocial 'Fatiga Central (CFF)' template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="psicosocial")
        parser.add_argument("--club", default=None)
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        from exams.models import ExamTemplate

        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No clubs found.")
        if clubs.count() > 1 and not opts["club"]:
            raise CommandError("Multiple clubs exist; pass --club <name>.")

        for club in clubs:
            dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
            if dept is None:
                raise CommandError(f"Department '{opts['department_slug']}' not in '{club.name}'.")

            template = ExamTemplate.objects.filter(department=dept, slug=SLUG).first()
            if template is None:
                template = ExamTemplate.objects.filter(department=dept, name=NAME).first()
            if template is None:
                if not opts["create_if_missing"]:
                    self.stdout.write(self.style.WARNING(
                        f"[{club.name}] '{NAME}' not found (pass --create-if-missing)."))
                    continue
                template = ExamTemplate(name=NAME, slug=SLUG, department=dept,
                                        config_schema=SCHEMA, input_config=INPUT_CONFIG)
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"[{club.name}] '{template.name}' is locked; pass --unlock."))
                    continue
                template.config_schema = SCHEMA
                template.input_config = INPUT_CONFIG
                if opts["unlock"]:
                    template.is_locked = False
                template.save()
                action = "refreshed"

            template.rebuild_template_fields()
            cats = Category.objects.filter(club=club, departments=dept)
            template.applicable_categories.set(cats)
            self.stdout.write(self.style.SUCCESS(
                f"[{club.name}] {action} '{template.name}' (slug={template.slug}); "
                f"categories: {', '.join(c.name for c in cats) or '(none)'}"
            ))
