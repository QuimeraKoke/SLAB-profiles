"""Recompute every episode's state with the current "latest result" rule.

Episodes whose stage change was saved but lost a timestamp tie (see
`exams.episode_lifecycle.latest_result`) stay wrong until something touches
them again. This re-derives stage / status / title / ended_at from their
results, recomputes the players' status, and — like "Dar de alta" does —
marks a player available on the day an episode it closes was discharged,
when no availability was recorded.

It cannot fix an episode whose last-saved change is dated BEFORE an existing
result (a typo'd future date beat a discharge): that needs someone to decide
which date was meant, so it is listed, not changed.

    docker compose exec backend python manage.py repair_episode_states            # dry run
    docker compose exec backend python manage.py repair_episode_states --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from exams.episode_lifecycle import latest_result, recompute_player_status, refresh_episode_from_results
from exams.models import Episode, ExamResult


class Command(BaseCommand):
    help = "Recalcula el estado de los episodios con la regla del último resultado."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        cambios, revisar = [], []
        with transaction.atomic():
            for ep in Episode.objects.select_related("player", "template").order_by("started_at"):
                antes = (ep.stage, ep.status)
                refresh_episode_from_results(ep)
                ep.refresh_from_db()
                if (ep.stage, ep.status) != antes:
                    if ep.status == Episode.STATUS_CLOSED and ep.available_at is None:
                        ep.available_at = ep.ended_at
                        ep.save(update_fields=["available_at", "updated_at"])
                    recompute_player_status(ep.player)
                    cambios.append(f"{ep.player} · {ep.template.name} desde {ep.started_at:%d/%m/%Y}: "
                                   f"{antes[0]}/{antes[1]} → {ep.stage}/{ep.status}")
                ultimo = (ExamResult.objects.filter(episode=ep).order_by("-created_at").first())
                vigente = latest_result(ep)
                if ultimo and vigente and ultimo.pk != vigente.pk and \
                        ultimo.result_data.get("stage") != vigente.result_data.get("stage"):
                    revisar.append(
                        f"{ep.player} · {ep.template.name}: lo último guardado es "
                        f"'{ultimo.result_data.get('stage')}' con fecha {ultimo.recorded_at:%d/%m/%Y}, "
                        f"pero hay '{vigente.result_data.get('stage')}' con fecha posterior "
                        f"({vigente.recorded_at:%d/%m/%Y})")
            if not opts["commit"]:
                transaction.set_rollback(True)

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nAPLICADO\n" if opts["commit"] else "\nSIMULACIÓN (sin --commit no escribe)\n"))
        self.stdout.write(self.style.SUCCESS(f"  episodios corregidos: {len(cambios)}"))
        for c in cambios:
            self.stdout.write(f"    {c}")
        if revisar:
            self.stdout.write(self.style.WARNING(
                f"\n  Para revisar a mano (fecha anterior a otro registro): {len(revisar)}"))
            for r in revisar:
                self.stdout.write(f"    {r}")
