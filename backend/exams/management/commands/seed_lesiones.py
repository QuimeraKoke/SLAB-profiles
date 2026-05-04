"""Seed the standard 'Lesiones' episodic exam template.

Each result on this template either opens a new injury Episode (no
episode_id passed) or progresses an existing open one (episode_id).
The template's `episode_config` declares the stage_field, the worst-to-
best stage list, and the closed stage. Player.status is automatically
recomputed from the player's open episodes via signal.

Run:

    docker compose exec backend python manage.py seed_lesiones \
        --create-if-missing --department-slug medico --all-applicable-categories
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


LESIONES_SCHEMA: dict = {
    "fields": [
        # === Diagnóstico ===
        {
            "key": "diagnosed_at", "label": "Fecha del diagnóstico", "type": "date",
            "group": "Diagnóstico", "required": True,
        },
        {
            "key": "type", "label": "Tipo de lesión", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": [
                "Muscular",
                "Tendinosa",
                "Ligamentosa",
                "Articular",
                "Ósea / fractura",
                "Contusión",
                "Concusión / TEC",
                "Sobreuso",
                "Otra",
            ],
        },
        {
            "key": "body_part", "label": "Parte del cuerpo", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": [
                "Cabeza", "Cuello", "Hombro izq.", "Hombro der.",
                "Brazo izq.", "Brazo der.", "Antebrazo izq.", "Antebrazo der.",
                "Mano izq.", "Mano der.", "Pecho", "Abdomen",
                "Espalda alta", "Espalda baja",
                "Cadera / pelvis",
                "Muslo izq.", "Muslo der.",
                "Rodilla izq.", "Rodilla der.",
                "Pantorrilla izq.", "Pantorrilla der.",
                "Tobillo izq.", "Tobillo der.",
                "Pie izq.", "Pie der.",
            ],
            # Map each option to a canonical body region. The widget renders
            # front + back silhouettes; limbs share keys across both views,
            # torso splits (chest/abdomen front-only, upper_back/lower_back
            # back-only). Tobillo still aliases calf — refine when we add
            # ankles as a region.
            "option_regions": {
                "Cabeza": "head",
                "Cuello": "neck",
                "Hombro izq.": "left_shoulder",
                "Hombro der.": "right_shoulder",
                "Brazo izq.": "left_arm",
                "Brazo der.": "right_arm",
                "Antebrazo izq.": "left_forearm",
                "Antebrazo der.": "right_forearm",
                "Mano izq.": "left_hand",
                "Mano der.": "right_hand",
                "Pecho": "chest",
                "Abdomen": "abdomen",
                "Espalda alta": "upper_back",
                "Espalda baja": "lower_back",
                "Cadera / pelvis": "pelvis",
                "Muslo izq.": "left_thigh",
                "Muslo der.": "right_thigh",
                "Rodilla izq.": "left_knee",
                "Rodilla der.": "right_knee",
                "Pantorrilla izq.": "left_calf",
                "Pantorrilla der.": "right_calf",
                "Tobillo izq.": "left_calf",
                "Tobillo der.": "right_calf",
                "Pie izq.": "left_foot",
                "Pie der.": "right_foot",
            },
        },
        {
            "key": "body_part_detail", "label": "Detalle anatómico (texto libre)",
            "type": "text", "group": "Diagnóstico", "multiline": False,
            "placeholder": "Ej: 'isquiotibial — cabeza larga del bíceps femoral'",
        },
        {
            "key": "severity", "label": "Severidad", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": ["Leve", "Moderada", "Severa"],
        },

        # === Etapa (drives the episode lifecycle) ===
        # The internal option keys stay English so they line up with
        # episode_config.open_stages / closed_stage and the
        # _map_stage_to_player_status() helper. The doctor sees the
        # Spanish labels via option_labels — the form renders the label,
        # the canonical key is what's stored.
        {
            "key": "stage", "label": "Etapa", "type": "categorical",
            "group": "Etapa", "required": True,
            "options": ["injured", "recovery", "reintegration", "closed"],
            "option_labels": {
                "injured": "Lesionado",
                "recovery": "Recuperación",
                "reintegration": "Reintegración",
                "closed": "Cerrado",
            },
        },

        # === Pronóstico ===
        {
            "key": "expected_return_date", "label": "Retorno estimado",
            "type": "date", "group": "Pronóstico",
        },
        {
            "key": "actual_return_date", "label": "Retorno efectivo",
            "type": "date", "group": "Pronóstico",
            "placeholder": "Completar al cerrar el episodio",
        },

        # === Notas + adjuntos ===
        {
            "key": "notes", "label": "Notas / plan", "type": "text",
            "multiline": True, "rows": 6, "group": "Notas",
            "placeholder": "Plan de tratamiento, evolución, observaciones…",
        },
        {
            "key": "imaging", "label": "Imágenes / informes",
            "type": "file", "group": "Adjuntos",
            "placeholder": "Radiografías, RM, ecografías, informes en PDF…",
        },
    ],
}


EPISODE_CONFIG = {
    "stage_field": "stage",
    "open_stages": ["injured", "recovery", "reintegration"],
    "closed_stage": "closed",
    "title_template": "{type} — {body_part}",
}


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
    "modifiers": {"prefill_from_last": False},
}


class Command(BaseCommand):
    help = "Create or refresh the 'Lesiones' episodic template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="medico",
                            help="Department slug (default: 'medico').")
        parser.add_argument("--club", default=None,
                            help="Required when more than one club exists.")
        parser.add_argument("--name", default="Lesiones",
                            help="Template name (default: 'Lesiones').")
        parser.add_argument("--slug", default="lesiones",
                            help="Template slug used in formula refs (default: 'lesiones').")
        parser.add_argument("--create-if-missing", action="store_true")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="Attach to every category in the department's club.")
        parser.add_argument("--unlock", action="store_true",
                            help="Unlock the template even if results exist.")

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
                    config_schema=LESIONES_SCHEMA,
                    input_config=INPUT_CONFIG,
                    is_episodic=True,
                    episode_config=EPISODE_CONFIG,
                )
                template.save()
                action = "created"
            else:
                if template.is_locked and not opts["unlock"]:
                    self.stdout.write(self.style.WARNING(
                        f"Template '{template.name}' is locked; pass --unlock to refresh."
                    ))
                    continue
                template.config_schema = LESIONES_SCHEMA
                template.input_config = INPUT_CONFIG
                template.is_episodic = True
                template.episode_config = EPISODE_CONFIG
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
                    f"[{club.name}] {action} '{template.name}' (slug={template.slug}); "
                    f"attached to: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' (slug={template.slug})"
                ))
