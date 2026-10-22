"""Bands the MD+2 screen needs and two templates lacked (`api/md2.py`).

* CK (`ck.valor`, U/L) had no bands anywhere. Defaults, editable later as
  the field's reference ranges or per-category alert rules:
  < 500 Normal · 500–1.000 Elevada · ≥ 1.000 Alta.
* Hydration data lives in `densidad_urinaria` (the team-table template the
  club fills), but its bands live in `fase_densidad`. The bands (and the
  g/mL unit) are copied over — the same numbers, one place to read them.

In place, add-only: a field that already has bands keeps them. Plan by
default; --commit writes.

    docker compose exec backend python manage.py seed_md2
    docker compose exec backend python manage.py seed_md2 --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from exams.models import ExamTemplate

CK_BANDAS = [
    {"label": "Normal", "max": 500, "color": "#16a34a"},
    {"label": "Elevada", "min": 500, "max": 1000, "color": "#f59e0b"},
    {"label": "Alta", "min": 1000, "color": "#dc2626", "alert": True},
]
DENSIDAD_POR_DEFECTO = [
    {"label": "Hidratado", "max": 1.02, "color": "#16a34a"},
    {"label": "Amarillo", "min": 1.02, "max": 1.03, "color": "#f59e0b"},
    {"label": "Deshidratado", "min": 1.03, "color": "#dc2626", "alert": True},
]


class Command(BaseCommand):
    help = "Bandas de CK y densidad urinaria para la pantalla MD+2."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None, help="Por defecto, todos los clubes.")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        qs = ExamTemplate.objects.filter(is_active_version=True)
        if opts["club"]:
            qs = qs.filter(department__club__name=opts["club"])
        with transaction.atomic():
            for t in qs.filter(slug="ck"):
                self._bandas(t, "valor", CK_BANDAS, unidad="U/L", direccion="down")
            for t in qs.filter(slug="densidad_urinaria"):
                fuente = qs.filter(slug="fase_densidad", department__club=t.department.club).first()
                bandas = next((f.get("reference_ranges") for f in
                               ((fuente.config_schema or {}).get("fields") or [] if fuente else [])
                               if f.get("key") == "densidad_urinaria" and f.get("reference_ranges")),
                              DENSIDAD_POR_DEFECTO)
                self._bandas(t, "densidad_urinaria", bandas, unidad="g/mL", direccion="down")
            if not opts["commit"]:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS("APLICADO" if opts["commit"] else "PLAN — repetir con --commit"))

    def _bandas(self, t, key, bandas, *, unidad, direccion):
        schema = t.config_schema or {}
        campo = next((f for f in schema.get("fields") or [] if f.get("key") == key), None)
        club = t.department.club.name
        if campo is None:
            self.stdout.write(f"  {club} · {t.slug}: sin campo {key} — nada")
            return
        cambios = []
        if not campo.get("reference_ranges"):
            campo["reference_ranges"] = bandas
            cambios.append("bandas")
        if not campo.get("unit"):
            campo["unit"] = unidad
            cambios.append(f"unidad {unidad}")
        if not campo.get("direction_of_good"):
            campo["direction_of_good"] = direccion
            cambios.append("dirección")
        if cambios:
            t.config_schema = schema
            t.save(update_fields=["config_schema", "updated_at"])
            t.rebuild_template_fields()
        self.stdout.write(f"  {club} · {t.slug}.{key}: {', '.join(cambios) or 'ya estaba'}")
