"""Seed sample CMJ / Nórdico / Fuerza isométrica readings so the strength
templates flow end-to-end through the médico report (bands, squad percentile,
evolution, agent narrative). Demo data only — deterministic (seeded RNG).

    python manage.py seed_strength_demo --club "Universidad de Chile" --category "Primer Equipo"
"""
from __future__ import annotations

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed demo CMJ/Nórdico/Iso readings for a category's players."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", default="Primer Equipo")
        parser.add_argument("--readings", type=int, default=3, help="Readings per template per player.")

    @transaction.atomic
    def handle(self, *args, **opts):
        from core.models import Category, Player
        from exams.models import ExamResult, ExamTemplate
        from dashboards.player_state import upsert_player_state

        rng = random.Random(42)  # deterministic
        cat = Category.objects.filter(name=opts["category"], club__name=opts["club"]).first()
        if cat is None:
            self.stderr.write(f"Category '{opts['category']}' not found in '{opts['club']}'.")
            return
        players = list(Player.objects.filter(category=cat, is_active=True))
        if not players:
            self.stderr.write("No active players in that category.")
            return

        templates = {}
        for slug in ("cmj", "nordico", "iso_prono"):
            t = ExamTemplate.objects.filter(
                slug=slug, department__slug="medico", is_active_version=True,
            ).first()
            if t is None:
                self.stderr.write(f"Missing médico template '{slug}' — run seed_medico_indicators first.")
                return
            templates[slug] = t

        def val(base: float, spread: float) -> float:
            return round(rng.uniform(base - spread, base + spread), 1)

        now = timezone.now()
        offsets = [i * 10 for i in range(opts["readings"])]  # 0, 10, 20… days ago
        rows: list = []
        for p in players:
            for off in offsets:
                ts = now - timedelta(days=off)
                cmj = val(42, 5)                       # 37–47 cm (spans the 40–45 band)
                nl, nr = val(375, 45), val(375, 45)    # 330–420 N
                il, ir = val(305, 30), val(305, 30)    # 275–335 N
                rows += [
                    ExamResult(player=p, template=templates["cmj"], recorded_at=ts,
                               result_data={"contramovimiento": cmj}),
                    ExamResult(player=p, template=templates["nordico"], recorded_at=ts,
                               result_data={"fuerza_izq": nl, "fuerza_der": nr,
                                            "asimetria": round(abs(nl - nr) / max(nl, nr) * 100, 1)}),
                    ExamResult(player=p, template=templates["iso_prono"], recorded_at=ts,
                               result_data={"fuerza_izq": il, "fuerza_der": ir, "protocolo": "extension",
                                            "asimetria": round(abs(il - ir) / max(il, ir) * 100, 1)}),
                ]
        ExamResult.objects.bulk_create(rows, batch_size=300)

        # bulk_create skips post_save signals — rebuild state for seeded players.
        for p in players:
            upsert_player_state(p)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(rows)} readings for {len(players)} players in {cat}; states rebuilt."
        ))
