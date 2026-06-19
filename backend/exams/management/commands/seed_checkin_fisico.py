"""Create the daily wellness "Check-IN" template for the Físico area,
matching the club's Google-Forms wellness sheet (CHECK IN 2026).

Fields: training status (categorical) + 5 wellness items on a 1–10 scale
(higher = better) + a calculated total + a discomfort-zone text field.
Per the club: max value per item is 10.

    docker compose exec backend python manage.py seed_checkin_fisico \\
        --create-if-missing --club "Universidad de Chile"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department


# Wellness bands per scale (higher = better). recuperación is 1–10; the
# other four items are 1–5 (proven by the data).
_BANDS_10 = [
    {"max": 5, "label": "Bajo", "color": "#dc2626"},
    {"min": 5, "max": 8, "label": "Aceptable", "color": "#f59e0b"},
    {"min": 8, "label": "Bueno", "color": "#16a34a"},
]
_BANDS_5 = [
    {"max": 3, "label": "Bajo", "color": "#dc2626"},
    {"min": 3, "max": 4, "label": "Aceptable", "color": "#f59e0b"},
    {"min": 4, "label": "Bueno", "color": "#16a34a"},
]


def _num(key: str, label: str, mx: int) -> dict:
    return {
        "key": key, "label": label, "type": "number", "unit": "",
        "group": "Bienestar", "chart_type": "line",
        "direction_of_good": "up", "min": 1, "max": mx,
        "reference_ranges": _BANDS_10 if mx >= 10 else _BANDS_5,
    }


# Body-zone legend for the "molestia/dolor" codes (from the form's
# "Glosario Cuerpo" sheet). code → readable label.
ZONE_LABELS = {
    "A": "Cabeza", "B": "Hombro der.", "C": "Pecho", "D": "Pecho", "E": "Hombro izq.",
    "F": "Brazo der.", "G": "Zona media", "H": "Zona media", "I": "Zona media",
    "J": "Brazo izq.", "K": "Antebrazo der.", "L": "Antebrazo izq.", "Z": "Pubis",
    "1": "Mano der.", "2": "Mano izq.",
    "M": "Aductor der.", "N": "Aductor izq.", "O": "Cuádriceps der.", "P": "Cuádriceps izq.",
    "Q": "Tensor der.", "R": "Tensor izq.", "S": "Rodilla der.", "T": "Rodilla izq.",
    "U": "Tibia der.", "V": "Tibia izq.", "W": "Tobillo der.", "X": "Tobillo izq.",
    "A1": "Cabeza", "Y": "Cuello", "B1": "Hombro izq.", "C1": "Espalda", "D1": "Espalda",
    "E1": "Hombro der.", "F1": "Brazo izq.", "G1": "Espalda", "H1": "Zona lumbar",
    "I1": "Espalda", "J1": "Brazo der.", "K1": "Antebrazo izq.", "L1": "Antebrazo der.",
    "3": "Mano izq.", "4": "Mano der.",
    "M1": "Glúteo izq.", "N1": "Glúteo der.", "O1": "Isquiotibial izq.", "P1": "Isquiotibial der.",
    "S1": "Poplíteo izq.", "T1": "Poplíteo der.", "U1": "Gemelo/sóleo izq.", "V1": "Gemelo/sóleo der.",
    "W1": "Tendón izq.", "X1": "Tendón der.",
}
# code → canonical body-map region (front view is mirrored: image-left =
# player's right; back view is not). Coarser than the labels above.
ZONE_REGIONS = {
    "A": "head", "A1": "head", "Y": "neck",
    "B": "right_shoulder", "E": "left_shoulder", "B1": "left_shoulder", "E1": "right_shoulder",
    "C": "chest", "D": "chest", "G": "abdomen", "H": "abdomen", "I": "abdomen", "Z": "pelvis",
    "F": "right_arm", "J": "left_arm", "F1": "left_arm", "J1": "right_arm",
    "K": "right_forearm", "L": "left_forearm", "K1": "left_forearm", "L1": "right_forearm",
    "1": "right_hand", "2": "left_hand", "3": "left_hand", "4": "right_hand",
    "C1": "upper_back", "D1": "upper_back", "G1": "upper_back", "I1": "upper_back", "H1": "lower_back",
    "M": "right_thigh", "N": "left_thigh", "O": "right_thigh", "P": "left_thigh",
    "Q": "right_thigh", "R": "left_thigh", "M1": "pelvis", "N1": "pelvis",
    "O1": "left_thigh", "P1": "right_thigh",
    "S": "right_knee", "T": "left_knee", "S1": "left_knee", "T1": "right_knee",
    "U": "right_calf", "V": "left_calf", "U1": "left_calf", "V1": "right_calf",
    "W": "right_foot", "X": "left_foot", "W1": "left_foot", "X1": "right_foot",
}


SCHEMA: dict = {
    "fields": [
        {
            "key": "estado", "label": "Estado de entrenamiento",
            "type": "categorical", "group": "Bienestar",
            "options": ["disponible", "parcial", "lesion"],
            "option_labels": {
                "disponible": "Disponible (entrena normal)",
                "parcial": "Parcial (parte de la sesión)",
                "lesion": "Lesión (no entrena)",
            },
        },
        _num("recuperacion", "Calidad de la recuperación", 10),
        _num("cuerpo", "¿Cómo sientes tu cuerpo hoy?", 5),
        _num("energia", "Nivel de energía", 5),
        _num("animo", "Estado de ánimo", 5),
        _num("sueno", "¿Cómo dormiste?", 5),
        {
            "key": "total_bienestar", "label": "Total bienestar",
            "type": "calculated", "group": "Bienestar", "chart_type": "line",
            "formula": "[recuperacion] + [cuerpo] + [energia] + [animo] + [sueno]",
        },
        {
            "key": "molestia", "label": "Molestias / zona(s)",
            "type": "text", "group": "Bienestar", "multiline": True, "rows": 2,
            # Comma-separated body-zone codes; legend from "Glosario Cuerpo".
            "option_labels": ZONE_LABELS,
            "option_regions": ZONE_REGIONS,
        },
    ],
}

INPUT_CONFIG: dict = {
    "input_modes": ["team_table", "single"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": []},
}

NAME = "Check-IN Bienestar"
SLUG = "checkin_fisico"


class Command(BaseCommand):
    help = "Create/refresh the Físico daily wellness Check-IN template."

    def add_arguments(self, parser):
        parser.add_argument("--department-slug", default="fisico")
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
