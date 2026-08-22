"""Seed the competition brackets and backfill cohorts / team-seasons.

Phase 1 of PRD_EQUIPO_TEMPORADA.md. Writes only new rows — it never touches
`Player.category`, so nothing changes behaviour. Dry-run by default.

    python manage.py backfill_cohorts
    python manage.py backfill_cohorts --commit

Five steps:

1. **Brackets.** The ANFP ladder, whose defining feature is its GAPS: there is
   no Sub 17 and no Sub 19, so `order` is what makes progression arithmetic
   correct. Sub 16 → Sub 18 is ONE rung.
2. **`cohort_year`** per age-group team, taken from the dominant birth year of
   its active players.
3. **`TeamSeason`** per (team, season), taken from where the team's players
   ACTUALLY played that season, not from the team's label. The labels are a
   frozen 2025 snapshot, which is the whole reason this model exists.
4. **`PlayerTeamMembership`** — one open spell per active player.
5. **`Event.bracket`** for matches, from the federation's competition name when
   COMET filled it, else from the event's own label.

A team's players also turn out above their bracket (26% of youth appearances in
2026), so the season's bracket is the DOMINANT one, never merely a present one.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Bracket, Category, Player, PlayerTeamMembership, TeamSeason
from events.models import EventParticipant

# The real ANFP ladder. `order` is consecutive even where `age` skips.
BRACKETS: list[tuple[str, str, int | None]] = [
    ("sub_11", "Sub 11", 11),
    ("sub_12", "Sub 12", 12),
    ("sub_13", "Sub 13", 13),
    ("sub_14", "Sub 14", 14),
    ("sub_15", "Sub 15", 15),
    ("sub_16", "Sub 16", 16),
    ("sub_18", "Sub 18", 18),          # no Sub 17 — the gap is the point
    ("sub_20", "Sub 20", 20),          # no Sub 19
    ("primera", "Primera", None),
]

# Minimum appearances before a season's bracket is trusted. Without it, a single
# guest appearance can outvote a real season.
MIN_APPEARANCES = 3

# How dominant the winning value must be before it's believed. Both thresholds
# exist because the cohort model FITS THE YOUNG TEAMS AND DEGRADES UPWARD: on
# this club's data SUB-11..SUB-14 are 100% one birth year, while SUB-20 is 33%
# (43 players spanning 2004–2008) and SUB-17 is 50%. Sub 20 isn't a cohort at
# all — it's a bracket-shaped squad — so guessing a `cohort_year` for it would
# assert something false. Below the threshold we leave it NULL, which the model
# already means as "not an age group".
MIN_COHORT_SHARE = 0.70
MIN_SEASON_SHARE = 0.60


def bracket_for_age(age: int, brackets: list[Bracket]) -> Bracket:
    """First rung that still admits a player of `age` — brackets are a ceiling."""
    for b in brackets:
        if b.age is not None and b.age >= age:
            return b
    return brackets[-1]                # senior


def parse_age(category_name: str) -> int | None:
    """`SUB-15` → 15, `Primer Equipo` → None. Women's squads return None."""
    name = (category_name or "").upper()
    if "F -" in name or "FEMENINO" in name:
        return None
    if not name.startswith("SUB-"):
        return None
    try:
        return int(name.split("-", 1)[1].strip())
    except (IndexError, ValueError):
        return None

def parse_age_token(text: str) -> int | None:
    """`Sub 15 Nacional Clausura 2026` → 15. Ignores the year.

    Looser than `parse_age`: it reads a competition name as the federation
    writes it, anywhere in the string. `\\b` around the digits keeps the season
    out — "Clausura 2026" must not parse as Sub 20.
    """
    m = re.search(r"\bsub\s*(\d{1,2})\b", (text or ""), re.IGNORECASE)
    return int(m.group(1)) if m else None


def is_age_group(category_name: str) -> bool:
    return parse_age(category_name) is not None


class Command(BaseCommand):
    help = "Seed brackets and backfill cohort_year / TeamSeason / memberships."

    def add_arguments(self, parser):
        parser.add_argument("--club", help="Club name. Omit → every club.")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        commit = opts["commit"]
        self.stdout.write(self.style.WARNING(
            "COMMIT" if commit else "DRY-RUN — nada escrito."
        ))

        brackets = self._seed_brackets(commit)
        by_code = {b.code: b for b in brackets}
        ladder = sorted(brackets, key=lambda b: b.order)

        cats = Category.objects.select_related("club")
        if opts["club"]:
            cats = cats.filter(club__name=opts["club"])
        cats = list(cats)

        self._backfill_cohorts(cats, commit)
        self._backfill_team_seasons(cats, ladder, by_code, commit)
        self._backfill_memberships(cats, commit)
        self._backfill_event_brackets(cats, ladder, by_code, commit)

        if not commit:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — volvé a correr con --commit para escribir."
            ))

    # ---------- 1. brackets ----------

    def _seed_brackets(self, commit: bool) -> list[Bracket]:
        self.stdout.write("\n1. Categorías de competencia")
        out, created = [], 0
        for order, (code, name, age) in enumerate(BRACKETS):
            b = Bracket.objects.filter(code=code).first()
            if b is None:
                b = Bracket(code=code, name=name, age=age, order=order)
                created += 1
                if commit:
                    b.save()
            else:
                # Keep order/age authoritative here — the ladder is not editable
                # data, it's the federation's.
                if (b.order, b.age, b.name) != (order, age, name):
                    b.order, b.age, b.name = order, age, name
                    if commit:
                        b.save(update_fields=["order", "age", "name"])
            out.append(b)
        self.stdout.write(f"   {len(BRACKETS)} brackets · {created} nuevos")
        self.stdout.write(
            "   escalera: " + " → ".join(b.name for b in out)
        )
        return out

    # ---------- 2. cohort_year ----------

    def _backfill_cohorts(self, cats: list[Category], commit: bool):
        self.stdout.write("\n2. Cohorte por equipo (año de nacimiento dominante)")
        for cat in sorted(cats, key=lambda c: c.name):
            if not is_age_group(cat.name):
                continue
            years = Counter(
                p.date_of_birth.year
                for p in Player.objects.filter(category=cat, is_active=True)
                if p.date_of_birth
            )
            if not years:
                self.stdout.write(self.style.WARNING(
                    f"   · {cat.name}: sin jugadores con fecha — omitido"
                ))
                continue
            year, n = years.most_common(1)[0]
            total = sum(years.values())
            share = n / total
            if share < MIN_COHORT_SHARE:
                self.stdout.write(self.style.WARNING(
                    f"   · {cat.name:<10} → sin cohorte: el año dominante es "
                    f"{year} con sólo {n}/{total} ({share:.0%}). "
                    "Es un plantel multi-cohorte, no un grupo de edad."
                ))
                continue
            if cat.cohort_year != year:
                cat.cohort_year = year
                if commit:
                    cat.save(update_fields=["cohort_year"])
            self.stdout.write(
                f"   · {cat.name:<10} → {year}  ({n}/{total}, {share:.0%})"
            )

    # ---------- 3. TeamSeason ----------

    def _backfill_team_seasons(self, cats, ladder, by_code, commit: bool):
        self.stdout.write("\n3. Temporadas de equipo (desde dónde jugaron de verdad)")
        age_to_bracket = {b.age: b for b in ladder if b.age is not None}

        # One pass over participations: (team, season) → Counter[bracket_code]
        seen: dict[tuple, Counter] = defaultdict(Counter)
        cat_ids = {c.id for c in cats}
        qs = (
            EventParticipant.objects
            .filter(event__event_type="match")
            .select_related("event", "event__category", "player")
        )
        for ep in qs.iterator(chunk_size=2000):
            ev, pl = ep.event, ep.player
            if ev.category_id is None or pl.category_id not in cat_ids:
                continue
            ev_name = ev.category.name if ev.category else ""
            age = parse_age(ev_name)
            code = "primera" if ev_name == "Primer Equipo" else None
            if age is not None:
                b = age_to_bracket.get(age)
                code = b.code if b else None
            if code is None:
                continue
            seen[(pl.category_id, ev.starts_at.year)][code] += 1

        by_id = {c.id: c for c in cats}
        written = skipped = 0
        for (team_id, season), counts in sorted(
            seen.items(), key=lambda kv: (by_id[kv[0][0]].name, kv[0][1])
        ):
            team = by_id[team_id]
            code, n = counts.most_common(1)[0]
            total = sum(counts.values())
            if n < MIN_APPEARANCES or n / total < MIN_SEASON_SHARE:
                self.stdout.write(self.style.WARNING(
                    f"   · {team.name:<14} {season}  →  sin decidir "
                    f"({by_code[code].name} sólo {n}/{total}) — dejar al club"
                ))
                skipped += 1
                continue
            bracket = by_code[code]
            existing = TeamSeason.objects.filter(team=team, season=season).first()
            if existing is not None:
                # Never overwrite a human's correction.
                if not existing.derived:
                    continue
                if existing.bracket_id != bracket.id:
                    existing.bracket = bracket
                    if commit:
                        existing.save(update_fields=["bracket"])
                        written += 1
                continue
            ts = TeamSeason(
                team=team, season=season, bracket=bracket, derived=True,
                external_config=team.external_config or {},
            )
            if commit:
                ts.save()
            written += 1
            share = 100.0 * n / total
            self.stdout.write(
                f"   · {team.name:<14} {season}  →  {bracket.name:<8} "
                f"({n}/{total}, {share:.0f}%)"
            )

        # Teams with a cohort but no match data still get a derived row.
        for team in cats:
            if team.cohort_year is None:
                continue
            for season in (2025, 2026):
                if TeamSeason.objects.filter(team=team, season=season).exists():
                    continue
                if (team.id, season) in seen:
                    continue
                bracket = bracket_for_age(season - team.cohort_year, ladder)
                ts = TeamSeason(
                    team=team, season=season, bracket=bracket, derived=True,
                    external_config=team.external_config or {},
                )
                if commit:
                    ts.save()
                written += 1
                self.stdout.write(
                    f"   · {team.name:<14} {season}  →  {bracket.name:<8} "
                    "(sin partidos, derivado de la edad)"
                )
        self.stdout.write(
            f"   {written} filas · {skipped} descartadas por <{MIN_APPEARANCES} partidos"
        )

    # ---------- 4. memberships ----------

    def _backfill_memberships(self, cats, commit: bool):
        """One open spell per active player, into the team he's in today.

        A player's team IS his cohort, so turning out for an older bracket is an
        APPEARANCE, not a change of team — that's what keeps this table small and
        meaningful. `since` is inferred from his first known match, and the reason
        says so, because the real joining date isn't in the system.
        """
        self.stdout.write("\n4. Pertenencias iniciales")
        cat_ids = {c.id for c in cats}
        players = list(
            Player.objects.filter(category_id__in=cat_ids, is_active=True)
        )
        first_seen: dict = {}
        for ep in (
            EventParticipant.objects
            .filter(player__in=players)
            .select_related("event")
            .only("player_id", "event__starts_at")
        ):
            d = ep.event.starts_at.date()
            cur = first_seen.get(ep.player_id)
            if cur is None or d < cur:
                first_seen[ep.player_id] = d

        created = 0
        for p in players:
            if PlayerTeamMembership.objects.filter(
                player=p, until__isnull=True,
            ).exists():
                continue
            since = first_seen.get(p.id)
            reason = (
                "carga inicial (fecha del primer partido)" if since
                else "carga inicial (sin partidos, fecha estimada)"
            )
            if since is None:
                since = p.created_at.date()
            m = PlayerTeamMembership(
                player=p, team=p.category, since=since, reason=reason,
            )
            if commit:
                m.save()
            created += 1
        with_date = sum(1 for p in players if p.id in first_seen)
        self.stdout.write(
            f"   {created} pertenencias · {with_date} con fecha de partido real"
        )

    # ---------- 5. Event.bracket ----------

    def _backfill_event_brackets(self, cats, ladder, by_code, commit: bool):
        """Which competition each match belongs to.

        Two sources, in order of authority:

        1. `metadata.competition` — the federation's own competition name, which
           COMET fills. "Sub 15 Nacional Clausura 2026" is unambiguous.
        2. The event's category label. Safe for both seasons despite the label
           drift, because match events have always been filed under the bracket
           they were played in: a 2025 fixture under `SUB-11` really was Sub 11,
           and a 2026 one under `SUB-12` really is Sub 12. The drift is between
           the PLAYER's label and the season, not the event's.

        Only match events get a bracket; training and test events have none.
        """
        from events.models import Event

        self.stdout.write("\n5. Categoría de competencia por partido")
        min_ladder_age = min(b.age for b in ladder if b.age is not None)
        club_ids = {c.club_id for c in cats}

        qs = (
            Event.objects
            .filter(event_type="match", club_id__in=club_ids, bracket__isnull=True)
            .select_related("category")
        )
        from_meta = from_label = unresolved = 0
        by_bracket: Counter = Counter()
        for ev in qs.iterator(chunk_size=1000):
            comp = (ev.metadata or {}).get("competition") or ""
            age = parse_age_token(comp)
            src = "meta"
            if age is None:
                name = ev.category.name if ev.category else ""
                if name == "Primer Equipo":
                    bracket = by_code["primera"]
                    if commit:
                        ev.bracket = bracket
                        ev.save(update_fields=["bracket"])
                    from_label += 1
                    by_bracket[bracket.name] += 1
                    continue
                age = parse_age(name)
                src = "label"
            if age is None:
                # A senior competition names no age: Primera, Copa Chile,
                # CONMEBOL. Fall back to the club's senior bracket only when the
                # event is actually a senior team's.
                if comp and ev.category and ev.category.name == "Primer Equipo":
                    bracket = by_code["primera"]
                else:
                    unresolved += 1
                    continue
            else:
                # `bracket_for_age`, not an exact-age lookup: a label can name an
                # age the federation doesn't run. `SUB-17` is real in this club
                # (6 fixtures) and there IS no Sub 17 competition, so it belongs
                # to Sub 18 — the same rule the rest of the system applies.
                # Below the ladder is different: a Sub 9 fixture is a local
                # tournament, and promoting it to Sub 11 would invent a
                # competition, so it stays unresolved.
                if age < min_ladder_age:
                    unresolved += 1
                    continue
                bracket = bracket_for_age(age, ladder)
            if commit:
                ev.bracket = bracket
                ev.save(update_fields=["bracket"])
            if src == "meta":
                from_meta += 1
            else:
                from_label += 1
            by_bracket[bracket.name] += 1

        total = from_meta + from_label
        self.stdout.write(
            f"   {total} partidos · {from_meta} por competencia oficial · "
            f"{from_label} por etiqueta · {unresolved} sin resolver"
        )
        for name, n in sorted(by_bracket.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"     · {name:<10} {n}")
