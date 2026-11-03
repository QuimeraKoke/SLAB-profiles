"""Re-date matches that were played on another day than scheduled.

Until 2026-11-03 the COMET played-match pass refreshed an existing fixture's
metadata but not its date, so a postponed match kept its scheduled day while
its fichas (`ficha_partido`, recorded at the real kickoff) and the club's GPS
carried the day it was played — U20/U18 vs Cobreloa, round 12: Event on
12-oct, played 22-oct. `comet_sync.played_kickoff_wins` fixes it going
forward; this fixes the matches already stored, by the same rule: a match with
fichas is dated by their kickoff.

    docker compose exec backend python manage.py fix_postponed_match_dates            # plan
    docker compose exec backend python manage.py fix_postponed_match_dates --commit
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.localtime import local_tz
from core.models import Club
from events.models import Event
from exams.models import ExamResult
from exams.services.comet_sync import played_kickoff_wins


class Command(BaseCommand):
    help = "Corrige la fecha de los partidos postergados según sus fichas COMET."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError("Club no encontrado.")
        kickoffs: dict = defaultdict(Counter)
        for event_id, rec in ExamResult.objects.filter(
            template__slug="ficha_partido", event__club=club,
        ).values_list("event_id", "recorded_at"):
            kickoffs[event_id][rec] += 1

        cambios = []
        for event in Event.objects.filter(pk__in=list(kickoffs)).select_related("category"):
            antes = event.starts_at
            if played_kickoff_wins(event, kickoffs[event.pk].most_common(1)[0][0]):
                cambios.append((event, antes))

        modo = "APLICADO" if opts["commit"] else "PLAN (sin cambios; usar --commit)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"{modo}: {len(cambios)} partidos con otra fecha"))
        for event, antes in sorted(cambios, key=lambda c: c[0].starts_at):
            self.stdout.write(
                f"  {antes.astimezone(local_tz()):%d-%m-%Y} → {event.starts_at.astimezone(local_tz()):%d-%m-%Y %H:%M}"
                f"  {event.category.name if event.category else '—':14} {event.title}")
        if opts["commit"] and cambios:
            with transaction.atomic():
                Event.objects.bulk_update([e for e, _ in cambios], ["starts_at", "updated_at"])
