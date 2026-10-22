"""Seed Nutrición's "Suplementación" exam: every supplement a player takes.

One record = the player's whole current regimen — every supplement he takes,
picked from the nutrition staff's list (a multiple-choice field) — in force
from its date until the next record changes it. So the latest record IS what
he takes today, and the history is when it changed. The form starts from
the previous record (`prefill_from_last`): a change is ticking or unticking,
not starting over.

"Otro" has a free-text box beside it (the forms have no conditional fields,
so it is always there, labelled for when "Otro" is ticked).

    docker compose exec backend python manage.py seed_suplementacion                # plan
    docker compose exec backend python manage.py seed_suplementacion --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate

SLUG = "suplementacion"
NOMBRE = "Suplementación"

# The nutrition staff's list (2026-08), in their order. Values are the labels:
# the department card and the exports show the stored value as-is.
SUPLEMENTOS = [
    "Proteína isolada whey", "Pre entrenamiento", "Creatina", "Cafeína", "Guaraná",
    "Curcumina", "Citrulina", "Colágeno hidrolizado", "Omega 3", "Vitamina C",
    "Complejo B", "B12", "Vitamina D", "Electrolitos", "Beta-alanina", "Magnesio",
    "Hierro", "Munocal", "Multivitamínico", "BCAA", "Proteína vegana", "Ashwagandha",
    "Nitratos", "Otro",
]

SCHEMA = {"fields": [
    {"key": "fecha", "label": "Vigente desde", "type": "date", "required": True,
     "group": "Suplementación"},
    {"key": "suplementos", "label": "Suplementos que consume", "type": "categorical",
     "multiple": True, "options": SUPLEMENTOS, "group": "Suplementación"},
    {"key": "otro", "label": "Otro (especificar)", "type": "text", "group": "Suplementación",
     "placeholder": "Si marcaste «Otro»: cuál, marca…"},
    {"key": "observaciones", "label": "Observaciones", "type": "text", "multiline": True,
     "rows": 3, "group": "Suplementación",
     "placeholder": "Dosis, momento del día, indicaciones…"},
]}
INPUT_CONFIG = {"input_modes": ["single"], "default_input_mode": "single",
                "modifiers": {"prefill_from_last": True}}


class Command(BaseCommand):
    help = "Crea o refresca la plantilla «Suplementación» de Nutrición."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None, help="Por defecto, todos los clubes.")
        parser.add_argument("--department-slug", default="nutricional")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        clubs = Club.objects.all()
        if opts["club"]:
            clubs = clubs.filter(name=opts["club"])
        if not clubs.exists():
            raise CommandError("No hay clubes para ese filtro.")
        with transaction.atomic():
            for club in clubs.order_by("name"):
                dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
                if dept is None:
                    self.stdout.write(f"  {club.name}: sin departamento {opts['department_slug']} — nada")
                    continue
                t = ExamTemplate.objects.filter(department=dept, slug=SLUG,
                                                is_active_version=True).first()
                accion = "refrescada" if t else "creada"
                if t is None:
                    t = ExamTemplate(department=dept, slug=SLUG, name=NOMBRE)
                else:
                    # Keep any option the club added in the template editor.
                    actual = next((f for f in (t.config_schema or {}).get("fields") or []
                                   if f.get("key") == "suplementos"), {})
                    extra = [o for o in actual.get("options") or [] if o not in SUPLEMENTOS]
                    if extra:
                        SCHEMA["fields"][1]["options"] = SUPLEMENTOS[:-1] + extra + ["Otro"]
                t.name = NOMBRE
                t.config_schema = SCHEMA
                t.input_config = INPUT_CONFIG
                t.save()
                t.rebuild_template_fields()
                cats = Category.objects.filter(club=club, departments=dept)
                t.applicable_categories.add(*cats)
                self.stdout.write(f"  {club.name}: {accion} · {len(SCHEMA['fields'][1]['options'])} "
                                  f"suplementos · {t.applicable_categories.count()} categorías")
            if not opts["commit"]:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS("APLICADO" if opts["commit"] else "PLAN — repetir con --commit"))
