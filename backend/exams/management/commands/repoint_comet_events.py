"""Re-file COMET matches under the team that actually played them.

Why this exists
---------------
`Event.category` for COMET matches was resolved by reading the "Sub NN" token
out of the competition name and matching it to the SLAB category with the same
digits. That is wrong by exactly one rung for this club's youth teams, because
the team NAMES are a frozen 2025 snapshot: the squad still called `SUB-11` is
the 2014 cohort, and in 2026 the 2014 cohort competes in **Sub 12**.

Measured on Universidad de Chile, 2026: of 215 synced youth matches, **zero**
were filed under the right team. Every played match sat one rung too low —
`SUB-12`'s calendar showed the matches `SUB-11`'s kids played (2014-born, 239
of 239 appearances in the Sub 12 competition).

The sync itself was fixed when `_category_index` learned to read `TeamSeason`
first. This command exists because that fix cannot heal the existing rows:
`_competition_link` only re-resolves a link whose category is still NULL, so a
`CometCompetitionLink` filed by the old name-matching path keeps its wrong
category forever and every match inherits it.

What it does NOT touch
---------------------
* **Senior competitions.** Primera, Copa Chile and CONMEBOL carry no age token
  and resolve through the `is_senior` flag, which was always right. The senior
  team is atemporal — it has no cohort and none of this arithmetic applies.
* **Links a human resolved** (`auto_resolved=False`) or parked
  (`ignored=True`). A person's decision outranks this command.
* **`Event.bracket`.** Already correct: it comes from the federation's own
  competition label, not from the team's name.

Orphans
-------
A competition can resolve to no team at all: the club has no squad declared in
that bracket for that season. Universidad de Chile's "Sub 11" 2026 is the case
— 17 played matches, not one lineup, because that competition belongs to the
2015 cohort, which SLAB does not roster. Those events are DETACHED
(`category=None`) rather than deleted: they are real ANFP matches, and if the
club loads the 2015 squad later they attach by re-running this. Detaching is
what stops them from padding `SUB-11`'s calendar with matches its kids never
played.

Season is read per EVENT, not per link. The cohort→bracket mapping is
season-specific, so a 2025 match and a 2026 match of the same team resolve
through different indexes.

    python manage.py repoint_comet_events                    # dry run
    python manage.py repoint_comet_events --commit
    python manage.py repoint_comet_events --club "Universidad de Chile" --season 2026
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Club
from events.models import Event, EventParticipant
from exams.models import CometCompetitionLink, CometIntegration
from exams.services.comet_sync import _category_from_names, _category_index


def _senior_default(club):
    """The team senior competitions belong to, via the flag — never the name."""
    from core.models import Category

    return Category.objects.filter(club=club, is_senior=True).first()


class Command(BaseCommand):
    help = "Re-file COMET matches under the team whose TeamSeason matches the competition."

    def add_arguments(self, parser):
        parser.add_argument("--club", help="Club name. Omit → every club with a COMET integration.")
        parser.add_argument(
            "--season", type=int,
            help="Limit to matches of this season. Omit → every synced season.",
        )
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        commit = opts["commit"]
        self.quiet = not opts.get("verbosity", 1)
        integrations = CometIntegration.objects.select_related("club")
        if opts.get("club"):
            integrations = integrations.filter(club=Club.objects.get(name=opts["club"]))

        for integ in integrations:
            self._club(integ, season=opts.get("season"), commit=commit)

        if not commit:
            self._say(self.style.WARNING(
                "\nDRY RUN — nada se guardó. Repetí con --commit."
            ))

    def _say(self, text):
        if not getattr(self, "quiet", False):
            self.stdout.write(text)

    # ------------------------------------------------------------------
    def _club(self, integ, *, season: int | None, commit: bool):
        club = integ.club
        self._say(self.style.MIGRATE_HEADING(f"\n=== {club.name} ==="))

        senior = _senior_default(club)
        indexes: dict[int, dict] = {}

        def index_for(year: int) -> dict:
            if year not in indexes:
                indexes[year] = _category_index(club, season=year)
            return indexes[year]

        # Competition id → link, for joining events by metadata.
        links = {
            l.competition_id: l
            for l in CometCompetitionLink.objects.filter(
                integration=integ).select_related("category")
        }

        events = Event.objects.filter(
            club=club, metadata__comet_match_id__isnull=False,
        ).select_related("category")
        if season:
            events = events.filter(starts_at__year=season)

        moves: dict[tuple, list] = defaultdict(list)
        stats = Counter()

        for ev in events:
            meta = ev.metadata or {}
            comp_id = meta.get("competition_id")
            link = links.get(int(comp_id)) if comp_id is not None else None

            # A human's call, or a parked competition: hands off.
            if link is not None and (link.ignored or not link.auto_resolved):
                stats["respetado"] += 1
                continue

            name = meta.get("competition") or (link.competition_name if link else "") or ""
            parent = meta.get("competition_phase") or (link.parent_name if link else "") or ""
            age = _category_from_names(name, parent)

            if age is None:
                # Senior: no age token. Always was right, leave it.
                stats["senior"] += 1
                continue

            year = ev.starts_at.year
            target = index_for(year).get(age)

            if target is None:
                # No squad declared in that bracket that season.
                if ev.category_id is not None:
                    moves[(ev.category.name, "— (sin plantel)", name, year)].append(ev)
                    stats["huérfano"] += 1
                else:
                    stats["ya suelto"] += 1
                continue

            if ev.category_id == target.id:
                stats["ya correcto"] += 1
                continue

            moves[(ev.category.name if ev.category else "—", target.name, name, year)].append(ev)
            stats["re-apuntado"] += 1

        self._report(moves, stats, senior)

        if commit and moves:
            self._apply(moves, integ, club, index_for)

    # ------------------------------------------------------------------
    def _report(self, moves, stats, senior):
        if senior:
            self._say(f"equipo senior (atemporal, intacto): {senior.name}")

        if moves:
            self._say("\ncambios:")
            for (src, dst, comp, year), evs in sorted(moves.items()):
                played = sum(
                    1 for e in evs if EventParticipant.objects.filter(event=e).exists()
                )
                detail = f"{len(evs)} partidos"
                if played:
                    detail += f" ({played} con nómina)"
                self._say(
                    f"  {year}  {comp[:34]:<35} {src:<9} → {dst:<18} {detail}"
                )
        else:
            self._say("\nsin cambios: todo ya está archivado donde corresponde.")

        self._say("\nresumen: " + ", ".join(
            f"{k}={v}" for k, v in sorted(stats.items())
        ))

    # ------------------------------------------------------------------
    def _apply(self, moves, integ, club, index_for):
        with transaction.atomic():
            touched = 0
            for (_src, _dst, _comp, _year), evs in moves.items():
                for ev in evs:
                    meta = ev.metadata or {}
                    age = _category_from_names(
                        meta.get("competition") or "", meta.get("competition_phase") or "",
                    )
                    target = index_for(ev.starts_at.year).get(age) if age is not None else None
                    ev.category = target
                    ev.save(update_fields=["category", "updated_at"])
                    touched += 1

            # Refresh the cached links too, or the next sync re-files new matches
            # under the old category. Season comes from the competition's own
            # label when it carries one — that is what makes a 2025 link resolve
            # through the 2025 index.
            relinked = 0
            for link in CometCompetitionLink.objects.filter(
                integration=integ, ignored=False, auto_resolved=True,
            ):
                age = _category_from_names(link.competition_name or "", link.parent_name or "")
                if age is None:
                    continue
                year = _season_from_label(link.competition_name, link.parent_name)
                if year is None:
                    year = _dominant_season(link, club)
                if year is None:
                    continue
                target = index_for(year).get(age)
                if link.category_id != (target.id if target else None):
                    link.category = target
                    link.save(update_fields=["category"])
                    relinked += 1

        self._say(self.style.SUCCESS(
            f"\nOK: {touched} eventos re-apuntados, {relinked} competencias re-vinculadas."
        ))


def _season_from_label(*labels) -> int | None:
    """`Sub 15 Nacional Apertura 2026` → 2026. None when the label carries none."""
    import re

    for text in labels:
        m = re.search(r"\b(20\d{2})\b", text or "")
        if m:
            return int(m.group(1))
    return None


def _dominant_season(link, club) -> int | None:
    """Fallback: the season most of this competition's matches were played in."""
    years = Counter(
        e.starts_at.year
        for e in Event.objects.filter(
            club=club, metadata__competition_id=link.competition_id,
        ).only("starts_at")
    )
    return years.most_common(1)[0][0] if years else None
