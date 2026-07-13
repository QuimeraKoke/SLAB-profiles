"""API-layer helper tests that need no database.

Currently targets the pre-match-risk staleness gate: a weekly-load "over
ceiling" verdict must stop firing once its window is no longer recent, so a
stale materialized state can't keep flagging load after a player stopped
training (the "5 días libres → sobreentrenamiento" false positive, §1.4).
"""

from datetime import datetime, timedelta, timezone as _tz

from django.test import SimpleTestCase

from api.command_center import _WEEKLY_LOAD_MAX_STALE_DAYS, _weekly_load_over_ceiling


class WeeklyLoadOverCeilingTests(SimpleTestCase):
    NOW = datetime(2026, 7, 13, 9, 0, tzinfo=_tz.utc)

    def _state(self, status, days_old):
        to = (self.NOW - timedelta(days=days_old)).isoformat()
        return {"weekly_load": {"metrics": [{"status": status}], "window": {"to": to}}}

    def test_fresh_over_is_flagged(self):
        self.assertTrue(_weekly_load_over_ceiling(self._state("over", 0), self.NOW))
        self.assertTrue(_weekly_load_over_ceiling(self._state("over", 2), self.NOW))

    def test_stale_over_is_suppressed(self):
        # The core bug: an "over" verdict on an old window must NOT fire.
        self.assertFalse(_weekly_load_over_ceiling(self._state("over", 5), self.NOW))

    def test_staleness_boundary(self):
        self.assertTrue(
            _weekly_load_over_ceiling(
                self._state("over", _WEEKLY_LOAD_MAX_STALE_DAYS), self.NOW
            )
        )
        self.assertFalse(
            _weekly_load_over_ceiling(
                self._state("over", _WEEKLY_LOAD_MAX_STALE_DAYS + 1), self.NOW
            )
        )

    def test_not_over_is_false(self):
        self.assertFalse(_weekly_load_over_ceiling(self._state("within", 0), self.NOW))

    def test_missing_or_malformed_is_false(self):
        self.assertFalse(_weekly_load_over_ceiling(None, self.NOW))
        self.assertFalse(_weekly_load_over_ceiling({}, self.NOW))
        # "over" but no window
        self.assertFalse(
            _weekly_load_over_ceiling(
                {"weekly_load": {"metrics": [{"status": "over"}]}}, self.NOW
            )
        )
        # "over" but unparseable window.to
        self.assertFalse(
            _weekly_load_over_ceiling(
                {"weekly_load": {"metrics": [{"status": "over"}], "window": {"to": "garbage"}}},
                self.NOW,
            )
        )
