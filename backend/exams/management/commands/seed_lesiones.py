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
    # Aligned with the club's injury-surveillance sheet (Fuller consensus):
    # region + side split into two fields, mecanismo/modo, BAMIC (RM), and
    # the 5-step Fuller severity scale. Option VALUES mirror the sheet
    # verbatim (accent-free) so imports match exactly; `option_labels`
    # carry the accented display strings.
    "fields": [
        # === Diagnóstico ===
        {
            "key": "diagnosed_at", "label": "Fecha de lesión (inicio)", "type": "date",
            "group": "Diagnóstico", "required": True,
        },
        {
            "key": "type", "label": "Tipo / Diagnóstico (Fuller)", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": [
                "Lesion muscular (desgarro/rotura)",
                "Lesion tendinosa/Tendinopatia",
                "Esguince/Lesion ligamentosa",
                "Lesion meniscal/cartilago",
                "Fractura/Estres oseo",
                "Luxacion/Subluxacion",
                "Contusion/Hematoma",
                "Laceracion/Abrasion",
                "Lesion nerviosa",
                "Conmocion",
                "Sobrecarga/Otro",
                "Otro",
            ],
            "option_labels": {
                "Lesion muscular (desgarro/rotura)": "Lesión muscular (desgarro/rotura)",
                "Lesion tendinosa/Tendinopatia": "Lesión tendinosa / Tendinopatía",
                "Esguince/Lesion ligamentosa": "Esguince / Lesión ligamentosa",
                "Lesion meniscal/cartilago": "Lesión meniscal / cartílago",
                "Fractura/Estres oseo": "Fractura / Estrés óseo",
                "Luxacion/Subluxacion": "Luxación / Subluxación",
                "Contusion/Hematoma": "Contusión / Hematoma",
                "Laceracion/Abrasion": "Laceración / Abrasión",
                "Lesion nerviosa": "Lesión nerviosa",
                "Conmocion": "Conmoción",
            },
        },
        {
            "key": "body_part", "label": "Región", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": [
                "Cabeza/Cara", "Cuello/C. cervical", "Hombro/Clavicula",
                "Brazo", "Codo", "Antebrazo", "Muneca", "Mano/Dedos",
                "Torax/Costillas", "Abdomen", "Columna dorsal",
                "Columna lumbar/Pelvis", "Cadera/Ingle", "Muslo", "Rodilla",
                "Pierna/Aquiles", "Tobillo", "Pie/Dedos pie",
            ],
            "option_labels": {
                "Cabeza/Cara": "Cabeza / Cara",
                "Cuello/C. cervical": "Cuello / C. cervical",
                "Hombro/Clavicula": "Hombro / Clavícula",
                "Muneca": "Muñeca",
                "Mano/Dedos": "Mano / Dedos",
                "Torax/Costillas": "Tórax / Costillas",
                "Columna lumbar/Pelvis": "Columna lumbar / Pelvis",
                "Cadera/Ingle": "Cadera / Ingle",
                "Pierna/Aquiles": "Pierna / Aquiles",
                "Pie/Dedos pie": "Pie / Dedos del pie",
            },
            # Side-aware body-map mapping: "{side}" resolves from the `lado`
            # field (see side_field). Central/bilateral or missing side
            # paints both silhouette sides. Codo aliases brazo, Muñeca
            # aliases mano, Tobillo aliases calf — same aliasing as before.
            "side_field": "lado",
            "option_regions": {
                "Cabeza/Cara": "head",
                "Cuello/C. cervical": "neck",
                "Hombro/Clavicula": "{side}_shoulder",
                "Brazo": "{side}_arm",
                "Codo": "{side}_arm",
                "Antebrazo": "{side}_forearm",
                "Muneca": "{side}_hand",
                "Mano/Dedos": "{side}_hand",
                "Torax/Costillas": "chest",
                "Abdomen": "abdomen",
                "Columna dorsal": "upper_back",
                "Columna lumbar/Pelvis": "lower_back",
                "Cadera/Ingle": "pelvis",
                "Muslo": "{side}_thigh",
                "Rodilla": "{side}_knee",
                "Pierna/Aquiles": "{side}_calf",
                "Tobillo": "{side}_calf",
                "Pie/Dedos pie": "{side}_foot",
            },
        },
        {
            "key": "lado", "label": "Lado", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": ["Izquierdo", "Derecho", "Central/Bilateral", "NA"],
            "option_labels": {"Central/Bilateral": "Central / Bilateral"},
        },
        {
            "key": "body_part_detail", "label": "Localización específica",
            "type": "text", "group": "Diagnóstico", "multiline": False,
            "placeholder": "Ej: 'Bíceps femoral', 'Aductor largo', 'Tendón de Aquiles'…",
        },
        {
            "key": "severity", "label": "Severidad (Fuller)", "type": "categorical",
            "group": "Diagnóstico", "required": True,
            "options": ["Sin tiempo perdido", "Minima", "Leve", "Moderada", "Severa"],
            "option_labels": {"Minima": "Mínima"},
        },
        {
            "key": "bamic", "label": "BAMIC (RM)", "type": "categorical",
            "group": "Diagnóstico",
            "options": ["NA", "0", "0a", "0b", "1a", "1b", "1c",
                        "2a", "2b", "2c", "3a", "3b", "3c", "4"],
            "help_text": "Clasificación muscular británica por RM (solo lesiones musculares).",
        },
        {
            "key": "hallazgos_rm", "label": "Hallazgos RM / Informe", "type": "text",
            "multiline": True, "rows": 3, "group": "Diagnóstico",
            "placeholder": "Resumen del informe de imágenes…",
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
            # Canonical keys stay English/stable (they drive the episode
            # lifecycle + Player.status); the club's RTP-protocol labels
            # are display-only: Lesionado → Recuperación → Return to
            # Train → Return to Play (= episodio cerrado, vuelve a jugar).
            "options": ["injured", "recovery", "reintegration", "closed"],
            "option_labels": {
                "injured": "Lesionado",
                "recovery": "Recuperación",
                "reintegration": "Return to Train",
                "closed": "Return to Play",
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

        # === Contexto (Fuller: dónde y cómo ocurrió) ===
        {
            "key": "exposicion", "label": "Contexto", "type": "categorical",
            "group": "Contexto clínico",
            "options": ["Partido oficial", "Partido amistoso", "Entrenamiento",
                        "Seleccion nacional", "Otro"],
            "option_labels": {"Seleccion nacional": "Selección nacional"},
            "help_text": "Dónde ocurrió la lesión.",
        },
        {
            "key": "mecanismo", "label": "Mecanismo", "type": "categorical",
            "group": "Contexto clínico",
            "options": ["No contacto", "Contacto con jugador", "Contacto con objeto",
                        "Sobreuso", "Otro"],
        },
        {
            "key": "modo", "label": "Modo", "type": "categorical",
            "group": "Contexto clínico",
            "options": ["Agudo/Traumatico", "Sobreuso/Gradual"],
            "option_labels": {
                "Agudo/Traumatico": "Agudo / Traumático",
                "Sobreuso/Gradual": "Sobreuso / Gradual",
            },
        },
        {
            "key": "recurrencia", "label": "Recurrencia", "type": "categorical",
            "group": "Contexto clínico",
            "options": ["Nueva", "Recurrente"],
        },
        {
            "key": "tipo_recurrencia", "label": "Tipo de recurrencia", "type": "categorical",
            "group": "Contexto clínico",
            "options": ["NA", "Temprana (<2 meses)", "Tardia (2-12 meses)",
                        "Diferida (>12 meses)"],
            "option_labels": {
                "Temprana (<2 meses)": "Temprana (< 2 meses)",
                "Tardia (2-12 meses)": "Tardía (2–12 meses)",
                "Diferida (>12 meses)": "Diferida (> 12 meses)",
            },
        },
        {
            "key": "tratamiento", "label": "Tratamiento", "type": "categorical",
            "group": "Contexto clínico",
            "options": ["Kinésico", "Reposo deportivo", "Kinésico + quirúrgico", "Otro"],
        },
        {
            "key": "dias_perdidos", "label": "Días de baja", "type": "number", "unit": "días",
            "group": "Contexto clínico",
            "help_text": "Días totales de baja (puede usarse para inferir severidad).",
        },
        {
            "key": "partidos_perdidos", "label": "Partidos perdidos", "type": "number", "unit": "partidos",
            "group": "Contexto clínico",
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
    # Detail-first: "Bíceps femoral — Muslo" reads better on cards than the
    # long Fuller type strings. Falls back to just "— {region}" when the
    # detail is empty (formatter tolerates missing keys).
    "title_template": "{body_part_detail} — {body_part}",
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
