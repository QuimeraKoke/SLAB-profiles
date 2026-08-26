"""`core.rosters` — the one place that answers "who is in this team".

SLAB has two answers and mixing them up is the recurring damage in this
codebase: the WORKING GROUP (home ∪ active call-ups) for anything you *do* with
a squad, the HOME ROSTER (plain `category=`) for anything you *count*. On
Universidad de Chile 2026, 26% of youth appearances are loans, so the two sets
are far apart.

These tests pin the ingest-facing behaviour, which had no coverage while three
importers quietly matched the home roster only.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase

from core.models import Category, Club, Player, PlayerCallUp
from core.rosters import player_ids_in_category, players_in_category


class PlayersInCategoryTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.home = Category.objects.create(club=self.club, name="SUB-18")
        self.other = Category.objects.create(club=self.club, name="SUB-16")

        self.local = Player.objects.create(
            category=self.home, first_name="Local", last_name="Uno")
        self.lent = Player.objects.create(
            category=self.other, first_name="Prestado", last_name="Dos")
        self.stranger = Player.objects.create(
            category=self.other, first_name="Ajeno", last_name="Tres")
        PlayerCallUp.objects.create(
            player=self.lent, category=self.home, active=True,
            since=date(2026, 3, 1),
        )

    # ------------------------------------------------------------------
    def test_the_working_group_includes_active_call_ups(self):
        got = set(players_in_category(self.home))
        self.assertEqual(got, {self.local, self.lent})

    def test_counting_excludes_call_ups_so_nobody_inflates_two_teams(self):
        got = set(players_in_category(self.home, include_call_ups=False))
        self.assertEqual(got, {self.local})

    def test_an_inactive_call_up_does_not_count_as_present(self):
        PlayerCallUp.objects.filter(player=self.lent).update(active=False)
        self.assertEqual(set(players_in_category(self.home)), {self.local})

    def test_a_call_up_keeps_its_home_category(self):
        # How a caller tells them apart, and why counts must use the home roster:
        # the lent player still belongs to SUB-16 for every other purpose.
        squad = {p.id: p for p in players_in_category(self.home)}
        self.assertNotEqual(squad[self.lent.id].category_id, self.home.id)

    def test_active_only_is_the_default_but_imports_can_widen_it(self):
        # A historical file may name someone who has since left. Dropping those
        # rows loses real data, so the importers pass active_only=False.
        self.local.is_active = False
        self.local.save(update_fields=["is_active"])

        self.assertNotIn(self.local, players_in_category(self.home))
        self.assertIn(
            self.local, players_in_category(self.home, active_only=False))

    def test_no_duplicate_when_someone_is_called_up_to_their_own_team(self):
        # A redundant call-up row must not make the player appear twice — the
        # index built from this list would silently overwrite itself, and any
        # count over it would double.
        PlayerCallUp.objects.create(
            player=self.local, category=self.home, active=True,
            since=date(2026, 4, 1),
        )
        got = list(players_in_category(self.home))
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(set(got), {self.local, self.lent})

    def test_ids_helper_matches_the_queryset(self):
        self.assertEqual(
            set(player_ids_in_category(self.home)),
            {p.id for p in players_in_category(self.home)},
        )

    def test_the_api_helper_delegates_to_this_one(self):
        # ~80 call sites import it from api.scoping; it must stay in step.
        from api.scoping import players_in_category as api_version

        self.assertEqual(set(api_version(self.home)), set(players_in_category(self.home)))
        self.assertEqual(
            set(api_version(self.home, include_call_ups=False)),
            set(players_in_category(self.home, include_call_ups=False)),
        )
