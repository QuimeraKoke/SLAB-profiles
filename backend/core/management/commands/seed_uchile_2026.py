"""Seed the Universidad de Chile 2026 first-team squad.

Idempotent — if a player with the same full name already exists in the target
category they are updated rather than duplicated. Squad numbers are stored as
`PlayerAlias(kind='squad_number')` so a year-over-year reshuffle is just an
alias update, not a Player schema change. The player codes used by the GPS
exports are seeded as `kind='nickname'` aliases pointing at the matching
player; cantera/youth players appearing only in the GPS files are created in
the target category so their codes have something to resolve to.

Run with:

    docker compose exec backend python manage.py seed_uchile_2026
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Player, PlayerAlias, Position


def _norm(text: str) -> str:
    """Lowercase + strip diacritics. Reconciles against a legacy roster that
    may store names in a different case/accent form (e.g. 'FABIAN HORMAZABAL'
    vs 'Fabián Hormazábal') so we update the existing player instead of
    creating a duplicate."""
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


@dataclass(frozen=True)
class RosterEntry:
    jersey: int
    first_name: str
    last_name: str
    nationality: str
    position_abbr: str  # one of POR, DF, MC, DEL


# 2026 first-team squad (Wikipedia, "Plantilla 2026" table).
ROSTER: list[RosterEntry] = [
    # Goalkeepers
    RosterEntry(1,  "Cristopher", "Toselli",   "Chile", "POR"),
    RosterEntry(25, "Gabriel",    "Castellón", "Chile", "POR"),
    RosterEntry(30, "Ignacio",    "Sáez",      "Chile", "POR"),
    # Defenders
    RosterEntry(2,  "Franco",      "Calderón",   "Argentina", "DF"),
    RosterEntry(4,  "Diego",       "Vargas",     "Chile",     "DF"),
    RosterEntry(5,  "Nicolás",     "Ramírez",    "Chile",     "DF"),
    RosterEntry(6,  "Nicolás",     "Fernández",  "Chile",     "DF"),
    RosterEntry(14, "Marcelo",     "Morales",    "Chile",     "DF"),
    RosterEntry(15, "Felipe",      "Salomoni",   "Argentina", "DF"),
    RosterEntry(17, "Fabián",      "Hormazábal", "Chile",     "DF"),
    RosterEntry(22, "Matías",      "Zaldivia",   "Chile",     "DF"),
    RosterEntry(31, "Bianneider",  "Tamayo",     "Venezuela", "DF"),
    # Midfielders
    RosterEntry(8,  "Israel",      "Poblete",    "Chile",     "MC"),
    RosterEntry(10, "Lucas",       "Assadi",     "Chile",     "MC"),
    RosterEntry(16, "Elías",       "Rojas",      "Chile",     "MC"),
    RosterEntry(19, "Javier",      "Altamirano", "Chile",     "MC"),
    RosterEntry(20, "Charles",     "Aránguiz",   "Chile",     "MC"),
    RosterEntry(21, "Marcelo",     "Díaz",       "Chile",     "MC"),
    RosterEntry(23, "Ignacio",     "Vásquez",    "Chile",     "MC"),
    RosterEntry(24, "Lucas",       "Romero",     "Paraguay",  "MC"),
    RosterEntry(26, "Matías",      "Riquelme",   "Chile",     "MC"),
    RosterEntry(28, "Agustín",     "Arce",       "Chile",     "MC"),
    RosterEntry(29, "Lucas",       "Barrera",    "Argentina", "MC"),
    # Forwards
    RosterEntry(7,  "Maximiliano",  "Guerrero",  "Chile",     "DEL"),
    RosterEntry(9,  "Octavio",      "Rivero",    "Uruguay",   "DEL"),
    RosterEntry(11, "Eduardo",      "Vargas",    "Chile",     "DEL"),
    RosterEntry(13, "Jhon",         "Cortés",    "Chile",     "DEL"),
    RosterEntry(18, "Juan",         "Lucero",    "Argentina", "DEL"),  # legacy record is "Juan Lucero"
    RosterEntry(27, "Andrés",       "Bolaño",    "Venezuela", "DEL"),
    RosterEntry(32, "Martín",       "Espinoza",  "Chile",     "DEL"),
]


# Players appearing in the GPS exports who are NOT in the Wikipedia first-team
# table — youth / cantera promotions who trained and played with the squad.
# Created in the target category (no jersey, position TBD) so their GPS codes
# have something to resolve to. Idempotent get_or_create by full name.
CANTERANOS: list[tuple[str, str]] = [
    ("Vicente",   "Ramírez"),   # VicRam — youth; distinct from Nicolás Ramírez
    ("Cristóbal", "Ulloa"),     # CrisUll
    ("Renato",    "Huerta"),    # RenHue
]


# Codes used by the GPS exports. Each code maps to a (first_name, last_name)
# pair so the alias seeder can resolve the right Player regardless of
# jersey-number changes year over year. The export sometimes labels the same
# player two different ways across a season (e.g. "NicFer" and "Fernandez") —
# both are seeded as separate aliases pointing at the one player, which is
# exactly what the bulk matcher's many-aliases-to-one-player model expects.
GPS_NICKNAMES: dict[str, tuple[str, str]] = {
    # --- First-team roster ---
    "AguArc": ("Agustín", "Arce"),
    "AndBol": ("Andrés", "Bolaño"),
    "Charle": ("Charles", "Aránguiz"),
    "Cortes": ("Jhon", "Cortés"),
    "DieVar": ("Diego", "Vargas"),
    "EduVar": ("Eduardo", "Vargas"),
    "EliRoj": ("Elías", "Rojas"),
    "FabHor": ("Fabián", "Hormazábal"),
    "FelSal": ("Felipe", "Salomoni"),
    "Fernandez": ("Nicolás", "Fernández"),   # alt label for NicFer
    "FraCal": ("Franco", "Calderón"),
    "IgnVas": ("Ignacio", "Vásquez"),
    "IsraPo": ("Israel", "Poblete"),
    "JavAlt": ("Javier", "Altamirano"),
    "LucAss": ("Lucas", "Assadi"),
    "LucBar": ("Lucas", "Barrera"),
    "LucRom": ("Lucas", "Romero"),
    "Lucero": ("Juan", "Lucero"),
    "MarDia": ("Marcelo", "Díaz"),
    "MarEsp": ("Martín", "Espinoza"),
    "MarMor": ("Marcelo", "Morales"),
    "MatRiq": ("Matías", "Riquelme"),
    "MatZal": ("Matías", "Zaldivia"),
    "MaxGue": ("Maximiliano", "Guerrero"),
    "NicFer": ("Nicolás", "Fernández"),
    "NicRam": ("Nicolás", "Ramírez"),
    "OctRiv": ("Octavio", "Rivero"),
    "Tamayo": ("Bianneider", "Tamayo"),   # bare last-name label
    # --- Cantera / youth (see CANTERANOS) ---
    "VicRam": ("Vicente", "Ramírez"),
    "CrisUll": ("Cristóbal", "Ulloa"),
    "RenHue": ("Renato", "Huerta"),
    # TODO: "AguKor" — appears in 1782419341661.xls (16 rows) but the player
    # behind the code is still unidentified. Add once confirmed.
}


class Command(BaseCommand):
    help = "Seed Universidad de Chile 2026 first-team roster + GPS-export aliases."

    def add_arguments(self, parser):
        parser.add_argument("--club",     default="Universidad de Chile")
        parser.add_argument("--category", default="Primer Equipo")

    @transaction.atomic
    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if not club:
            raise CommandError(f"Club '{opts['club']}' not found.")
        category = Category.objects.filter(club=club, name=opts["category"]).first()
        if not category:
            raise CommandError(f"Category '{opts['category']}' not found in {club.name}.")

        positions = self._ensure_positions(club)

        # Normalized-name index of existing players so we reconcile against a
        # legacy roster (different case/accents) instead of duplicating it.
        index: dict[str, Player] = {}
        for p in Player.objects.filter(category=category):
            index.setdefault(_norm(f"{p.first_name} {p.last_name}"), p)

        def get_or_make(first: str, last: str, defaults: dict):
            existing = index.get(_norm(f"{first} {last}"))
            if existing is not None:
                return existing, False
            created = Player.objects.create(
                category=category, first_name=first, last_name=last, **defaults,
            )
            index[_norm(f"{first} {last}")] = created
            return created, True

        created_players = 0
        updated_players = 0
        created_squad_aliases = 0
        for entry in ROSTER:
            player, created = get_or_make(
                entry.first_name, entry.last_name,
                {
                    "nationality": entry.nationality,
                    "position": positions[entry.position_abbr],
                    "is_active": True,
                },
            )
            if created:
                created_players += 1
            else:
                # Idempotent update — keep nationality + position aligned with the seed.
                changed = False
                if player.nationality != entry.nationality:
                    player.nationality = entry.nationality
                    changed = True
                if player.position_id != positions[entry.position_abbr].id:
                    player.position = positions[entry.position_abbr]
                    changed = True
                if not player.is_active:
                    player.is_active = True
                    changed = True
                if changed:
                    player.save()
                    updated_players += 1

            _, alias_created = PlayerAlias.objects.get_or_create(
                player=player,
                kind=PlayerAlias.KIND_SQUAD_NUMBER,
                source=PlayerAlias.SOURCE_MANUAL,
                value=str(entry.jersey),
            )
            if alias_created:
                created_squad_aliases += 1

        # Cantera / youth players present in the GPS exports but not on the
        # first-team table. Create them so their nickname aliases resolve.
        created_canteranos = 0
        for first, last in CANTERANOS:
            _, c = get_or_make(first, last, {"nationality": "Chile", "is_active": True})
            if c:
                created_canteranos += 1

        # GPS-file nickname aliases
        created_nickname_aliases = 0
        missing = []
        for code, (first, last) in GPS_NICKNAMES.items():
            player = index.get(_norm(f"{first} {last}"))
            if not player:
                missing.append(f"{code} -> {first} {last}")
                continue
            _, alias_created = PlayerAlias.objects.get_or_create(
                player=player,
                kind=PlayerAlias.KIND_NICKNAME,
                source=PlayerAlias.SOURCE_MANUAL,
                value=code,
            )
            if alias_created:
                created_nickname_aliases += 1

        self.stdout.write(self.style.SUCCESS(
            f"[{club.name} / {category.name}] "
            f"players: +{created_players} created, ~{updated_players} updated, "
            f"cantera: +{created_canteranos}, "
            f"squad-number aliases: +{created_squad_aliases}, "
            f"GPS nickname aliases: +{created_nickname_aliases}."
        ))
        if missing:
            self.stdout.write(self.style.WARNING(
                "Missing players for nicknames (skipped):\n  " + "\n  ".join(missing)
            ))

    def _ensure_positions(self, club: Club) -> dict[str, Position]:
        """Reuse existing DF/MC/DEL positions; create POR if missing.

        Doesn't touch a club's other positions (e.g. LAT) — the seed is
        additive so manual overrides like a "lateral" subtype survive.
        """
        defaults = [
            ("POR", "Portero",        "Arquero",       1),
            ("DF",  "Defensa",        "Defensa",       2),
            ("MC",  "Mediocampista",  "Mediocampista", 3),
            ("DEL", "Delantero",      "Delantero",     4),
        ]
        out: dict[str, Position] = {}
        for abbr, name, role, sort_order in defaults:
            position, _ = Position.objects.get_or_create(
                club=club, abbreviation=abbr,
                defaults={"name": name, "role": role, "sort_order": sort_order},
            )
            out[abbr] = position
        return out
