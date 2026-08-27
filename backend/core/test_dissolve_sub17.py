"""Migration 0024 — the guards on re-homing a player.

The ids in `MOVES` were verified by hand, so these tests exercise `move_player`,
which is where the safety lives: every guard re-checks the fact that justifies
the move and refuses otherwise, because prod is the source of truth and may not
look like local.

The sex guard is here for a specific near-miss. The obvious generalisation of
this migration — "move each player to the Serie matching their birth year" —
would have moved `SUB-16 F - Femenino`'s single player, born 2009, into
`Serie 2009`, a male team.
"""
from __future__ import annotations

import importlib
from datetime import date

from django.test import TestCase

from core.models import Category, Club, Player

mod = importlib.import_module("core.migrations.0024_dissolve_sub17")


class MovePlayerGuardTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.bucket = Category.objects.create(club=self.club, name="SUB-17")
        self.serie09 = Category.objects.create(
            club=self.club, name="Serie 2009", cohort_year=2009)
        Player.objects.create(
            category=self.serie09, first_name="Ya", last_name="Estaba",
            date_of_birth=date(2009, 5, 1), sex="M")

    def _player(self, year=2009, sex="M"):
        return Player.objects.create(
            category=self.bucket, first_name="A", last_name="B",
            date_of_birth=date(year, 3, 3), sex=sex,
        )

    def test_a_matching_player_moves(self):
        p = self._player()
        self.assertEqual(mod.move_player(p, self.serie09), "")
        p.refresh_from_db()
        self.assertEqual(p.category, self.serie09)

    def test_a_mismatched_birth_year_refuses(self):
        # The fact that justifies the whole move. Without it this is just
        # reassigning someone to a team they don't belong to.
        p = self._player(year=2011)
        why = mod.move_player(p, self.serie09)
        self.assertIn("año de nacimiento", why)
        p.refresh_from_db()
        self.assertEqual(p.category, self.bucket)

    def test_a_player_of_the_other_sex_refuses(self):
        """The near-miss this guard exists for.

        A generic version of this migration would have put SUB-16 F's only
        player — born 2009, female — into the male Serie 2009.
        """
        p = self._player(sex="F")
        why = mod.move_player(p, self.serie09)
        self.assertIn("sexo", why)
        p.refresh_from_db()
        self.assertEqual(p.category, self.bucket)

    def test_a_destination_in_another_club_refuses(self):
        other = Club.objects.create(name="Otro")
        far = Category.objects.create(club=other, name="Serie 2009", cohort_year=2009)
        p = self._player()
        self.assertIn("otro club", mod.move_player(p, far))

    def test_a_missing_destination_refuses(self):
        p = self._player()
        self.assertIn("no existe", mod.move_player(p, None))

    def test_a_player_without_a_birth_date_refuses(self):
        p = Player.objects.create(
            category=self.bucket, first_name="A", last_name="B", sex="M")
        self.assertIn("sin fecha", mod.move_player(p, self.serie09))

    def test_an_empty_destination_does_not_trip_the_sex_guard(self):
        # A serie with no other players has no sex to compare against; the guard
        # must not block on absence of evidence.
        empty = Category.objects.create(
            club=self.club, name="Serie 2008", cohort_year=2008)
        p = self._player(year=2008)
        self.assertEqual(mod.move_player(p, empty), "")
        p.refresh_from_db()
        self.assertEqual(p.category, empty)

    def test_the_move_keeps_the_players_history(self):
        # Exams and appearances hang off the player, not the team, which is why
        # re-homing costs nothing. Pinned because it is the reason this is safe.
        from django.utils import timezone

        from core.models import Department
        from exams.models import ExamResult, ExamTemplate

        dept = Department.objects.create(club=self.club, name="Físico", slug="fis")
        tpl = ExamTemplate.objects.create(
            department=dept, name="T", slug="t", config_schema={})
        p = self._player()
        ExamResult.objects.create(
            template=tpl, player=p, recorded_at=timezone.now(), result_data={})

        mod.move_player(p, self.serie09)

        self.assertEqual(ExamResult.objects.filter(player=p).count(), 1)
