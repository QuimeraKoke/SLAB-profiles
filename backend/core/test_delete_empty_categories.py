"""Migration 0023 — deleting categories that hold nothing.

The point of these tests is the GUARD, not the deletion. Prod is the source of
truth and does not look like local, so the migration has to refuse anything that
holds real data. It is fail-safe by construction: any relation it does not
explicitly recognise blocks the delete, so adding a `Category` FK later cannot
quietly turn this into a cascade.
"""
from __future__ import annotations

import importlib
from datetime import date

from django.apps import apps as global_apps
from django.test import TestCase

from core.models import (
    Bracket, Category, Club, Department, Player, PlayerCallUp,
    PlayerTeamMembership, TeamSeason,
)


def run_forward():
    mod = importlib.import_module("core.migrations.0023_delete_empty_categories")
    mod.forward(global_apps, None)


class DeleteEmptyCategoriesTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.empty = Category.objects.create(club=self.club, name="SUB-8")

    def test_a_category_holding_nothing_is_deleted(self):
        run_forward()
        self.assertFalse(Category.objects.filter(pk=self.empty.pk).exists())

    def test_the_first_team_is_never_touched_even_when_empty(self):
        senior = Category.objects.create(
            club=self.club, name="Primer Equipo", is_senior=True)
        run_forward()
        self.assertTrue(Category.objects.filter(pk=senior.pk).exists())

    # ── each blocker, one test: this is the part that protects prod ──────
    def test_an_inactive_player_still_blocks(self):
        # Not just active players: an inactive one is a historical record.
        Player.objects.create(
            category=self.empty, first_name="X", last_name="Y", is_active=False)
        run_forward()
        self.assertTrue(Category.objects.filter(pk=self.empty.pk).exists())

    def test_a_call_up_blocks(self):
        other = Category.objects.create(club=self.club, name="SUB-16")
        p = Player.objects.create(category=other, first_name="A", last_name="B")
        PlayerCallUp.objects.create(
            player=p, category=self.empty, active=True, since=date(2026, 3, 1))
        run_forward()
        self.assertTrue(Category.objects.filter(pk=self.empty.pk).exists())

    def test_a_membership_blocks(self):
        other = Category.objects.create(club=self.club, name="SUB-16")
        p = Player.objects.create(category=other, first_name="A", last_name="B")
        PlayerTeamMembership.objects.create(
            player=p, team=self.empty, since=date(2026, 1, 1))
        run_forward()
        self.assertTrue(Category.objects.filter(pk=self.empty.pk).exists())

    def test_a_declared_season_blocks(self):
        b = Bracket.objects.create(code="sub_12", name="Sub 12", age=12, order=2)
        TeamSeason.objects.create(team=self.empty, season=2026, bracket=b)
        run_forward()
        self.assertTrue(Category.objects.filter(pk=self.empty.pk).exists())

    def test_an_event_blocks(self):
        from events.models import Event

        dept = Department.objects.create(club=self.club, name="Médico", slug="medico")
        Event.objects.create(
            club=self.club, department=dept, category=self.empty,
            event_type=Event.TYPE_MATCH, title="vs Rival",
            starts_at="2026-06-01T15:00:00Z",
        )
        run_forward()
        self.assertTrue(Category.objects.filter(pk=self.empty.pk).exists())

    # ── accepted collateral ─────────────────────────────────────────────
    def test_a_template_link_does_not_save_it(self):
        # 9 templates pointed at each of the real shells. An M2M row to a
        # category holding no players is bookkeeping, not data.
        from exams.models import ExamTemplate

        dept = Department.objects.create(club=self.club, name="Físico", slug="fisico")
        t = ExamTemplate.objects.create(
            department=dept, name="T", slug="t", config_schema={})
        t.applicable_categories.add(self.empty)
        run_forward()
        self.assertFalse(Category.objects.filter(pk=self.empty.pk).exists())
        self.assertTrue(ExamTemplate.objects.filter(pk=t.pk).exists())

    def test_a_briefing_cache_row_does_not_save_it(self):
        # These existed precisely because the job ran over empty squads: five
        # rows per shell naming claude-opus-4-8 with items: [].
        from dashboards.models import BriefingSnapshot

        BriefingSnapshot.objects.create(
            category=self.empty, data_hash="h" * 64,
            model="claude-opus-4-8", items=[],
        )
        run_forward()
        self.assertFalse(Category.objects.filter(pk=self.empty.pk).exists())

    # ── the fail-safe itself ────────────────────────────────────────────
    def test_an_unrecognised_relation_with_rows_blocks(self):
        """The property that keeps this safe as the schema grows.

        A relation absent from `ACCEPTABLE` must block. Asserted through a real
        one — `AlertRule` — rather than a mock, so it also proves the walk over
        `related_objects` actually reaches models in other apps.
        """
        from exams.models import ExamTemplate
        from goals.models import AlertRule, AlertRuleKind

        mod = importlib.import_module("core.migrations.0023_delete_empty_categories")
        self.assertNotIn("goals.AlertRule.category", mod.ACCEPTABLE)

        dept = Department.objects.create(club=self.club, name="Físico", slug="fis")
        template = ExamTemplate.objects.create(
            department=dept, name="T", slug="t", config_schema={})
        AlertRule.objects.create(
            template=template, category=self.empty, field_key="k",
            kind=AlertRuleKind.choices[0][0], config={},
        )
        run_forward()
        self.assertTrue(Category.objects.filter(pk=self.empty.pk).exists())

    def test_it_is_idempotent(self):
        run_forward()
        run_forward()
        self.assertFalse(Category.objects.filter(pk=self.empty.pk).exists())

    def test_it_only_removes_what_is_empty(self):
        keep = Category.objects.create(club=self.club, name="Serie 2014",
                                       cohort_year=2014)
        Player.objects.create(category=keep, first_name="A", last_name="B")
        run_forward()
        self.assertTrue(Category.objects.filter(pk=keep.pk).exists())
        self.assertFalse(Category.objects.filter(pk=self.empty.pk).exists())
