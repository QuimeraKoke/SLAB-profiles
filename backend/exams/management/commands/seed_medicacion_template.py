"""Seed the 'Medicación' exam template for the Médico department.

Each prescription is a flat `ExamResult` — no episode lifecycle. Tracked
fields capture which player is on what drug, since when, until when
(optional `fecha_fin`), dose, route, and indication. Edits happen via
the Médico department card's history table (per-row pencil button).

The medicines list, their categoría (group), and their WADA risk level
are loaded from `data/medicamentos.csv` shipped alongside this command.

Risk metadata (PERMITIDO / CONDICIONAL / PROHIBIDO + WADA notes + actions)
is stashed on the `medicamento` field config under custom keys
(`option_risk`, `option_notes`, `option_actions`) so the post-save signal
in `exams.signals.medication_wada_alert_on_result_save` can read it and
fire WADA-flagged alerts via the existing `_upsert_alert` infrastructure.

Run:

    docker compose exec backend python manage.py seed_medicacion_template \\
        --create-if-missing --department-slug medico --all-applicable-categories
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


CSV_PATH = Path(__file__).resolve().parent / "data" / "medicamentos.csv"


def _load_medicines() -> list[dict]:
    """Read the bundled CSV. Strips whitespace; empty rows ignored."""
    if not CSV_PATH.exists():
        raise CommandError(
            f"Medicines CSV not found at {CSV_PATH}. "
            f"Place medicamentos.csv next to this command."
        )
    rows: list[dict] = []
    with CSV_PATH.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for raw in reader:
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
            if not row.get("nombre"):
                continue
            rows.append(row)
    if not rows:
        raise CommandError("Medicines CSV is empty after parsing.")
    return rows


def _option_key(name: str) -> str:
    """Stable, idempotent key per medicine. Matches the CSV's `nombre`
    column verbatim — keeping it as the canonical key makes the option
    string self-describing in result_data (vs. an opaque slug)."""
    return name


def _build_schema(medicines: list[dict]) -> dict:
    """Construct the template's config_schema with the medicamento field
    populated from the CSV. The cascading group → option dropdown is
    enabled by `option_groups`; risk + WADA metadata sits in custom
    `option_risk` / `option_notes` / `option_actions` maps."""
    options: list[str] = []
    option_labels: dict[str, str] = {}
    option_groups: dict[str, str] = {}
    option_risk: dict[str, str] = {}
    option_notes: dict[str, str] = {}
    option_actions: dict[str, str] = {}

    for med in medicines:
        key = _option_key(med["nombre"])
        if key in option_labels:
            # Duplicate names — append a discriminator so the option set is unique.
            key = f"{key} (id {med.get('id', '?')})"
        options.append(key)
        option_labels[key] = med["nombre"]
        option_groups[key] = med.get("categoria") or "Otros"
        option_risk[key] = (med.get("riesgo_doping") or "").upper() or "PERMITIDO"
        if med.get("nota_medica"):
            option_notes[key] = med["nota_medica"]
        if med.get("accion_requerida") and med["accion_requerida"].lower() not in {"ninguna", ""}:
            option_actions[key] = med["accion_requerida"]

    return {
        "fields": [
            # === Curso de medicación ===
            {
                "key": "medicamento",
                "label": "Medicamento",
                "type": "categorical",
                "group": "Curso",
                "required": True,
                "options": options,
                "option_labels": option_labels,
                "option_groups": option_groups,
                # Custom metadata — read by the WADA-alert signal.
                "option_risk": option_risk,
                "option_notes": option_notes,
                "option_actions": option_actions,
            },
            {
                "key": "via_admin",
                "label": "Vía de administración",
                "type": "categorical",
                "group": "Curso",
                "options": [
                    "oral",
                    "sublingual",
                    "inyectable",
                    "inyectable local",
                    "topica",
                    "topica/oral",
                    "inhalatoria",
                    "intraarticular",
                    "otra",
                ],
            },
            {
                "key": "dosis",
                "label": "Dosis / posología",
                "type": "text",
                "group": "Curso",
                "placeholder": "Ej: 1 comprimido cada 8 hs por 5 días",
            },
            {
                "key": "fecha_inicio",
                "label": "Inicio del tratamiento",
                "type": "date",
                "group": "Curso",
                "required": True,
            },
            {
                "key": "fecha_fin",
                "label": "Fin del tratamiento (estimado)",
                "type": "date",
                "group": "Curso",
                "placeholder": "Dejar vacío si la duración aún no se conoce",
            },

            # === Indicación ===
            {
                "key": "motivo",
                "label": "Indicación clínica",
                "type": "text",
                "group": "Indicación",
                "placeholder": "Ej: dolor lumbar post-partido",
            },

            # === Etapa (drives the episode lifecycle) ===
            # `activa` while the player is on the course; `completada` once
            # the course ends (or is interrupted). `suspendida` is open and
            # treated as still-active for the squad-availability widget.
            {
                "key": "stage",
                "label": "Estado del tratamiento",
                "type": "categorical",
                "group": "Estado",
                "required": True,
                "options": ["activa", "suspendida", "completada"],
                "option_labels": {
                    "activa": "Activa",
                    "suspendida": "Suspendida",
                    "completada": "Completada",
                },
            },

            # === Notas + adjuntos ===
            {
                "key": "notas",
                "label": "Notas / observaciones",
                "type": "text",
                "multiline": True,
                "rows": 5,
                "group": "Notas",
                "placeholder": "Reacciones adversas, ajustes de dosis, etc.",
            },
            {
                "key": "adjuntos",
                "label": "Recetas / informes",
                "type": "file",
                "group": "Adjuntos",
                "placeholder": "Receta médica, ficha técnica, notificación TUE…",
            },
        ],
    }


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
}


class Command(BaseCommand):
    help = "Create or refresh the 'Medicación' episodic template loaded from medicamentos.csv."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico")
        parser.add_argument("--club", default=None)
        parser.add_argument("--name", default="Medicación")
        parser.add_argument("--slug", default="medicacion")
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true")
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        medicines = _load_medicines()
        schema = _build_schema(medicines)
        flagged = sum(
            1 for v in schema["fields"][0]["option_risk"].values()
            if v in {"PROHIBIDO", "CONDICIONAL"}
        )

        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No clubs found.")
        if clubs.count() > 1 and not opts["club"]:
            raise CommandError("Multiple clubs exist; pass --club <name>.")

        for club in clubs:
            dept = Department.objects.filter(
                club=club, slug=opts["department_slug"],
            ).first()
            if dept is None:
                raise CommandError(
                    f"Department '{opts['department_slug']}' not found in club '{club.name}'."
                )

            template = ExamTemplate.objects.filter(
                department=dept, name=opts["name"],
            ).first()

            if template is None:
                if not opts["create_if_missing"]:
                    raise CommandError(
                        f"Template '{opts['name']}' not found in {dept}; "
                        f"pass --create-if-missing to create it."
                    )
                template = ExamTemplate(
                    name=opts["name"],
                    slug=opts["slug"],
                    department=dept,
                    config_schema=schema,
                    input_config=INPUT_CONFIG,
                    is_episodic=False,
                    show_injuries=False,
                )
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"Template '{template.name}' is locked; pass --unlock to refresh."
                    ))
                    continue
                template.config_schema = schema
                template.input_config = INPUT_CONFIG
                template.is_episodic = False
                # Flat-result model — clear any leftover episode_config
                # from prior episodic runs so the admin / API never see
                # stale stage definitions.
                template.episode_config = {}
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
                    f"(slug={template.slug}); {len(medicines)} medicamentos, "
                    f"{flagged} con alerta WADA; categorías: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' "
                    f"(slug={template.slug}); {len(medicines)} medicamentos, "
                    f"{flagged} con alerta WADA"
                ))
