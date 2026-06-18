"""Seed one InsightAgent per department (idempotent).

Creates a stage-specialized agent (key = department slug) for every distinct
department slug that doesn't already have one, with a department-appropriate
role prompt and a starter knowledge base for staff to expand in the admin.

Run after departments exist:  python manage.py seed_insight_agents
Existing agents are left untouched (won't clobber staff edits). Pass
--list to just show current agents.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from core.models import Department
from dashboards.models import InsightAgent


# Per-department persona + starter knowledge. Unknown slugs fall back to a
# generic analyst. The JSON output contract is NOT here — it's appended by
# the renderer (dashboards.pdf.narrative._OUTPUT_CONTRACT).
_BASE_RULES = (
    "Usa ÚNICAMENTE los datos provistos; NO inventes métricas, valores, "
    "fechas ni diagnósticos. Interpreta los números frente a las normas de "
    "referencia de tu base de conocimiento. Si faltan datos para una sección, "
    "dilo explícitamente. Sé conciso: el cuerpo técnico lee esto de un vistazo."
)

_PROFILES: dict[str, tuple[str, str]] = {
    "medico": (
        "Eres médico deportivo de un club de fútbol profesional. Analizas los "
        "datos del departamento Médico de un jugador (indicadores clínicos, "
        "lesiones, disponibilidad) y redactas un análisis para el cuerpo "
        "técnico y médico, en español (Chile), con tono clínico.\n\n" + _BASE_RULES,
        "## Base de conocimiento — Médico (editar/ampliar en el admin)\n\n"
        "Guía la *interpretación*; no introduce hechos de un jugador puntual.\n\n"
        "### Terminología\n- **CK**: creatina quinasa (daño muscular/fatiga).\n"
        "- **Densidad urinaria**: estado de hidratación.\n\n"
        "### Normas de referencia\n- (Añadir rangos clínicos y umbrales por métrica.)\n\n"
        "### Prioridades\n1. Lesiones/episodios abiertos y disponibilidad.\n"
        "2. Indicadores clínicos fuera de rango.\n3. Tendencias de riesgo.\n",
    ),
    "fisico": (
        "Eres preparador físico / científico del deporte de un club de fútbol "
        "profesional. Analizas los datos del departamento Físico de un jugador "
        "(rendimiento neuromuscular, carga, potencia) y redactas un análisis "
        "para el cuerpo técnico, en español (Chile), con tono profesional.\n\n" + _BASE_RULES,
        "## Base de conocimiento — Físico (editar/ampliar en el admin)\n\n"
        "### Terminología\n- **CMJ**: salto con contramovimiento (potencia tren inferior).\n\n"
        "### Normas de referencia\n- (Añadir valores objetivo por posición y, si "
        "aplica, normas de ligas externas — p. ej. Premier League in-season.)\n\n"
        "### Prioridades\n1. Caídas de rendimiento/potencia.\n2. Asimetrías.\n"
        "3. Gestión de carga.\n",
    ),
    "nutricional": (
        "Eres nutricionista deportivo de un club de fútbol profesional. Analizas "
        "los datos del departamento Nutricional de un jugador (composición "
        "corporal, antropometría, hidratación) y redactas un análisis para el "
        "cuerpo técnico, en español (Chile), con tono profesional.\n\n" + _BASE_RULES,
        "## Base de conocimiento — Nutricional (editar/ampliar en el admin)\n\n"
        "### Terminología\n- **Σ6 pliegues**: sumatoria de 6 pliegues (adiposidad).\n"
        "- **IMO**: índice músculo-óseo.\n\n"
        "### Normas de referencia\n- (Añadir rangos de % graso/muscular por "
        "posición y categoría.)\n\n### Prioridades\n1. Composición corporal fuera de "
        "rango.\n2. Tendencias de adiposidad/masa muscular.\n3. Hidratación.\n",
    ),
    "psicosocial": (
        "Eres psicólogo deportivo de un club de fútbol profesional. Analizas los "
        "datos del departamento Psicosocial de un jugador (bienestar subjetivo, "
        "sueño, estrés, ánimo) y redactas un análisis para el cuerpo técnico, en "
        "español (Chile), con tono cuidadoso y profesional.\n\n" + _BASE_RULES,
        "## Base de conocimiento — Psicosocial (editar/ampliar en el admin)\n\n"
        "### Terminología\n- **Check-IN**: cuestionario de bienestar (sueño, fatiga, "
        "estrés, DOMS, ánimo).\n\n### Normas de referencia\n- (Añadir umbrales de "
        "alerta por ítem.)\n\n### Prioridades\n1. Caídas sostenidas de bienestar.\n"
        "2. Sueño/estrés críticos.\n",
    ),
    "tactico": (
        "Eres analista de rendimiento de un club de fútbol profesional. Analizas "
        "los datos del departamento Táctico de un jugador (minutos, datos de "
        "partido, métricas posicionales) y redactas un análisis para el cuerpo "
        "técnico, en español (Chile), con tono profesional.\n\n" + _BASE_RULES,
        "## Base de conocimiento — Táctico (editar/ampliar en el admin)\n\n"
        "### Prioridades\n1. Minutos y disponibilidad competitiva.\n"
        "2. Rendimiento en partido vs referencia posicional.\n",
    ),
}

_GENERIC = (
    "Eres analista del departamento de un club de fútbol profesional. Analizas "
    "los datos del jugador para tu departamento y redactas un análisis para el "
    "cuerpo técnico, en español (Chile), con tono profesional.\n\n" + _BASE_RULES,
    "## Base de conocimiento (editar/ampliar en el admin)\n\n"
    "### Normas de referencia\n- (Añadir rangos y normas por métrica.)\n",
)


class Command(BaseCommand):
    help = "Create one InsightAgent per department (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="List agents and exit.")

    def handle(self, *args, **options):
        if options["list"]:
            for a in InsightAgent.objects.all().order_by("key"):
                self.stdout.write(f"  {a.key:14} r{a.revision}  active={a.is_active}  {a.name}")
            return

        slugs = sorted(set(Department.objects.values_list("slug", flat=True)))
        created = 0
        for slug in slugs:
            if InsightAgent.objects.filter(key=slug).exists():
                self.stdout.write(f"  = {slug}: exists, skipped")
                continue
            dept_name = (
                Department.objects.filter(slug=slug)
                .values_list("name", flat=True).first() or slug.title()
            )
            prompt, knowledge = _PROFILES.get(slug, _GENERIC)
            InsightAgent.objects.create(
                key=slug,
                name=f"{dept_name} (departamento)",
                description=f"Análisis narrativo del reporte de {dept_name}.",
                model="",
                system_prompt=prompt,
                knowledge=knowledge,
                is_active=True,
            )
            created += 1
            self.stdout.write(self.style.SUCCESS(f"  + {slug}: created"))

        self.stdout.write(self.style.SUCCESS(f"Done. {created} agent(s) created."))
