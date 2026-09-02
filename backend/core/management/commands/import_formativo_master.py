"""Seed categories, players and aliases from the canonical Formativo master.

Phase 2 of PLAN_FORMATIVO.md. Reads the CSV produced by
`backend/scripts/build_formativo_master.py` and reconciles it against what is
already in the database. Dry-run by default:

    docker compose exec backend python manage.py import_formativo_master \\
        --csv /tmp/maestro.csv --club "Universidad de Chile" --season 2026
    # ... read the report, then:
    docker compose exec backend python manage.py import_formativo_master \\
        --csv /tmp/maestro.csv --club "Universidad de Chile" --season 2026 --commit

Matching: birth date first, name second
---------------------------------------
SLAB stores `first_name` + `last_name`; the club's workbooks write
`NOMBRE APELLIDO_PATERNO APELLIDO_MATERNO` in one cell. So exact-name matching
finds 36 of 423 players, and matching on the leading tokens alone would happily
merge the eight homonym pairs this club has (two Davids, a Sub 13 and a Sub 20
Tomás Mandiola, …).

The birth date settles it: 313 of 314 existing players have one, and keying on
it produced **zero** ambiguous matches across 423 master rows — 251 matched,
172 genuinely new. Token overlap is kept only as a guard, so that two different
people who happen to share a birth date are never merged.

The 215 matches whose master name is longer are not aliases — they are players
whose `second_last_name` was never filled in. Writing the real field (rather
than piling up alias rows) is what makes plain exact matching work for every
future import from these same workbooks.

What this command will NOT do without being asked
-------------------------------------------------
* **Move a player between categories** (`--reassign`). The master's cohort can
  disagree with the category a player currently sits in, and the fix is not
  always "trust the file": six such cases are one-year disagreements where
  either side could be right.
* **Move anyone out of a senior category**, ever. Formativo players who were
  promoted to Primer Equipo appear in these workbooks too, and reassigning them
  to their birth cohort would silently demote them off the senior roster.
* **Overwrite a birth date** (`--overwrite-dob`). Seven players differ between
  database and file, and several of those differences are day/month swaps —
  which means the file is wrong at least as often as the database.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Bracket, Category, Club, Player, Position

# The club's workbooks use six coarse positions; the club's own taxonomy is
# finer (Extremo derecho / izquierdo). The source does not say which side, so
# each maps to the unspecified variant — the same reason a generic "Lateral"
# already sits alongside "Lateral derecho"/"Lateral izquierdo".
POSITION_MAP = {
    "GUARDAMETA": ("POR", "Arquero", ""),
    "DEFENSA CENTRAL": ("DC", "Defensa central", "Específica"),
    "DEFENSA LATERAL": ("L", "Lateral", "General"),
    "MEDIOCAMPISTA": ("MC", "Mediocampista", ""),
    "EXTREMO": ("EX", "Extremo", "General"),
    "CENTRO DELANTERO": ("DEL", "Delantero", ""),
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", text).split())


def split_name(full: str) -> tuple[str, str, str]:
    """`JUAN PEREZ GONZALEZ` → (`Juan`, `Perez`, `Gonzalez`).

    Chilean convention: given name(s), then paternal then maternal surname.
    Two tokens means the maternal surname is simply absent, which is common in
    these files and must not be guessed at.
    """
    parts = full.split()
    if len(parts) == 1:
        return parts[0].title(), "", ""
    if len(parts) == 2:
        return parts[0].title(), parts[1].title(), ""
    # Three or more: everything before the last two is the given name, so
    # compound given names ("JOSE MIGUEL SOTO ROJAS") survive intact.
    return (" ".join(parts[:-2]).title(), parts[-2].title(), parts[-1].title())


class Command(BaseCommand):
    help = "Create categories, players and aliases from the Formativo master CSV."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=Path, required=True)
        parser.add_argument("--club", required=True)
        parser.add_argument("--season", type=int, default=date.today().year)
        parser.add_argument("--commit", action="store_true",
                            help="Write. Without it, only reports.")
        parser.add_argument("--reassign", action="store_true",
                            help="Move matched players to their cohort's category.")
        parser.add_argument("--overwrite-dob", action="store_true",
                            help="Let the file's birth date win over the database's.")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        if not opts["csv"].exists():
            raise CommandError(f"No existe {opts['csv']}.")

        rows = [r for r in csv.DictReader(
            opts["csv"].open(encoding="utf-8-sig"), delimiter=";")
            if r["estado"] == "plantel" and r["cohorte"]]
        if not rows:
            raise CommandError("El CSV no trae filas de plantel con cohorte.")

        season = opts["season"]
        ladder = Bracket.ladder()
        report: dict[str, list] = defaultdict(list)

        # Everything is written unconditionally and rolled back when --commit is
        # absent. An earlier version guarded each write with `if commit:`, which
        # made the dry run take a different path than the real one: it never
        # created the new categories, so it could not report the TeamSeasons or
        # the players that depended on them. A simulation that under-reports is
        # worse than none, because the commit then does more than was approved.
        with transaction.atomic():
            categories = self._ensure_categories(club, rows, season, ladder, report)
            positions = self._ensure_positions(club, rows, report)
            self._reconcile_players(club, rows, categories, positions, opts, report)
            if not opts["commit"]:
                transaction.set_rollback(True)

        self._print(report, opts, len(rows))

    # ── categories ──────────────────────────────────────────────────────
    def _ensure_categories(self, club, rows, season, ladder, report):
        by_cohort: dict[int, Category] = {
            c.cohort_year: c for c in Category.objects.filter(
                club=club, cohort_year__isnull=False)
        }
        for cohort in sorted({int(r["cohorte"]) for r in rows}):
            if cohort in by_cohort:
                continue
            name = f"Serie {cohort}"
            existing = Category.objects.filter(club=club, name=name).first()
            if existing:
                # Same label, no cohort recorded — adopt it rather than
                # colliding on the (club, name) unique constraint.
                report["categoria_adoptada"].append(f"{name} (cohorte vacía → {cohort})")
                existing.cohort_year = cohort
                existing.save(update_fields=["cohort_year"])
                by_cohort[cohort] = existing
                continue
            report["categoria_creada"].append(name)
            by_cohort[cohort] = Category.objects.create(
                club=club, name=name, cohort_year=cohort)

        # A TeamSeason per cohort for the target season, with the bracket the
        # ladder gives — never `season - cohort`, which invents Sub 17/19/21.
        for cohort, category in by_cohort.items():
            if cohort not in {int(r["cohorte"]) for r in rows}:
                continue
            age = season - cohort
            youngest = min((b.age for b in ladder if b.age is not None), default=None)
            bracket = Bracket.for_age(age, ladder)
            # `Bracket.for_age` is a CEILING: it answers "what is the lowest
            # rung that would admit this age", so an 8-year-old comes back as
            # Sub 11. That is the right answer to its own question and the
            # wrong one here — the club's Series 2016/2017/2018 are three
            # distinct internal groups and the ANFP runs no competition for
            # them, so giving each a Sub 11 TeamSeason would assert three teams
            # in one bracket. See core/test_formativo_ladder.py.
            if youngest is not None and age < youngest:
                report["sin_teamseason"].append(
                    f"Serie {cohort} (bajo Sub {youngest}: sin competencia ANFP)")
                continue
            if bracket is None or bracket.is_senior:
                report["sin_teamseason"].append(f"Serie {cohort} (sobre-edad)")
                continue
            if category.team_seasons.filter(season=season).exists():
                continue
            report["temporada_creada"].append(f"Serie {cohort} {season} → {bracket.name}")
            category.team_seasons.create(season=season, bracket=bracket, derived=False)
        return by_cohort

    # ── positions ───────────────────────────────────────────────────────
    def _ensure_positions(self, club, rows, report):
        wanted = {norm(r["posicion"]) for r in rows if r["posicion"]}
        resolved: dict[str, Position] = {}
        for label in sorted(wanted):
            mapped = POSITION_MAP.get(label)
            if mapped is None:
                report["posicion_sin_mapa"].append(label)
                continue
            abbr, name, role = mapped
            pos = Position.objects.filter(club=club, abbreviation=abbr).first()
            if pos is None:
                report["posicion_creada"].append(f"{abbr} — {name}")
                pos = Position.objects.create(
                    club=club, abbreviation=abbr, name=name, role=role,
                    sort_order=Position.objects.filter(club=club).count())
            resolved[label] = pos
        return resolved

    # ── players ─────────────────────────────────────────────────────────
    def _reconcile_players(self, club, rows, categories, positions, opts, report):
        existing = list(Player.objects.filter(category__club=club)
                        .select_related("category"))
        by_dob: dict[date, list[Player]] = defaultdict(list)
        by_name: dict[str, Player] = {}
        for p in existing:
            if p.date_of_birth:
                by_dob[p.date_of_birth].append(p)
            by_name[norm(f"{p.first_name} {p.last_name} {p.second_last_name}")] = p
            by_name.setdefault(norm(f"{p.first_name} {p.last_name}"), p)

        for row in rows:
            full = norm(row["nombre"])
            cohort = int(row["cohorte"])
            dob = date.fromisoformat(row["fecha_nacimiento"]) \
                if row["fecha_nacimiento"] else None
            category = categories.get(cohort)
            position = positions.get(norm(row["posicion"])) if row["posicion"] else None

            match, how = self._find(full, dob, by_dob, by_name)
            if match is None:
                report["jugador_creado"].append(f"{row['nombre']} · Serie {cohort}")
                if category is not None:
                    first, last, second = split_name(full)
                    Player.objects.create(
                        category=category, first_name=first, last_name=last,
                        second_last_name=second, date_of_birth=dob,
                        position=position)
                continue

            self._update_match(match, row, full, dob, cohort, category, position,
                               how, opts, report)

    def _find(self, full, dob, by_dob, by_name):
        """Birth date first; token overlap only guards against a false merge."""
        if dob and by_dob.get(dob):
            tokens = set(full.split())
            candidates = [
                (len(tokens & set(norm(f"{p.first_name} {p.last_name} "
                                       f"{p.second_last_name}").split())), p)
                for p in by_dob[dob]
            ]
            candidates.sort(key=lambda t: -t[0])
            if candidates[0][0] >= 2:
                return candidates[0][1], "fecha"
            # Same date, no shared surname: two different people. Fall through
            # rather than merge them.
        return by_name.get(full), "nombre" if by_name.get(full) else ""

    def _update_match(self, player, row, full, dob, cohort, category, position,
                      how, opts, report):
        updates = []
        _, _, second = split_name(full)
        if second and not player.second_last_name:
            # The 215-player case: SLAB never had the maternal surname, so the
            # club's own label could not match exactly. Filling the real field
            # fixes every future import from these workbooks.
            player.second_last_name = second
            updates.append("apellido materno")
        if position and player.position_id is None:
            player.position = position
            updates.append("posición")
        if dob and player.date_of_birth != dob:
            if opts["overwrite_dob"]:
                player.date_of_birth = dob
                updates.append("fecha")
            else:
                report["fecha_en_conflicto"].append(
                    f"{row['nombre']}: base={player.date_of_birth} archivo={dob}")
        if category and player.category_id != category.id:
            if player.category.is_senior:
                report["senior_no_movido"].append(
                    f"{row['nombre']} sigue en {player.category.name}")
            elif opts["reassign"]:
                report["recategorizado"].append(
                    f"{row['nombre']}: {player.category.name} → Serie {cohort}")
                player.category = category
                updates.append("categoría")
            else:
                report["categoria_distinta"].append(
                    f"{row['nombre']}: base={player.category.name} archivo=Serie {cohort}")
        if updates:
            report["jugador_actualizado"].append(
                f"{row['nombre']} ({how}): {', '.join(updates)}")
            player.save()

    # ── report ──────────────────────────────────────────────────────────
    def _print(self, report, opts, total):
        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{modo} · {total} filas de plantel · temporada {opts['season']}\n"))
        orden = [
            ("categoria_creada", "Categorías creadas", self.style.SUCCESS),
            ("categoria_adoptada", "Categorías adoptadas (se les fijó cohorte)", self.style.SUCCESS),
            ("temporada_creada", "TeamSeason creadas", self.style.SUCCESS),
            ("sin_teamseason", "Sin TeamSeason (fuera de la escalera ANFP)", self.style.WARNING),
            ("posicion_creada", "Posiciones creadas", self.style.SUCCESS),
            ("posicion_sin_mapa", "Posiciones sin mapeo", self.style.ERROR),
            ("jugador_creado", "Jugadores creados", self.style.SUCCESS),
            ("jugador_actualizado", "Jugadores actualizados", self.style.SUCCESS),
            ("recategorizado", "Recategorizados", self.style.WARNING),
            ("categoria_distinta", "Categoría distinta (NO movidos; usar --reassign)", self.style.WARNING),
            ("senior_no_movido", "En categoría senior (nunca se mueven)", self.style.WARNING),
            ("fecha_en_conflicto", "Fecha en conflicto (NO tocada; usar --overwrite-dob)", self.style.ERROR),
        ]
        for key, title, style in orden:
            items = report.get(key) or []
            if not items:
                continue
            self.stdout.write(style(f"{title}: {len(items)}"))
            # Truncating the list hides the shape of the problem: 51 category
            # disagreements read as 51 individual judgement calls, when in fact
            # most are one legacy category that needs dissolving. Group first,
            # then show examples.
            if key in ("categoria_distinta", "recategorizado"):
                grupos = Counter(re.search(r"base=(.+?) archivo=(.+)$", i).groups()
                                 for i in items if re.search(r"base=(.+?) archivo=(.+)$", i))
                for (desde, hacia), n in sorted(grupos.items(), key=lambda kv: -kv[1]):
                    self.stdout.write(f"    {n:>3}× {desde} → {hacia}")
            else:
                for item in items[:12]:
                    self.stdout.write(f"    {item}")
                if len(items) > 12:
                    self.stdout.write(f"    … y {len(items) - 12} más")
            self.stdout.write("")
