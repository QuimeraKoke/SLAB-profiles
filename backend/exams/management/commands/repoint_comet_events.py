"""Re-file COMET matches under the team that actually played them.

Why this exists
---------------
`Event.category` for COMET matches used to be resolved by reading the "Sub NN"
token out of the competition name and matching it to the SLAB category with the
same digits. That is wrong by exactly one rung for this club's youth teams,
because the team NAMES are a frozen 2025 snapshot: the squad still called
`SUB-11` is the 2014 cohort, and in 2026 the 2014 cohort competes in **Sub 12**.

Measured on Universidad de Chile, 2026: of 215 synced youth matches, **zero**
were filed under the right team. Every played match sat one rung too low —
`SUB-12`'s calendar showed the matches `SUB-11`'s kids played (2014-born, 239
of 239 appearances in the Sub 12 competition).

This is a ONE-OFF repair of rows written before `CometCompetitionLink` stored
the bracket instead of the team. New syncs cannot reproduce the fault: the team
is now computed per season by `resolve_link_category` and never cached, so
correcting a `TeamSeason` re-points every match with no command at all. Keep
this around for the historical rows and for clubs migrating late.

What it does NOT touch
---------------------
* **Senior competitions.** Primera, Copa Chile and CONMEBOL carry no age token,
  so their bracket is the senior rung and they resolve through `is_senior` —
  which never had the off-by-one. The senior team is atemporal: it has no cohort
  and none of this arithmetic applies to it.
* **Competitions parked by a human** (`ignored=True`).
* **`Event.bracket`.** Already correct: it comes from the federation's own
  competition label, not from the team's name.

A human's `category_override` is not "untouched" so much as *obeyed*: resolution
returns it, so events move TO the pinned team rather than away from it.

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

Season is read per EVENT. The cohort→bracket mapping is season-specific, so a
2025 match and a 2026 match of the same team resolve through different indexes.

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
from exams.services.comet_sync import _season_index_cache, resolve_link_category


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

        index_for = _season_index_cache(club)
        links = {
            l.competition_id: l
            for l in CometCompetitionLink.objects.filter(
                integration=integ).select_related("bracket", "category_override")
        }

        events = Event.objects.filter(
            club=club, metadata__comet_match_id__isnull=False,
        ).select_related("category")
        if season:
            events = events.filter(starts_at__year=season)

        moves: dict[tuple, list] = defaultdict(list)
        stats = Counter()

        for ev in events:
            comp_id = (ev.metadata or {}).get("competition_id")
            link = links.get(int(comp_id)) if comp_id is not None else None

            if link is None:
                # No link row: nothing to resolve through. Report, never guess.
                stats["sin competencia"] += 1
                continue
            if link.ignored:
                stats["aparcada"] += 1
                continue

            year = ev.starts_at.year
            target = resolve_link_category(
                link, club, season=year, by_age=index_for(year),
            )
            label = link.competition_name or str(link.competition_id)

            if target is None:
                if ev.category_id is not None:
                    moves[(ev.category.name, "— (sin plantel)", label, year)].append(ev)
                    stats["huérfano"] += 1
                else:
                    stats["ya suelto"] += 1
                continue

            if ev.category_id == target.id:
                stats["ya correcto"] += 1
                continue

            src = ev.category.name if ev.category else "—"
            moves[(src, target.name, label, year)].append(ev)
            stats["re-apuntado"] += 1

        self._report(moves, stats, club)

        if commit and moves:
            self._apply(moves, club, index_for, links)

    # ------------------------------------------------------------------
    def _report(self, moves, stats, club):
        from core.models import Category

        senior = Category.objects.filter(club=club, is_senior=True).first()
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
    def _apply(self, moves, club, index_for, links):
        touched = 0
        with transaction.atomic():
            for _key, evs in moves.items():
                for ev in evs:
                    comp_id = (ev.metadata or {}).get("competition_id")
                    link = links.get(int(comp_id)) if comp_id is not None else None
                    if link is None:
                        continue
                    year = ev.starts_at.year
                    ev.category = resolve_link_category(
                        link, club, season=year, by_age=index_for(year),
                    )
                    ev.save(update_fields=["category", "updated_at"])
                    touched += 1

        self._say(self.style.SUCCESS(f"\nOK: {touched} eventos re-apuntados."))
