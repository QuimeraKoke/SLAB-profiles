"""Seed the Chile men's national team (La Roja) 2026 squad.

Mirrors `seed_uchile_2026`: idempotent insert/update of players into the
target club + category, with squad numbers stored as
`PlayerAlias(kind='squad_number')`. Roster = Nicolás Córdova's May/June 2026
call-up (FIFA-window friendlies). All players carry nationality "Chile".

Run after the skeleton exists (club + category + POR/DF/MC/DEL positions):

    python manage.py seed_uchile_skeleton --club-name "Selección Chilena" --category-name "Selección Nacional"
    python manage.py seed_chile_roster
"""
from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Player, PlayerAlias, Position


@dataclass(frozen=True)
class RosterEntry:
    jersey: int
    first_name: str
    last_name: str
    position_abbr: str  # POR, DF, MC, DEL


# Nicolás Córdova's 2026 call-up (26). Positions mapped to the platform's
# four canonical buckets (arquero/defensa/mediocampista/delantero).
ROSTER: list[RosterEntry] = [
    # Arqueros
    RosterEntry(1,  "Lawrence", "Vigouroux", "POR"),
    RosterEntry(12, "Brayan",   "Cortés",    "POR"),
    RosterEntry(23, "Thomas",   "Gillier",   "POR"),
    # Defensas
    RosterEntry(2,  "Guillermo", "Maripán",   "DF"),
    RosterEntry(3,  "Gabriel",   "Suazo",     "DF"),
    RosterEntry(4,  "Francisco", "Sierralta", "DF"),
    RosterEntry(5,  "Igor",      "Lichnovsky","DF"),
    RosterEntry(6,  "Iván",      "Román",     "DF"),
    RosterEntry(13, "Matías",    "Pérez",     "DF"),
    RosterEntry(15, "Felipe",    "Faúndez",   "DF"),
    RosterEntry(18, "Francisco", "Salinas",   "DF"),
    RosterEntry(22, "Diego",     "Ulloa",     "DF"),
    # Volantes
    RosterEntry(8,  "Rodrigo",   "Echeverría","MC"),
    RosterEntry(20, "Víctor",    "Méndez",    "MC"),
    RosterEntry(14, "Vicente",   "Pizarro",   "MC"),
    RosterEntry(16, "Felipe",    "Loyola",    "MC"),
    RosterEntry(19, "Matías",    "Sepúlveda", "MC"),
    RosterEntry(21, "Lautaro",   "Millán",    "MC"),
    RosterEntry(24, "Agustín",   "Arce",      "MC"),
    RosterEntry(26, "Nils",      "Reichmuth", "MC"),
    # Delanteros
    RosterEntry(7,  "Maximiliano","Gutiérrez","DEL"),
    RosterEntry(11, "Darío",     "Osorio",    "DEL"),
    RosterEntry(9,  "Gonzalo",   "Tapia",     "DEL"),
    RosterEntry(17, "Iván",      "Morales",   "DEL"),
    RosterEntry(10, "Lucas",     "Cepeda",    "DEL"),
    RosterEntry(25, "Clemente",  "Montes",    "DEL"),
]


class Command(BaseCommand):
    help = "Seed the Chile national team 2026 squad into the target club/category."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Selección Chilena")
        parser.add_argument("--category", default="Selección Nacional")

    @transaction.atomic
    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if not club:
            raise CommandError(f"Club '{opts['club']}' not found. Run seed_uchile_skeleton first.")
        category = Category.objects.filter(club=club, name=opts["category"]).first()
        if not category:
            raise CommandError(f"Category '{opts['category']}' not found in {club.name}.")

        positions = self._ensure_positions(club)

        created = updated = aliases = 0
        for entry in ROSTER:
            player, was_created = Player.objects.get_or_create(
                category=category,
                first_name=entry.first_name,
                last_name=entry.last_name,
                defaults={
                    "nationality": "Chile",
                    "position": positions[entry.position_abbr],
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                changed = False
                if player.nationality != "Chile":
                    player.nationality = "Chile"; changed = True
                if player.position_id != positions[entry.position_abbr].id:
                    player.position = positions[entry.position_abbr]; changed = True
                if not player.is_active:
                    player.is_active = True; changed = True
                if changed:
                    player.save(); updated += 1

            _, alias_created = PlayerAlias.objects.get_or_create(
                player=player,
                kind=PlayerAlias.KIND_SQUAD_NUMBER,
                source=PlayerAlias.SOURCE_MANUAL,
                value=str(entry.jersey),
            )
            if alias_created:
                aliases += 1

        self.stdout.write(self.style.SUCCESS(
            f"[{club.name} / {category.name}] players: +{created} created, "
            f"~{updated} updated, squad-number aliases: +{aliases} "
            f"({len(ROSTER)} in roster)."
        ))

    def _ensure_positions(self, club: Club) -> dict[str, Position]:
        defaults = [
            ("POR", "Portero",       "Arquero",       1),
            ("DF",  "Defensa",       "Defensa",       2),
            ("MC",  "Mediocampista", "Mediocampista", 3),
            ("DEL", "Delantero",     "Delantero",     4),
        ]
        out: dict[str, Position] = {}
        for abbr, name, role, sort_order in defaults:
            pos, _ = Position.objects.get_or_create(
                club=club, abbreviation=abbr,
                defaults={"name": name, "role": role, "sort_order": sort_order},
            )
            out[abbr] = pos
        return out
