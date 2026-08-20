"""`_build_last_match` — which participations get to show their match data.

The rule that matters: only a role ASSERTING non-participation hides the
performance block. An unset role means "unknown", and both the GPS ingest and
the legacy import create participations without one. Reading NULL as "did not
play" hid the physical data of 338 Primer Equipo player-matches whose results
were sitting in the database the whole time — reported from the club as "no
aparecen sus datos de GPS".
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from api.triage import _build_last_match
from core.models import Category, Club, Department, Player
from events.models import Event, EventParticipant
from exams.models import ExamResult, ExamTemplate


class LastMatchPerformanceVisibilityTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="F", slug="f")
        self.cat = Category.objects.create(club=self.club, name="Primer Equipo")
        self.cat.departments.add(self.dept)
        self.template = ExamTemplate.objects.create(
            name="GPS partido", slug="gps_partido", department=self.dept,
            config_schema={"fields": [
                {"key": "tot_dist", "type": "number", "label": "Distancia", "unit": "m"},
            ]},
        )
        self.template.applicable_categories.add(self.cat)
        self.player = Player.objects.create(
            category=self.cat, first_name="Nicolas", last_name="F", is_active=True,
        )
        self.match = Event.objects.create(
            club=self.club, department=self.dept,
            event_type=Event.TYPE_MATCH, title="vs Limache",
            starts_at=timezone.now() - timedelta(days=2),
            scope=Event.SCOPE_CATEGORY, category=self.cat,
        )
        ExamResult.objects.create(
            player=self.player, template=self.template, event=self.match,
            recorded_at=self.match.starts_at, result_data={"tot_dist": 1823.27},
        )

    def _participate(self, role):
        EventParticipant.objects.create(
            event=self.match, player=self.player,
            attendance=EventParticipant.Attendance.ATTENDED, match_role=role,
        )
        return _build_last_match(self.player)

    def _slugs(self, out):
        return [p["template_slug"] for p in out["performance"]]

    # --- unknown role: the regression ----------------------------------
    def test_null_role_still_shows_performance(self):
        out = self._participate(None)
        self.assertEqual(self._slugs(out), ["gps_partido"])

    def test_blank_role_still_shows_performance(self):
        # The field is null=True AND blank=True, so "" is equally reachable.
        out = self._participate("")
        self.assertEqual(self._slugs(out), ["gps_partido"])

    def test_null_role_asserts_no_label(self):
        # Showing the data is right; inventing a role for it is not.
        out = self._participate(None)
        self.assertIsNone(out["match_role_label"])

    # --- roles that DO hide it ----------------------------------------
    def test_no_citado_hides_performance(self):
        out = self._participate(EventParticipant.MatchRole.NO_CITADO)
        self.assertEqual(out["performance"], [])

    def test_lesionado_hides_performance(self):
        out = self._participate(EventParticipant.MatchRole.LESIONADO)
        self.assertEqual(out["performance"], [])

    def test_suspendido_hides_performance(self):
        out = self._participate(EventParticipant.MatchRole.SUSPENDIDO)
        self.assertEqual(out["performance"], [])

    # --- roles that show it, with a label ------------------------------
    def test_substitute_who_came_on_shows_performance_and_label(self):
        out = self._participate(EventParticipant.MatchRole.SUPLENTE_INGRESA)
        self.assertEqual(self._slugs(out), ["gps_partido"])
        self.assertEqual(out["match_role_label"], "Suplente — ingresa")

    def test_unused_substitute_shows_performance(self):
        # He was called up and may still carry a warm-up GPS row.
        out = self._participate(EventParticipant.MatchRole.SUPLENTE_NO_INGRESA)
        self.assertEqual(self._slugs(out), ["gps_partido"])

    def test_titular_shows_performance(self):
        out = self._participate(EventParticipant.MatchRole.TITULAR)
        self.assertEqual(self._slugs(out), ["gps_partido"])

    # --- no participation row at all -----------------------------------
    def test_missing_participation_is_reported_as_no_citado(self):
        out = _build_last_match(self.player)
        self.assertEqual(out["match_role_label"], "No citado")
        self.assertEqual(out["performance"], [])
