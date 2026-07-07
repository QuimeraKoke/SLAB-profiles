"""Create the three small clinical-indicator templates for Médico:
CK, Densidad urinaria, and CMJ.

These were originally authored ad-hoc via Django Admin; this command
makes them reproducible so a fresh DB boots into the full demo state.

Run:

    docker compose exec backend python manage.py seed_medico_indicators \\
        --create-if-missing --department-slug medico \\
        --all-applicable-categories --club "Universidad de Chile"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


# --- CK (creatine kinase) — single numeric reading per take ---
CK_SCHEMA: dict = {
    "fields": [
        {"key": "fecha", "label": "Fecha", "type": "date", "group": "Toma", "required": True},
        {
            "key": "valor", "label": "CK", "type": "number",
            "unit": "U/L", "group": "Toma", "chart_type": "line",
        },
        {
            "key": "nota", "label": "Notas", "type": "text",
            "multiline": True, "rows": 2, "group": "Toma",
        },
    ],
}

CK_INPUT_CONFIG: dict = {
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": ["fecha"]},
}


# --- Densidad urinaria (formerly "Hidratación") — urine specific gravity ---
DENSIDAD_URINARIA_SCHEMA: dict = {
    "fields": [
        {"key": "fecha", "label": "Fecha", "type": "date", "group": "Toma", "required": True},
        {
            "key": "densidad_urinaria", "label": "Densidad urinaria",
            "type": "number", "group": "Toma", "chart_type": "line",
        },
        {
            "key": "notas", "label": "Notas", "type": "text",
            "multiline": True, "rows": 2, "group": "Toma",
        },
    ],
}

DENSIDAD_URINARIA_INPUT_CONFIG: dict = {
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": ["fecha"]},
}


# --- CMJ (countermovement jump) — force-plate jump profile ---
# Redefined 2026-07-07 (user spec): jump height + peak power/body mass +
# RSI-modified + eccentric peak velocity. Height keeps the club's reference
# bands (G. Tapia): 40–45 cm media; alto = mejor.
CMJ_SCHEMA: dict = {
    "fields": [
        {
            "key": "jump_height", "label": "Jump Height",
            "type": "number", "unit": "cm", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": [
                {"max": 40, "label": "Bajo", "color": "#dc2626"},
                {"min": 40, "max": 45, "label": "En rango", "color": "#f59e0b"},
                {"min": 45, "label": "Óptimo", "color": "#16a34a"},
            ],
        },
        {
            "key": "peak_power_bodymass", "label": "Peak Power/Body Mass",
            "type": "number", "unit": "W/kg", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "rsi_modified", "label": "RSI-modified",
            "type": "number", "unit": "m/s", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "ecc_peak_velocity", "label": "Eccentric Peak Velocity",
            "type": "number", "unit": "m/s", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

CMJ_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


# --- Nórdico (eccentric hamstring strength, NordBord) — per-leg force ---
# Reference bands (G. Tapia / club): 350–400 N por pierna; alto = mejor.
# Redefined 2026-07-07 (user spec): two inputs (L/R max force) + CALCULATED
# signed imbalance 100 * (left - right) / right → positive = left stronger.
# Alerted (bound rule) when it exceeds ±10% — see ALERT_RULES below.
_NORDIC_FORCE_BANDS = [
    {"max": 350, "label": "Bajo", "color": "#dc2626"},
    {"min": 350, "max": 400, "label": "En rango", "color": "#f59e0b"},
    {"min": 400, "label": "Óptimo", "color": "#16a34a"},
]

_NORDIC_IMBALANCE_BANDS = [
    {"max": -10, "label": "Marcada (der. domina)", "color": "#dc2626", "alert": True},
    {"min": -10, "max": -5, "label": "Leve (der.)", "color": "#f59e0b"},
    {"min": -5, "max": 5, "label": "Simétrico", "color": "#16a34a"},
    {"min": 5, "max": 10, "label": "Leve (izq.)", "color": "#f59e0b"},
    {"min": 10, "label": "Marcada (izq. domina)", "color": "#dc2626", "alert": True},
]

NORDICO_SCHEMA: dict = {
    "fields": [
        {
            "key": "left_max", "label": "L Max Force",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _NORDIC_FORCE_BANDS,
        },
        {
            "key": "right_max", "label": "R Max Force",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _NORDIC_FORCE_BANDS,
        },
        {
            "key": "imbalance", "label": "Imbalance",
            "type": "calculated", "unit": "%", "group": "Test",
            "chart_type": "line", "direction_of_good": "neutral",
            "formula": "100 * ([left_max] - [right_max]) / [right_max]",
            "reference_ranges": _NORDIC_IMBALANCE_BANDS,
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

NORDICO_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


# --- Fuerza isométrica en prono (rodilla casi extendida) — per-leg force ---
# Reference bands (G. Tapia / club): 290–320 N por pierna (~3.5 N/kg); alto =
# mejor. Sensible al ángulo: a 30° de flexión (ISO 30) asciende a ~350–370 N
# (anotar el protocolo en Notas).
_ISO_PRONO_BANDS = [
    {"max": 290, "label": "Bajo", "color": "#dc2626"},
    {"min": 290, "max": 320, "label": "En rango", "color": "#f59e0b"},
    {"min": 320, "label": "Óptimo", "color": "#16a34a"},
]

ISO_PRONO_SCHEMA: dict = {
    "fields": [
        {
            "key": "fuerza_izq", "label": "Fuerza isométrica – Izquierda",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _ISO_PRONO_BANDS,
        },
        {
            "key": "fuerza_der", "label": "Fuerza isométrica – Derecha",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
            "reference_ranges": _ISO_PRONO_BANDS,
        },
        {
            "key": "protocolo", "label": "Protocolo (ángulo)",
            "type": "categorical", "group": "Test",
            "options": ["extension", "iso30"],
            "option_labels": {"extension": "Rodilla casi extendida", "iso30": "ISO 30°"},
        },
        {
            "key": "asimetria", "label": "Asimetría",
            "type": "number", "unit": "%", "group": "Test",
            "chart_type": "line", "direction_of_good": "down",
            "reference_ranges": [
                {"max": 10, "label": "Simétrico", "color": "#16a34a"},
                {"min": 10, "max": 15, "label": "Leve", "color": "#f59e0b"},
                {"min": 15, "label": "Marcada", "color": "#dc2626"},
            ],
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

ISO_PRONO_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


# --- Hip AD/AB (groin squeeze & pull, e.g. ForceFrame) — per-leg force ---
# Two protocols per take: Pull (abduction) and Squeeze (adduction). Per leg,
# the Pull/Squeeze ratio; per protocol, the signed L/R imbalance:
#   100 * (right - left) / left   → positive = right stronger.
# Alerted (bound rule) when it exceeds ±15% — see ALERT_RULES below.
_HIP_IMBALANCE_BANDS = [
    {"max": -15, "label": "Marcada (izq. domina)", "color": "#dc2626", "alert": True},
    {"min": -15, "max": -10, "label": "Leve (izq.)", "color": "#f59e0b"},
    {"min": -10, "max": 10, "label": "Simétrico", "color": "#16a34a"},
    {"min": 10, "max": 15, "label": "Leve (der.)", "color": "#f59e0b"},
    {"min": 15, "label": "Marcada (der. domina)", "color": "#dc2626", "alert": True},
]

HIP_ADAB_SCHEMA: dict = {
    "fields": [
        # -- Pull --------------------------------------------------------
        {
            "key": "pull_left_max", "label": "Pull — Left Max Force",
            "type": "number", "unit": "N", "group": "Pull",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "pull_right_max", "label": "Pull — Right Max Force",
            "type": "number", "unit": "N", "group": "Pull",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "pull_imbalance", "label": "Imbalance (Pull)",
            "type": "calculated", "unit": "%", "group": "Pull",
            "chart_type": "line", "direction_of_good": "neutral",
            "formula": "100 * ([pull_right_max] - [pull_left_max]) / [pull_left_max]",
            "reference_ranges": _HIP_IMBALANCE_BANDS,
        },
        # -- Squeeze -----------------------------------------------------
        {
            "key": "squeeze_left_max", "label": "Squeeze — Left Max Force",
            "type": "number", "unit": "N", "group": "Squeeze",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "squeeze_right_max", "label": "Squeeze — Right Max Force",
            "type": "number", "unit": "N", "group": "Squeeze",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "squeeze_imbalance", "label": "Imbalance (Squeeze)",
            "type": "calculated", "unit": "%", "group": "Squeeze",
            "chart_type": "line", "direction_of_good": "neutral",
            "formula": "100 * ([squeeze_right_max] - [squeeze_left_max]) / [squeeze_left_max]",
            "reference_ranges": _HIP_IMBALANCE_BANDS,
        },
        # -- Ratios (Pull/Squeeze per leg) ---------------------------------
        {
            "key": "left_max_ratio", "label": "Left Max Ratio (Pull/Squeeze)",
            "type": "calculated", "group": "Ratios",
            "chart_type": "line", "direction_of_good": "neutral",
            "formula": "[pull_left_max] / [squeeze_left_max]",
        },
        {
            "key": "right_max_ratio", "label": "Right Max Ratio (Pull/Squeeze)",
            "type": "calculated", "group": "Ratios",
            "chart_type": "line", "direction_of_good": "neutral",
            "formula": "[pull_right_max] / [squeeze_right_max]",
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Ratios",
        },
    ],
}

HIP_ADAB_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


# --- IMTP (isometric mid-thigh pull) — force-plate strength test ---
IMTP_SCHEMA: dict = {
    "fields": [
        {
            "key": "peak_vertical_force", "label": "Peak Vertical Force",
            "type": "number", "unit": "N", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "peak_force_bodymass", "label": "PeakForce/BodyMass",
            "type": "number", "unit": "N/kg", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "rfd_200ms", "label": "RFD-200ms",
            "type": "number", "unit": "N/s", "group": "Test",
            "chart_type": "line", "direction_of_good": "up",
        },
        {
            "key": "notas", "label": "Notas",
            "type": "text", "multiline": True, "rows": 2, "group": "Test",
        },
    ],
}

IMTP_INPUT_CONFIG: dict = {
    "input_modes": ["single", "team_table"],
    "default_input_mode": "single",
}


TEMPLATES = [
    ("CK", "ck", CK_SCHEMA, CK_INPUT_CONFIG),
    ("Densidad urinaria", "densidad_urinaria", DENSIDAD_URINARIA_SCHEMA, DENSIDAD_URINARIA_INPUT_CONFIG),
    ("CMJ", "cmj", CMJ_SCHEMA, CMJ_INPUT_CONFIG),
    ("Nórdico", "nordico", NORDICO_SCHEMA, NORDICO_INPUT_CONFIG),
    ("Fuerza isométrica (prono)", "iso_prono", ISO_PRONO_SCHEMA, ISO_PRONO_INPUT_CONFIG),
    ("Hip AD/AB", "hip_adab", HIP_ADAB_SCHEMA, HIP_ADAB_INPUT_CONFIG),
    ("IMTP", "imtp", IMTP_SCHEMA, IMTP_INPUT_CONFIG),
]

# Threshold alert rules seeded alongside a template (idempotent by
# template+field+kind). `bound` fires when value > upper OR value < lower —
# the imbalance is signed, so ±15 covers a dominance either side.
# `band` (not `bound`): the imbalance fields' "Marcada" bands carry the
# thresholds (±10% nórdico, ±15% hip) via explicit `alert: True`, and band
# alerts AUTO-RESOLVE when a newer reading returns to range — bound ones
# would linger after the player recovers.
ALERT_RULES: dict[str, list[dict]] = {
    "nordico": [
        {
            "field_key": "imbalance",
            "kind": "band",
            "config": {},
            "severity": "warning",
            "message_template": "{field_label}: {value}% — asimetría entre piernas supera el 10%.",
        },
    ],
    "hip_adab": [
        {
            "field_key": "pull_imbalance",
            "kind": "band",
            "config": {},
            "severity": "warning",
            "message_template": "{field_label}: {value}% — asimetría entre piernas supera el 15%.",
        },
        {
            "field_key": "squeeze_imbalance",
            "kind": "band",
            "config": {},
            "severity": "warning",
            "message_template": "{field_label}: {value}% — asimetría entre piernas supera el 15%.",
        },
    ],
}


class Command(BaseCommand):
    help = (
        "Create / refresh the Médico clinical-indicator templates "
        "(CK, Densidad urinaria, CMJ)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true")
        parser.add_argument("--unlock", action="store_true")
        parser.add_argument(
            "--only", default=None,
            help="Comma-separated template slugs to touch (e.g. 'hip_adab,nordico'). "
                 "Everything else in TEMPLATES is left alone — use this so a "
                 "targeted run can't refresh (or resurrect) unrelated templates.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No clubs found.")
        if clubs.count() > 1 and not opts["club"]:
            raise CommandError("Multiple clubs exist; pass --club <name>.")

        only = (
            {s.strip() for s in opts["only"].split(",") if s.strip()}
            if opts["only"] else None
        )
        if only:
            known = {slug for _, slug, _, _ in TEMPLATES}
            unknown = only - known
            if unknown:
                raise CommandError(f"Unknown slug(s) in --only: {', '.join(sorted(unknown))}")

        for club in clubs:
            dept = Department.objects.filter(
                club=club, slug=opts["department_slug"],
            ).first()
            if dept is None:
                raise CommandError(
                    f"Department '{opts['department_slug']}' not found in '{club.name}'."
                )

            for name, slug, schema, input_config in TEMPLATES:
                if only and slug not in only:
                    continue
                template = ExamTemplate.objects.filter(
                    department=dept, name=name,
                ).first()
                if template is None:
                    if not opts["create_if_missing"]:
                        self.stdout.write(self.style.WARNING(
                            f"Skipping '{name}' (not found, --create-if-missing not passed)."
                        ))
                        continue
                    template = ExamTemplate(
                        name=name, slug=slug, department=dept,
                        config_schema=schema, input_config=input_config,
                    )
                    template.save()
                    action = "created"
                else:
                    if template.is_locked and not opts["unlock"]:
                        self.stdout.write(self.style.WARNING(
                            f"'{template.name}' is locked; pass --unlock to refresh."
                        ))
                        continue
                    template.config_schema = schema
                    template.input_config = input_config
                    if opts["unlock"]:
                        template.is_locked = False
                    template.save()
                    action = "refreshed"

                template.rebuild_template_fields()

                # Threshold alerts bundled with the template (idempotent).
                from goals.models import Alert, AlertRule

                specs = ALERT_RULES.get(slug, [])
                wanted = {(sp["field_key"], sp["kind"]) for sp in specs}
                stale = [
                    r for r in AlertRule.objects.filter(template=template)
                    if (r.field_key, r.kind) not in wanted
                ]
                for r in stale:
                    n_resolved = Alert.objects.filter(source_id=str(r.id)).delete()[0]
                    self.stdout.write(self.style.WARNING(
                        f"    alert rule removed (superseded): {r.field_key} {r.kind} "
                        f"(+{n_resolved} alert(s) dropped)"
                    ))
                    r.delete()
                for spec in specs:

                    rule, rule_created = AlertRule.objects.update_or_create(
                        template=template,
                        field_key=spec["field_key"],
                        kind=spec["kind"],
                        category=None,
                        defaults={
                            "config": spec["config"],
                            "severity": spec["severity"],
                            "message_template": spec.get("message_template", ""),
                            "is_active": True,
                        },
                    )
                    self.stdout.write(
                        f"    alert rule {'created' if rule_created else 'updated'}: "
                        f"{spec['field_key']} {spec['kind']} {spec['config']}"
                    )

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
