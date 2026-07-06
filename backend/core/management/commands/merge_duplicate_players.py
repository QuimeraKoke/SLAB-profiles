"""Merge duplicate Player records — one human, one profile.

Duplicates happen when the legacy roster (UPPERCASE, no accents) and a later
seed (mixed case, accents) created the same human twice, possibly in
different categories. This command scans a club for players whose normalized
name collides, repoints every relation (results, aliases, episodes, events,
goals, alerts, notes, snapshots) onto the data-richest record, fills its
empty identity fields from the duplicate, and deletes the duplicate.

Guards: two records whose `national_id` or `date_of_birth` BOTH exist and
disagree are reported as distinct humans and skipped.

    docker compose exec backend python manage.py merge_duplicate_players --dry-run
    docker compose exec backend python manage.py merge_duplicate_players
"""
from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from core.models import Player

# Scalar identity fields copied dup → target when the target's is empty.
_FILLABLE_FIELDS = (
    "middle_name", "second_last_name", "date_of_birth", "sex", "national_id",
    "nationality", "preferred_foot", "secondary_position", "photo_url",
)


def normalize_name(*parts: str) -> str:
    joined = " ".join(p for p in parts if p).strip().casefold()
    return "".join(
        c for c in unicodedata.normalize("NFKD", joined)
        if not unicodedata.combining(c)
    )


class Command(BaseCommand):
    help = "Merge duplicate Player records (same club, same normalized name) into one profile."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-log", action="store_true")

    def handle(self, *args, **opts):
        players = list(
            Player.objects.filter(category__club__name=opts["club"])
            .select_related("category")
        )
        if not players:
            raise CommandError(f"No players found for club '{opts['club']}'.")

        groups: dict[str, list[Player]] = defaultdict(list)
        for p in players:
            groups[normalize_name(p.first_name, p.last_name)].append(p)

        report: dict = {"club": opts["club"], "dry_run": opts["dry_run"],
                        "merged": [], "skipped": []}
        with transaction.atomic():
            for key, dupes in sorted(groups.items()):
                if len(dupes) < 2:
                    continue
                self._merge_group(dupes, report)
            if opts["dry_run"]:
                transaction.set_rollback(True)

        self._print(report)
        if not opts["no_log"] and not opts["dry_run"] and report["merged"]:
            self._write_log(report)

    # ------------------------------------------------------------------

    def _merge_group(self, dupes: list[Player], report: dict) -> None:
        from exams.models import ExamResult

        def label(p):
            return f"{p.first_name} {p.last_name} [{p.category}] ({p.id})"

        # Distinct-human guards: both sides carrying a conflicting identity
        # value means these are two real people who share a name.
        for field in ("national_id", "date_of_birth"):
            vals = {getattr(p, field) for p in dupes if getattr(p, field)}
            if len(vals) > 1:
                report["skipped"].append({
                    "players": [label(p) for p in dupes],
                    "reason": f"conflicting {field} — treated as distinct humans",
                })
                return

        richness = {p.id: ExamResult.objects.filter(player=p).count() for p in dupes}
        # Aliases outrank raw result count: the aliased record is the one the
        # ingest pipelines (GPS uploads, wellness sync) resolve against, so it
        # must stay the live profile. Then data volume, then age.
        dupes.sort(key=lambda p: (
            -p.aliases.count(),
            -richness[p.id],
            p.created_at,
        ))
        target, rest = dupes[0], dupes[1:]

        entry = {"kept": label(target), "kept_results": richness[target.id],
                 "absorbed": [], "moved": {}}
        for dup in rest:
            moved = self._repoint_relations(dup, target)
            self._fill_identity_fields(dup, target)
            entry["absorbed"].append({"player": label(dup), "results": richness[dup.id]})
            for k, v in moved.items():
                entry["moved"][k] = entry["moved"].get(k, 0) + v
            dup.delete()
        report["merged"].append(entry)

    def _repoint_relations(self, dup: Player, target: Player) -> dict:
        """Point every relation from `dup` to `target`. Unique collisions
        (same event participation, one-to-one state rows, duplicate aliases)
        resolve in the target's favor — the dup's colliding row is dropped;
        materialized state is rebuildable anyway."""
        moved: dict = {}
        for rel in Player._meta.related_objects:
            model = rel.related_model
            if rel.many_to_many:
                through = getattr(rel, "through", None)
                if through is None or not through._meta.auto_created:
                    continue  # explicit through table is covered by its own FK
                fk = next(f.name for f in through._meta.fields
                          if getattr(f, "related_model", None) is Player)
                qs, field = through.objects.filter(**{fk: dup}), fk
            else:
                qs, field = model.objects.filter(**{rel.field.name: dup}), rel.field.name

            n = 0
            for row in qs:
                try:
                    with transaction.atomic():
                        setattr(row, field, target)
                        row.save(update_fields=[field])
                    n += 1
                except IntegrityError:
                    row.delete()  # target already has the equivalent row
            if n:
                moved[model._meta.label] = n
        return moved

    def _fill_identity_fields(self, dup: Player, target: Player) -> None:
        changed = []
        for field in _FILLABLE_FIELDS:
            if not getattr(target, field) and getattr(dup, field):
                setattr(target, field, getattr(dup, field))
                changed.append(field)
        if changed:
            target.save(update_fields=changed)

    # ------------------------------------------------------------------

    def _print(self, r):
        tag = "DRY-RUN — " if r["dry_run"] else ""
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{tag}merge_duplicate_players [{r['club']}]"))
        if not r["merged"] and not r["skipped"]:
            self.stdout.write("  no duplicates found.")
        for m in r["merged"]:
            self.stdout.write(f"  KEPT {m['kept']} ({m['kept_results']} results)")
            for a in m["absorbed"]:
                self.stdout.write(f"    absorbed {a['player']} ({a['results']} results)")
            if m["moved"]:
                self.stdout.write(f"    moved: {m['moved']}")
        for s in r["skipped"]:
            self.stdout.write(self.style.WARNING(
                f"  SKIPPED {s['players']} — {s['reason']}"))
        self.stdout.write(self.style.SUCCESS(
            "  (nothing written)" if r["dry_run"] else "  done."))

    def _write_log(self, report):
        import os
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        out_dir = os.path.join(settings.BASE_DIR, "migration_runs")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"merge-players-{ts}.json")
        with open(out, "w") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
        self.stdout.write(f"  run log: {out}")
