"""Demo data for the load-control module on the DEMO club (tutorial videos).

Gives "Selección Chilena" what the planner needs, relative to today:
  - its category competes in Sub 20 this season (TeamSeason),
  - four official matches in the last 28 days with match GPS for every
    outfield player, by position (DFC/LAT/MC/EXT/DC; keepers are excluded by
    the module), some subbed off before 75',
  - next Saturday's match as a fixture, so the new week finds it.

Idempotent: re-running deletes what it created before (rows marked
origen=demo_carga, the club's microcycles) and builds it again.

    python manage.py seed_demo_carga            # dry run
    python manage.py seed_demo_carga --commit
"""
from __future__ import annotations

import random
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Bracket, Category, Club, Player, TeamSeason
from events.models import Event
from exams.models import ExamResult, ExamTemplate
from load_control.models import Microcycle

CLUB = "Selección Chilena"
ORIGEN = "demo_carga"
HOJA = "U20"

# Mean per position group of a full match: DT, HSR >20, Sprint >25, ACC, DEC.
PERFIL = {
    "DEFENSA CENTRAL": (9400, 420, 110, 42, 55),
    "DEFENSA LATERAL": (10400, 820, 260, 58, 62),
    "MEDIOCAMPISTA": (11300, 690, 150, 52, 60),
    "EXTREMO": (10700, 960, 330, 64, 58),
    "CENTRO DELANTERO": (9900, 760, 240, 50, 52),
}
RIVALES = ["ARGENTINA", "URUGUAY", "PARAGUAY", "BOLIVIA"]
PROXIMO = "PERÚ"


def _posicion(position: str, i: int) -> str:
    if position == "Arquero":
        return "GUARDAMETA"
    if position == "Defensor":
        return "DEFENSA CENTRAL" if i % 2 == 0 else "DEFENSA LATERAL"
    if position == "Mediocampista":
        return "MEDIOCAMPISTA" if i % 4 else "EXTREMO"
    return "EXTREMO" if i % 2 else "CENTRO DELANTERO"


class Command(BaseCommand):
    help = "Seed load-control demo data (matches + GPS) on the demo club."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, commit=False, **opts):
        club = Club.objects.filter(name=CLUB).first()
        if club is None:
            raise CommandError(f"No existe el club demo «{CLUB}».")
        category = Category.objects.filter(club=club).order_by("name").first()
        template = ExamTemplate.objects.filter(slug="gps_partido", department__club=club).first()
        bracket = Bracket.objects.get(code="sub_20")
        if category is None or template is None:
            raise CommandError("El club demo necesita una categoría y la plantilla gps_partido.")

        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        saturdays = [monday - timedelta(days=2 + 7 * k) for k in range(4)][::-1]
        upcoming = monday + timedelta(days=5)
        rng = random.Random(20)

        with transaction.atomic():
            Microcycle.objects.filter(club=club).delete()
            ExamResult.objects.filter(template=template, result_data__origen=ORIGEN).delete()
            Event.objects.filter(club=club, metadata__origen=ORIGEN).delete()
            TeamSeason.objects.update_or_create(team=category, season=today.year,
                                                defaults={"bracket": bracket})

            def match(day, rival):
                return Event.objects.create(
                    club=club, department=template.department, event_type=Event.TYPE_MATCH,
                    title=f"Chile vs {rival.title()}",
                    starts_at=timezone.make_aware(datetime.combine(day, time(16))),
                    scope=Event.SCOPE_CATEGORY, category=category, bracket=bracket,
                    metadata={"origen": ORIGEN, "opponent": rival})

            players = list(Player.objects.filter(category=category).select_related("position")
                           .order_by("last_name", "first_name"))
            rows = []
            for day, rival in zip(saturdays, RIVALES):
                event = match(day, rival)
                for i, p in enumerate(players):
                    pos = _posicion(p.position.name if p.position else "", i)
                    if pos == "GUARDAMETA" or rng.random() < 0.12:  # keepers / not called up
                        continue
                    minutes = 90 if rng.random() > 0.25 else rng.choice([28, 45, 61, 70])
                    share = minutes / 90
                    dt, hsr, spr, acc, dec = (v * share * rng.uniform(0.9, 1.1) for v in PERFIL[pos])
                    rows.append(ExamResult(
                        template=template, player=p, event=event,
                        recorded_at=timezone.make_aware(datetime.combine(day, time(17))),
                        result_data={
                            "origen": ORIGEN, "origen_hoja": HOJA, "origen_codigo": "MD OFICIAL",
                            "match_type": "official", "posicion_hoja": pos, "opponent": rival,
                            "tot_dur": minutes, "tot_dist": round(dt), "hsr": round(hsr),
                            "sprint_dist": round(spr), "acc": round(acc), "dec": round(dec),
                        }))
            ExamResult.objects.bulk_create(rows)
            match(upcoming, PROXIMO)

            self.stdout.write(
                f"{len(rows)} filas GPS de partido en {len(saturdays)} partidos "
                f"({saturdays[0]} → {saturdays[-1]}); próximo: {upcoming} vs {PROXIMO}.")
            if not commit:
                transaction.set_rollback(True)
                self.stdout.write("Dry run: nada guardado (usa --commit).")
