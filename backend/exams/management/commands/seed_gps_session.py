"""Create / overwrite the per-session TRAINING GPS template ("GPS Entrenamiento").

One half of the live GPS pair: `gps_sesion` holds per-session training totals
(one row per player per session — trainings, rehab "reintegro", tactical
work); its sibling `gps_partido` (see `seed_gps_partido`) holds the
event-linked match sessions with the same field keys. The legacy
`seed_gps_match` (per-half export) / `seed_gps_training` profiles predate this
pair.

It is the target of the `import_gps_sessions` backfill command and the
training side of the `/gps-sessions/upload` endpoint; the `single` /
`team_table` input modes are just a manual-entry fallback. Field keys here are
the contract the importer maps the export headers onto — keep them in sync
with `exams/gps_session.py:HEADER_TO_KEY`.

Run:

    docker compose exec backend python manage.py seed_gps_session \\
        --create-if-missing --department-slug fisico \\
        --all-applicable-categories
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


CONFIG_SCHEMA: dict = {
    "fields": [
        # --- Session identity ---
        {
            "key": "fecha", "label": "Fecha de la sesión",
            "type": "date", "group": "Sesión", "required": True,
        },
        {
            "key": "sesion", "label": "Sesión",
            "type": "text", "group": "Sesión",
            "placeholder": "p.ej. F8 vs La Serena / Sesión 04-01-26",
        },
        {
            "key": "tipo_sesion", "label": "Tipo de sesión",
            "type": "categorical", "group": "Sesión",
            # "partido" lives on the gps_partido template; an unlinked friendly
            # logged here keeps "amistoso".
            "options": ["amistoso", "tareas", "entrenamiento", "reintegro", "otro"],
            "option_labels": {
                "amistoso": "Amistoso",
                "tareas": "Tareas tácticas",
                "entrenamiento": "Entrenamiento",
                "reintegro": "Reintegro",
                "otro": "Otro",
            },
        },
        # --- Load / volume ---
        {
            "key": "tot_dur", "label": "Duración",
            "type": "number", "unit": "min", "group": "Carga", "chart_type": "line",
        },
        {
            "key": "tot_dist", "label": "Distancia total",
            "type": "number", "unit": "m", "group": "Distancia", "chart_type": "line",
        },
        {
            "key": "mpm", "label": "Metros por minuto",
            "type": "number", "unit": "m/min", "group": "Ritmo", "chart_type": "line",
        },
        # --- High-speed distances ---
        {
            "key": "hsr", "label": "HSR > 19,8 km/h",
            "type": "number", "unit": "m", "group": "Distancia", "chart_type": "line",
        },
        {
            "key": "sprint_dist", "label": "Distancia Sprint > 25 km/h",
            "type": "number", "unit": "m", "group": "Distancia",
        },
        {
            "key": "sprints", "label": "Sprints",
            "type": "number", "unit": "n", "group": "Velocidad",
        },
        {
            "key": "max_vel", "label": "Velocidad máxima",
            "type": "number", "unit": "km/h", "group": "Velocidad", "chart_type": "line",
        },
        # --- Accelerations / decelerations ---
        {
            "key": "acc_dec", "label": "Acc + Dec ≥3",
            "type": "number", "unit": "n", "group": "Aceleración",
        },
        {
            "key": "acc", "label": "Acc ≥3",
            "type": "number", "unit": "n", "group": "Aceleración",
        },
        {
            "key": "dec", "label": "Dec ≥3",
            "type": "number", "unit": "n", "group": "Aceleración",
        },
        {
            "key": "dist_acc", "label": "Distancia en aceleración",
            "type": "number", "unit": "m", "group": "Aceleración",
        },
        {
            "key": "dist_dec", "label": "Distancia en desaceleración",
            "type": "number", "unit": "m", "group": "Aceleración",
        },
        {
            "key": "hmld", "label": "HMLD",
            "type": "number", "unit": "m", "group": "Distancia",
        },
        # --- Optional provider metrics (not in every export) ---
        {
            "key": "player_load", "label": "Player Load",
            "type": "number", "unit": "a.u.", "group": "Carga",
        },
        {
            "key": "hiaa", "label": "HIAA",
            "type": "number", "unit": "n", "group": "Aceleración",
        },
        {
            "key": "rpe", "label": "RPE",
            "type": "number", "unit": "1-10", "group": "Carga",
        },
        # --- Speed zones (% of Vmax) ---
        {
            "key": "zone_75_85", "label": "Zona 75-85% Vmax",
            "type": "number", "unit": "m", "group": "Velocidad",
        },
        {
            "key": "zone_85_95", "label": "Zona 85-95% Vmax",
            "type": "number", "unit": "m", "group": "Velocidad",
        },
        {
            "key": "zone_95_100", "label": "Zona 95-100% Vmax",
            "type": "number", "unit": "m", "group": "Velocidad",
        },
        # --- Intensidad relativa (por minuto) ---
        # Normalizan el volumen por la duración de la sesión, de modo que un
        # entrenamiento de 30' no se compara contra uno de 90' en crudo. Base
        # preferida para las alertas intra-individuales (z-score). tot_dur=0 o
        # vacío hace fallar la fórmula → el campo queda None (sin ruido).
        {
            "key": "hsr_min", "label": "HSR por minuto",
            "type": "calculated", "unit": "m/min", "group": "Ritmo", "chart_type": "line",
            "formula": "[hsr] / [tot_dur]",
        },
        {
            "key": "sprint_dist_min", "label": "Distancia Sprint por minuto",
            "type": "calculated", "unit": "m/min", "group": "Ritmo",
            "formula": "[sprint_dist] / [tot_dur]",
        },
        {
            "key": "acc_dec_min", "label": "Acc + Dec por minuto",
            "type": "calculated", "unit": "n/min", "group": "Ritmo",
            "formula": "[acc_dec] / [tot_dur]",
        },
        {
            "key": "player_load_min", "label": "Player Load por minuto",
            "type": "calculated", "unit": "a.u./min", "group": "Ritmo",
            "formula": "[player_load] / [tot_dur]",
        },
    ],
}


INPUT_CONFIG: dict = {
    # Manual-entry fallback only — the bulk season load is done by the
    # import_gps_sessions management command, not through the UI.
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "modifiers": {"prefill_from_last": False},
    "team_table": {
        "shared_fields": ["fecha", "sesion", "tipo_sesion"],
    },
}


class Command(BaseCommand):
    help = "Create / refresh the per-session GPS template (Físico, one row per player per session)."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="fisico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="GPS Entrenamiento")
        parser.add_argument("--slug", default="gps_sesion")
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

        for club in clubs:
            dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
            if dept is None:
                raise CommandError(
                    f"Department '{opts['department_slug']}' not found in club '{club.name}'."
                )

            # Slug lookup so a display-name rename never forks a duplicate.
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
                    config_schema=CONFIG_SCHEMA,
                    input_config=INPUT_CONFIG,
                    # Trainings carry no Event; matches live on gps_partido.
                    link_to_match=False,
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
                template.config_schema = CONFIG_SCHEMA
                template.input_config = INPUT_CONFIG
                template.link_to_match = False
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
