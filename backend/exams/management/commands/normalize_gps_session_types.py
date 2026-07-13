"""Collapse GPS session types to the simplified taxonomy (client, 2026-07-13).

After `seed_gps_session` reduces `gps_sesion` to {entrenamiento, reintegro}
(and `seed_gps_partido` drops the field), existing rows and alert-rule scopes
may still carry the old values (amistoso / tareas / otro / partido). This
one-off, idempotent cleanup:

  * remaps any `gps_sesion` result whose `tipo_sesion` is not entrenamiento /
    reintegro → "entrenamiento";
  * rewrites any `gps_sesion` AlertRule scope `session_types` to drop the
    removed values.

Dry-run by default; pass --commit to write. Safe to re-run (a clean DB
reports 0 changes).

    docker compose exec backend python manage.py normalize_gps_session_types --commit
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from exams.models import ExamResult
from goals.models import AlertRule

_KEEP = {"entrenamiento", "reintegro"}


class Command(BaseCommand):
    help = "Collapse legacy gps_sesion tipo_sesion values + rule scopes to {entrenamiento, reintegro}."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None, help="Restrict to one club (name).")
        parser.add_argument("--commit", action="store_true", help="Write changes (default: dry-run).")

    @transaction.atomic
    def handle(self, *args, **opts):
        commit = opts["commit"]
        results = ExamResult.objects.filter(template__slug="gps_sesion")
        rules = AlertRule.objects.filter(template__slug="gps_sesion")
        if opts["club"]:
            results = results.filter(template__department__club__name=opts["club"])
            rules = rules.filter(template__department__club__name=opts["club"])

        before: Counter = Counter()
        remapped = 0
        for er in results.iterator(chunk_size=500):
            data = er.result_data or {}
            t = data.get("tipo_sesion")
            before[t] += 1
            if t is not None and t not in _KEEP:
                remapped += 1
                if commit:
                    data["tipo_sesion"] = "entrenamiento"
                    er.result_data = data
                    er.save(update_fields=["result_data"])

        scope_fixed = 0
        for r in rules:
            sc = r.scope or {}
            st = sc.get("session_types")
            if st and any(x not in _KEEP for x in st):
                scope_fixed += 1
                if commit:
                    sc["session_types"] = [x for x in st if x in _KEEP] or ["entrenamiento"]
                    r.scope = sc
                    r.save(update_fields=["scope"])

        mode = "" if commit else "[DRY RUN] "
        self.stdout.write(f"{mode}tipo_sesion before: {dict(before)}")
        self.stdout.write(self.style.SUCCESS(
            f"{mode}results remapped → entrenamiento: {remapped}; "
            f"alert-rule scopes fixed: {scope_fixed}"
        ))
