"""Backfill `Event.category` on migrated matches.

Phase 3 (legacy → events) created Event rows with `event_type='match'` but
left `category` null. The /partidos page filters by the navbar category,
so matches without a category never show up there. This command derives
the category for each migrated match by looking up the legacy
competicion → categoria chain, then matching the legacy categoria name to
the SLAB Category (case-insensitive).

Future re-runs of the migration should populate `category` directly in
phase 3 — see the parallel fix in `phases/phase3_events.py`.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from core.legacy_migration.connection import LegacyDB
from core.models import Category
from events.models import Event


class Command(BaseCommand):
    help = "Backfill Event.category on migrated matches via the legacy DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--club",
            default="Universidad de Chile",
            help="SLAB club name (default: Universidad de Chile)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without writing.",
        )

    def handle(self, *args, **options):
        club_name = options["club"]
        dry_run = options["dry_run"]

        # 1) Fetch the partido_id → legacy categoria name + genero from the
        #    legacy DB. genero is needed so the same name-resolution rules
        #    as phase 0 (PEM → "Primer Equipo", female suffix) can apply.
        sql = """
            SELECT p.id_partido,
                   cat.nombre AS cat_name,
                   cat.genero AS genero
              FROM partido p
              JOIN competicion_temporada ct
                ON ct.id_competicion_temporada = p.competicion_temporada_id
              JOIN competicion c
                ON c.id_competicion = ct.competicion_id
              JOIN categoria cat
                ON cat.id_categoria = c.categoria_id
        """
        with LegacyDB() as db:
            rows = db.fetch_all(sql)
        legacy_map: dict[int, tuple[str, str]] = {
            r["id_partido"]: (r["cat_name"] or "", (r["genero"] or "").lower())
            for r in rows
        }
        self.stdout.write(f"Legacy partidos with category: {len(legacy_map)}")

        # 2) Build a SLAB Category lookup by canonical SLAB name.
        from core.legacy_migration.mapping import CATEGORY_NAME_MAP
        slab_cats = {
            c.name: c
            for c in Category.objects.filter(club__name=club_name)
        }
        self.stdout.write(f"SLAB categories in club: {len(slab_cats)}")

        def resolve_slab_name(legacy_name: str, genero: str) -> str:
            """Mirror phase 0's name resolution so PEM → 'Primer Equipo' and
            female categorias get the ' - Femenino' suffix."""
            slab_name = CATEGORY_NAME_MAP.get(legacy_name, legacy_name)
            if genero == "femenino" and "femenino" not in slab_name.lower():
                slab_name = f"{slab_name} - Femenino"
            return slab_name

        # 3) Walk each migrated match Event, look up legacy categoria, resolve
        #    to SLAB Category, set event.category.
        events = Event.objects.filter(
            event_type="match",
            legacy_raw__contains={"_source_table": "partido"},
        )
        updated = no_legacy = no_slab = skipped = 0
        unmatched_names: dict[str, int] = {}

        for ev in events:
            pid = (ev.legacy_raw or {}).get("_source_pk")
            if pid is None:
                skipped += 1
                continue
            legacy = legacy_map.get(int(pid))
            if not legacy:
                no_legacy += 1
                continue
            legacy_name, genero = legacy
            slab_name = resolve_slab_name(legacy_name, genero)
            slab_cat = slab_cats.get(slab_name)
            if slab_cat is None:
                no_slab += 1
                unmatched_names[f"{legacy_name} ({genero})"] = (
                    unmatched_names.get(f"{legacy_name} ({genero})", 0) + 1
                )
                continue
            if ev.category_id == slab_cat.id:
                skipped += 1
                continue
            if not dry_run:
                ev.category = slab_cat
                ev.save(update_fields=["category"])
            updated += 1

        mode = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            f"{mode}updated: {updated}, no legacy row: {no_legacy}, "
            f"no SLAB match: {no_slab}, unchanged: {skipped}"
        )
        if unmatched_names:
            self.stdout.write("Unmatched legacy category names (would be skipped):")
            for name, n in sorted(unmatched_names.items(), key=lambda x: -x[1]):
                self.stdout.write(f"  '{name}' — {n} matches")
