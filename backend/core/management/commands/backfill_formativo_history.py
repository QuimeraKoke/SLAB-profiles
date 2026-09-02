"""Give every Formativo player a membership with a real start date.

Phase 3 of PLAN_FORMATIVO.md, consuming `formativo_historial.csv` from
`backend/scripts/build_formativo_master.py`. Dry-run by default:

    docker compose exec backend python manage.py backfill_formativo_history \\
        --csv /tmp/historial.csv --club "Universidad de Chile"
    # ... read the report, then add --commit

What phase 3 turned out to be
-----------------------------
The plan called this "membership spells from history", expecting players to
show two spells when they changed category. With cohort categories that case
barely exists: a Serie 2013 player stays Serie 2013 forever. What moves is the
*bracket*, and `TeamSeason` already models that per season.

The workbooks make the point plainly. 248 of 501 players invert to a birth
cohort that changes across seasons — `CLEMENTE SALAS` reads 2006, 2007 and 2008
across 2024–2026 — not because anyone moved, but because he was Sub 18 for
three straight years while his cohort aged underneath him. Reading that as
three memberships would invent transfers that never happened.

So what this command actually does is the part that was genuinely missing:

* **A membership for the 169 players phase 2 created**, who have none at all.
* **A real `since`** — the first dated appearance in the club's own session
  data — replacing the 55 rows whose reason still reads "fecha estimada".

Call-ups are reported, not written
----------------------------------
272 players turn out for a rung above their own somewhere in the data, which
under the two-scopes rule is a call-up rather than a change of home category.
They are NOT written unless `--call-ups` is passed, and then only inactive:

* `PlayerCallUp.active=True` widens data access for that category's staff
  (`api.scoping.scope_players`). Granting that to 272 people from a spreadsheet
  is an access-control change, not a data import.
* 56 call-ups already exist, created deliberately through the UI. Burying them
  under seventy spreadsheet-derived rows makes the real ones unfindable.
* Only the current season is considered even then. A Sub 16 appearance in 2024
  is history, and `PlayerCallUp` has no end date to express that with.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Bracket, Category, Club, Player, PlayerCallUp
from core.models import PlayerTeamMembership as Membership

REASON = "primera aparición en datos del club"
# Reasons written by `backfill_cohorts` when it had nothing better to go on.
ESTIMATED_REASONS = ("estimada", "sin partidos")


def norm(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", text).split())


class Command(BaseCommand):
    help = "Backfill player memberships with real first-appearance dates."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=Path, required=True)
        parser.add_argument("--club", required=True)
        parser.add_argument("--season", type=int, default=date.today().year)
        parser.add_argument("--commit", action="store_true")
        parser.add_argument(
            "--call-ups", action="store_true",
            help=("Además, crear PlayerCallUp INACTIVOS para quienes jugaron "
                  "sobre su serie en la temporada indicada."))

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        if not opts["csv"].exists():
            raise CommandError(f"No existe {opts['csv']}.")

        rows = list(csv.DictReader(opts["csv"].open(encoding="utf-8-sig"),
                                  delimiter=";"))
        if not rows:
            raise CommandError("El CSV de historial está vacío.")

        por_jugador: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            por_jugador[norm(row["nombre"])].append(row)

        report: dict[str, list] = defaultdict(list)
        with transaction.atomic():
            self._run(club, por_jugador, opts, report)
            if not opts["commit"]:
                transaction.set_rollback(True)
        self._print(report, opts, len(por_jugador))

    def _index(self, club) -> dict[str, Player]:
        """Phase 2 filled in the maternal surnames, so exact names now match.

        Both the two-token and three-token forms are indexed because the club
        writes some players without the maternal surname in the same sheet.
        """
        index: dict[str, Player] = {}
        for player in Player.objects.filter(category__club=club).select_related(
                "category"):
            largo = norm(f"{player.first_name} {player.last_name} "
                         f"{player.second_last_name}")
            index[largo] = player
            index.setdefault(norm(f"{player.first_name} {player.last_name}"),
                             player)
        return index

    def _run(self, club, por_jugador, opts, report):
        index = self._index(club)
        season = opts["season"]
        ladder = Bracket.ladder()
        by_rung = {b.age: b for b in ladder if b.age is not None}

        for nombre, filas in sorted(por_jugador.items()):
            player = index.get(nombre)
            if player is None:
                report["sin_jugador"].append(nombre)
                continue

            primera = min(date.fromisoformat(f["primera"]) for f in filas)
            self._membership(player, primera, report)
            if opts["call_ups"]:
                self._call_ups(player, filas, season, by_rung, club, report)

    def _membership(self, player, primera, report):
        spell = (player.team_memberships.order_by("since").first())
        if spell is None:
            Membership.objects.create(player=player, team=player.category,
                                      since=primera, reason=REASON)
            report["pertenencia_creada"].append(f"{player} · desde {primera}")
            return
        if primera >= spell.since:
            return
        # `since` is a lower bound on when the spell began, so the earliest
        # evidence always wins — this is not two facts in conflict.
        #
        # 219 of these came from `backfill_cohorts`, which used the first
        # MATCH. A training session or test on an earlier date proves the
        # player was already with the team, so the match date was simply the
        # earliest thing that command could see. Playing up does not change
        # the home team either, so an appearance for a higher bracket is still
        # evidence of being at the club.
        estimada = any(t in (spell.reason or "") for t in ESTIMATED_REASONS)
        report["fecha_afinada" if estimada else "fecha_adelantada"].append(
            f"{player}: {spell.since} → {primera}")
        spell.since = primera
        spell.reason = REASON
        spell.save(update_fields=["since", "reason"])

    def _call_ups(self, player, filas, season, by_rung, club, report):
        propios = {f["bracket"] for f in filas
                   if str(f["temporada"]) == str(season) and not f["sobre_su_serie"]}
        for fila in filas:
            if str(fila["temporada"]) != str(season) or not fila["sobre_su_serie"]:
                continue
            rung = int(fila["bracket"].split()[-1])
            bracket = by_rung.get(rung)
            if bracket is None:
                report["bracket_desconocido"].append(fila["bracket"])
                continue
            destino = self._category_for(club, bracket, season)
            if destino is None:
                report["sin_categoria_destino"].append(
                    f"{player} → {fila['bracket']} {season}")
                continue
            if destino.id == player.category_id:
                continue
            existente = PlayerCallUp.objects.filter(
                player=player, category=destino).first()
            if existente:
                report["citacion_ya_existia"].append(f"{player} → {destino.name}")
                continue
            PlayerCallUp.objects.create(
                player=player, category=destino, active=False,
                since=date.fromisoformat(fila["primera"]),
                note=(f"{fila['sesiones']} sesiones en {fila['bracket']} "
                      f"({fila['primera']}→{fila['ultima']}), planilla del club"))
            report["citacion_creada"].append(
                f"{player} → {destino.name} ({fila['sesiones']} ses, inactiva)")
        if propios:
            report["_propios"].append(propios)

    def _category_for(self, club, bracket, season):
        """The club's category playing `bracket` in `season`.

        Goes through `TeamSeason` rather than guessing from the label, so the
        Sub 20 squad resolves to whatever the club actually calls it — `SUB-20`
        here, not a `Serie 2006` that does not exist.
        """
        team_season = bracket.team_seasons.filter(
            season=season, team__club=club).select_related("team").first()
        return team_season.team if team_season else None

    def _print(self, report, opts, total):
        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{modo} · {total} jugadores en el historial\n"))
        orden = [
            ("pertenencia_creada", "Pertenencias creadas", self.style.SUCCESS),
            ("fecha_afinada", "Fechas estimadas reemplazadas por reales", self.style.SUCCESS),
            ("citacion_creada", "Citaciones creadas (inactivas)", self.style.SUCCESS),
            ("citacion_ya_existia", "Citaciones que ya existían", self.style.WARNING),
            ("fecha_adelantada", "Fechas adelantadas (había aparición anterior al 1er partido)", self.style.SUCCESS),
            ("sin_categoria_destino", "Sin categoría para ese bracket/temporada", self.style.WARNING),
            ("bracket_desconocido", "Bracket fuera de la escalera", self.style.WARNING),
            ("sin_jugador", "Sin jugador en SLAB (jugadores a prueba: no se importan)", self.style.WARNING),
        ]
        for key, title, style in orden:
            items = report.get(key) or []
            if not items:
                continue
            self.stdout.write(style(f"{title}: {len(items)}"))
            for item in items[:10]:
                self.stdout.write(f"    {item}")
            if len(items) > 10:
                self.stdout.write(f"    … y {len(items) - 10} más")
            self.stdout.write("")
        if not opts["call_ups"]:
            self.stdout.write(self.style.WARNING(
                "Citaciones NO escritas. Con --call-ups se crean inactivas "
                "(sin efecto en accesos) para quienes jugaron sobre su serie."))
