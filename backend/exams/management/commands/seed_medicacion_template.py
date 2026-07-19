"""Seed the 'Medicación' exam template for the Médico department.

Simplified per el pedido del área médica (2026-07): cada receta es un
`ExamResult` plano (sin ciclo de episodio, sin etapas). Los campos son:

    Nombre · Tipo · Vía · Dosis · Fechas (inicio/fin) · Indicación · Adjuntos

`Nombre`, `Tipo` y `Vía` son listas **seleccionables** (sin texto libre).
El nombre lista solo el fármaco, sin la cantidad/mg (la dosis va en su
propio campo). Adjuntos es opcional.

Alertas WADA: el campo `medicamento` conserva la metadata `option_risk`
(+ `option_notes` / `option_actions`) que lee el signal
`medication_wada_alert_on_result_save`. La clasificación reutiliza la del
listado médico original (`data/medicamentos.csv`) matcheada por principio
activo. Recetar un medicamento CONDICIONAL o PROHIBIDO dispara una alerta
anti-doping automática. Fuente: WADA 2025 / globaldro.com — el equipo
médico debe verificar la formulación puntual de cada marca.

Run:

    docker compose exec backend python manage.py seed_medicacion_template \\
        --create-if-missing --department-slug medico --all-applicable-categories
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


# --- Catálogo seleccionable (curado por el área médica) --------------------
# Solo el nombre del fármaco, sin cantidad/mg ni vía (esos van en sus campos).
MEDICAMENTOS = [
    "Abrilar",
    "Aciclovir",
    "Amoxicilina",
    "Amoxicilina + Ácido clavulánico",
    "Antiax",
    "Azitromicina",
    "Bromhexina",
    "Celecoxib",
    "Dacam",
    "Desdol",
    "Desloratadina",
    "Dogenal",
    "Domperidona",
    "Eterocoxib",
    "Fresh Mell",
    "Ketanor",
    "Ketoprofeno",
    "Lertus",
    "Levodroprizina",
    "Loperamida",
    "Neurobionta",
    "Oticum",
    "Papaína",
    "Paracetamol",
    "Pro Bextra",
    "Reflexan",
    "Suprahyal",
    "Tapsin té día y noche",
    "Valaciclovir",
    "Viadil",
    "Zopiclona",
]

# --- Clasificación WADA (reutilizada de data/medicamentos.csv por principio
# activo). Todo lo no listado aquí es PERMITIDO. Solo CONDICIONAL/PROHIBIDO
# disparan alerta. Fuente: WADA 2025 / globaldro.com — verificar formulación.
WADA_FLAGS = {
    # (riesgo, nota_medica, accion_requerida)
    "Pro Bextra": (
        "PROHIBIDO",
        "Glucocorticoide inyectable sistémico (betametasona/dexametasona): "
        "PROHIBIDO EN COMPETICIÓN (WADA S9).",
        "No administrar en competición. Requiere TUE/AUT si es médicamente "
        "necesario; documentar y respetar el periodo de lavado.",
    ),
    "Tapsin té día y noche": (
        "CONDICIONAL",
        "Contiene pseudoefedrina: prohibida EN COMPETICIÓN sobre 150 µg/mL en orina.",
        "Evitar 24 h antes y durante la competición; preferir alternativa "
        "sin pseudoefedrina.",
    ),
}

# Marcas que NO estaban en el listado WADA original; se asumen PERMITIDO por
# principio activo pero conviene que el médico las verifique en globaldro.com.
WADA_VERIFY = {"Dacam", "Levodroprizina", "Papaína", "Reflexan"}

TIPOS = [
    "Aines",
    "Analgésico",
    "Antipirético",
    "Relajante muscular",
    "Inductor del sueño",
    "Antialérgico",
    "Antigripal",
    "Antitusivo",
    "Antiespasmódico",
    "Antiácido / antiulceroso",
    "Antidiarreico",
    "Antiemético",
    "Antibiótico",
    "Antiviral",
    "Corticoide",
    "Vitaminas",
    "Enzimático",
    "Ácido hialurónico",
    "Anestesia",
    "Medicina regenerativa",
    "Otro",
]

VIAS = [
    "Oral",
    "Sublingual",
    "Jarabe",
    "Gotas",
    "Ampolla",
    "Crema",
    "Ótica",
    "Intraarticular",
    "Otra",
]


def _labels(options: list[str]) -> dict[str, str]:
    """Identity label map — la opción es auto-descriptiva (key == label)."""
    return {o: o for o in options}


def _build_risk_maps() -> tuple[dict, dict, dict]:
    """Construye option_risk / option_notes / option_actions para el campo
    `medicamento`. Todo PERMITIDO salvo lo declarado en WADA_FLAGS."""
    option_risk: dict[str, str] = {}
    option_notes: dict[str, str] = {}
    option_actions: dict[str, str] = {}
    for name in MEDICAMENTOS:
        if name in WADA_FLAGS:
            riesgo, nota, accion = WADA_FLAGS[name]
            option_risk[name] = riesgo
            if nota:
                option_notes[name] = nota
            if accion:
                option_actions[name] = accion
        else:
            option_risk[name] = "PERMITIDO"
            if name in WADA_VERIFY:
                option_notes[name] = (
                    "Clasificación por defecto (no estaba en el listado WADA "
                    "original) — verificar formulación en globaldro.com."
                )
    return option_risk, option_notes, option_actions


def _build_schema() -> dict:
    """Config schema simplificado: 3 listas seleccionables + dosis, fechas,
    indicación y adjuntos. Sin etapas, sin cantidad ni notas. El campo
    `medicamento` conserva la metadata WADA (`option_risk`) para las alertas."""
    option_risk, option_notes, option_actions = _build_risk_maps()
    return {
        "fields": [
            # === Medicamento ===
            {
                "key": "medicamento",
                "label": "Nombre",
                "type": "categorical",
                "group": "Medicamento",
                "required": True,
                "options": list(MEDICAMENTOS),
                "option_labels": _labels(MEDICAMENTOS),
                # Metadata WADA — leída por el signal de alertas anti-doping.
                "option_risk": option_risk,
                "option_notes": option_notes,
                "option_actions": option_actions,
            },
            {
                "key": "tipo",
                "label": "Tipo de medicamento",
                "type": "categorical",
                "group": "Medicamento",
                "options": list(TIPOS),
                "option_labels": _labels(TIPOS),
            },
            {
                "key": "via_admin",
                "label": "Vía de administración",
                "type": "categorical",
                "group": "Medicamento",
                "options": list(VIAS),
                "option_labels": _labels(VIAS),
            },
            {
                "key": "dosis",
                "label": "Dosis / posología",
                "type": "text",
                "group": "Medicamento",
                "placeholder": "Ej: 1 comprimido cada 8 hs por 5 días",
            },

            # === Fechas ===
            {
                "key": "fecha_inicio",
                "label": "Inicio del tratamiento",
                "type": "date",
                "group": "Fechas",
                "required": True,
            },
            {
                "key": "fecha_fin",
                "label": "Fin del tratamiento (estimado)",
                "type": "date",
                "group": "Fechas",
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

            # === Adjuntos (opcional) ===
            {
                "key": "adjuntos",
                "label": "Adjuntos (opcional)",
                "type": "file",
                "group": "Adjuntos",
                "placeholder": "Receta médica, ficha técnica, informe…",
            },
        ],
    }


INPUT_CONFIG = {
    "input_modes": ["single"],
    "default_input_mode": "single",
}


class Command(BaseCommand):
    help = "Create or refresh the simplified 'Medicación' template (flat, seleccionable, sin etapas)."

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
        schema = _build_schema()
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
                # Flat-result model — clear any leftover episode_config so the
                # admin / API never see stale stage definitions.
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
                    f"(slug={template.slug}); {len(MEDICAMENTOS)} medicamentos, "
                    f"{flagged} con alerta WADA; categorías: {cats_label}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] {action} '{template.name}' "
                    f"(slug={template.slug}); {len(MEDICAMENTOS)} medicamentos, "
                    f"{flagged} con alerta WADA"
                ))
