"""Import opponent scouting data (recent form + last lineup) for a
category's rivals from API-Football, into the hidden OpponentScouting store.

    # upcoming opponents of Primer Equipo (quota-aware):
    python manage.py scout_opponents --club "Universidad de Chile" --category "Primer Equipo" --limit 3
    # all opponents (past + future) of the season:
    python manage.py scout_opponents --category "Primer Equipo" --all
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scout a category's opponents (recent form + last lineup) into OpponentScouting."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None)
        parser.add_argument("--category", required=True, help="Category name.")
        parser.add_argument("--all", action="store_true",
                            help="Include past matches (default: upcoming only).")
        parser.add_argument("--limit", type=int, default=None,
                            help="Cap opponents fetched this run (quota-aware).")

    def handle(self, *args, **opts):
        from core.models import Category
        from events.services.opponent_scouting import scout_category_opponents

        qs = Category.objects.filter(name=opts["category"])
        if opts["club"]:
            qs = qs.filter(club__name=opts["club"])
        cat = qs.first()
        if cat is None:
            self.stderr.write("Category not found.")
            return

        result = scout_category_opponents(
            cat, upcoming_only=not opts["all"], limit=opts["limit"],
        )
        self.stdout.write(self.style.SUCCESS(str(result)))
