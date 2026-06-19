"""Sync match fixtures + results from API-Football into Events.

Requires API_FOOTBALL_KEY and a category bound via `external_config`
({"provider":"api_football","team_id":N,"season":YYYY}).

    # all bound categories:
    python manage.py sync_fixtures
    # one category (free tier → use a season the plan exposes, e.g. 2023):
    python manage.py sync_fixtures --club "Universidad de Chile" --category "Primer Equipo"
    # calendar only, skip tactical stats (saves requests on the free tier):
    python manage.py sync_fixtures --no-stats
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync API-Football fixtures + results into match Events."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None)
        parser.add_argument("--category", default=None, help="Category name.")
        parser.add_argument("--no-stats", action="store_true",
                            help="Skip lineups/events/stats (calendar only).")
        parser.add_argument("--stats-limit", type=int, default=None,
                            help="Cap matches whose tactical data is fetched this "
                                 "run (quota-aware; targets matches missing it).")

    def handle(self, *args, **opts):
        from core.models import Category
        from events.services.fixtures_sync import (
            sync_all_bound_categories, sync_category_fixtures,
        )

        with_stats = not opts["no_stats"]
        stats_limit = opts["stats_limit"]

        if opts["category"]:
            qs = Category.objects.filter(name=opts["category"])
            if opts["club"]:
                qs = qs.filter(club__name=opts["club"])
            cat = qs.first()
            if cat is None:
                self.stderr.write("Category not found.")
                return
            results = [sync_category_fixtures(
                cat, with_stats=with_stats, stats_limit=stats_limit,
            )]
        else:
            results = sync_all_bound_categories(
                with_stats=with_stats, stats_limit=stats_limit,
            )

        if not results:
            self.stdout.write("No categories bound to API-Football.")
            return
        for r in results:
            self.stdout.write(self.style.SUCCESS(str(r)))
