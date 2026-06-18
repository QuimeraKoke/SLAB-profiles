"""Seed the first InsightAgent: the player Resumen ("triage") narrative.

Gives staff an immediately-editable agent in the admin (prompt + knowledge
base) for the per-player Resumen PDF. The role prompt mirrors the built-in
default in `dashboards/pdf/narrative.py`; once this row exists it is what's
used. The JSON output contract is NOT here — it stays code-owned so prompt
edits can't break parsing.

Idempotent: skips if a 'triage' agent already exists. Reverse is a no-op so
a rollback never deletes staff-edited content.
"""
from __future__ import annotations

from django.db import migrations

_ROLE_PROMPT = (
    "Eres un analista de ciencias del deporte y del área médica de un club "
    "de fútbol profesional. Redactas fichas individuales para el cuerpo "
    "técnico y médico, en español (Chile), con un tono clínico, claro y "
    "accionable.\n\n"
    "Se te entregan los datos de seguimiento de un jugador (alertas activas, "
    "métricas alertadas, otras métricas con su evolución reciente y el último "
    "partido). A partir de SOLO esos datos, redacta una ficha narrativa.\n\n"
    "Reglas estrictas:\n"
    "- Usa únicamente la información provista. NO inventes métricas, valores, "
    "fechas, diagnósticos ni lesiones que no aparezcan en los datos.\n"
    "- Si no hay datos suficientes para una sección, dilo explícitamente en "
    "lugar de rellenar.\n"
    "- Interpreta las variaciones según 'direction_of_good' cuando esté "
    "presente (qué dirección es buena para cada métrica).\n"
    "- Sé conciso: el cuerpo técnico lee esto de un vistazo."
)

# Starter knowledge base — a template for staff to expand in the admin.
_STARTER_KNOWLEDGE = (
    "## Cómo interpretar (editar y ampliar este contenido en el admin)\n\n"
    "Esta base de conocimiento guía la *interpretación* de los datos; nunca "
    "debe introducir hechos sobre un jugador puntual.\n\n"
    "### Terminología\n"
    "- **CMJ**: salto con contramovimiento; proxy de potencia de tren inferior.\n"
    "- **IMO**: índice músculo-óseo.\n"
    "- **Σ6 pliegues**: sumatoria de 6 pliegues cutáneos (adiposidad).\n"
    "- **Check-IN**: cuestionario de bienestar subjetivo (sueño, fatiga, "
    "estrés, DOMS, ánimo).\n\n"
    "### Énfasis por prioridad\n"
    "1. Alertas críticas activas.\n"
    "2. Caídas de bienestar subjetivo sostenidas.\n"
    "3. Tendencias desfavorables de composición corporal.\n"
    "4. Disponibilidad competitiva (rol en el último partido).\n"
)


def seed(apps, schema_editor):
    InsightAgent = apps.get_model("dashboards", "InsightAgent")
    if InsightAgent.objects.filter(key="triage").exists():
        return
    InsightAgent.objects.create(
        key="triage",
        name="Resumen del jugador (Triage)",
        description="Narrativa de la ficha Resumen: resumen, hallazgos y objetivos.",
        model="",  # blank ⇒ settings.ANTHROPIC_MODEL
        system_prompt=_ROLE_PROMPT,
        knowledge=_STARTER_KNOWLEDGE,
        is_active=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("dashboards", "0022_insightagent"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
