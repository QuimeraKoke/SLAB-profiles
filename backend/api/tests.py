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


class ExportWorkbookTests(SimpleTestCase):
    """The pure workbook builder (§5 export) — no DB."""

    def test_builds_valid_xlsx_with_sheets(self):
        import io as _io

        from openpyxl import load_workbook

        from api.export import workbook_bytes

        data = workbook_bytes([
            {"name": "CK", "headers": ["Jugador", "Fecha", "CK (U/L)"],
             "rows": [["Díaz", "2026-07-10", 720], ["Pérez", "2026-07-10", 310]]},
            {"name": "GPS: partido/sesión?", "headers": ["Jugador"], "rows": [["X"]]},
        ])
        self.assertEqual(data[:2], b"PK")  # xlsx is a zip
        wb = load_workbook(_io.BytesIO(data))
        self.assertEqual(wb.sheetnames[0], "CK")
        self.assertTrue(all(len(n) <= 31 for n in wb.sheetnames))
        self.assertNotIn(":", wb.sheetnames[1])  # invalid char stripped
        ws = wb["CK"]
        self.assertEqual([c.value for c in ws[1]], ["Jugador", "Fecha", "CK (U/L)"])
        self.assertEqual(ws.cell(row=2, column=3).value, 720)

    def test_empty_yields_one_sheet(self):
        import io as _io

        from openpyxl import load_workbook

        from api.export import workbook_bytes

        wb = load_workbook(_io.BytesIO(workbook_bytes([])))
        self.assertEqual(len(wb.sheetnames), 1)


class StatsTests(SimpleTestCase):
    """Pure rolling-statistics helpers (dashboards/stats.py) — §1.2 + §4."""

    def test_mean_stdev_cv(self):
        from dashboards import stats

        self.assertEqual(stats.mean([2, 4, 6]), 4)
        self.assertEqual(stats.stdev([2, 4, 6]), 2.0)
        self.assertEqual(stats.cv([2, 4, 6]), 50.0)
        self.assertIsNone(stats.stdev([5]))  # <2 values
        self.assertIsNone(stats.mean([]))

    def test_ewma(self):
        from dashboards import stats

        self.assertEqual(stats.ewma([1, 1, 1], span=2), 1.0)   # constant series
        self.assertEqual(stats.ewma([0, 10], span=1), 10.0)    # span 1 → latest
        self.assertIsNone(stats.ewma([]))

    def test_deviation_full(self):
        from dashboards import stats

        d = stats.deviation(10, [2, 4, 6])
        self.assertEqual(d["centre"], 4)
        self.assertEqual(d["sd"], 2.0)
        self.assertEqual(d["z"], 3.0)
        self.assertEqual(d["pct"], 150.0)
        self.assertEqual(d["cv"], 50.0)

    def test_deviation_partial_and_empty(self):
        from dashboards import stats

        d = stats.deviation(4, [4, 4])       # zero spread
        self.assertIsNone(d["z"])
        self.assertEqual(d["pct"], 0.0)
        d1 = stats.deviation(5, [5])          # single prior → no sd
        self.assertIsNone(d1["z"])
        self.assertEqual(d1["pct"], 0.0)
        self.assertIsNone(stats.deviation(5, []))          # no prior
        self.assertIsNone(stats.deviation(None, [1, 2, 3]))  # non-numeric value

    def test_deviation_ewma_method(self):
        from dashboards import stats

        d = stats.deviation(10, [2, 4, 6], method="ewma", span=1)
        self.assertEqual(d["centre"], 6.0)   # span-1 EWMA = latest prior
        self.assertEqual(d["z"], 2.0)        # (10-6)/sd(=2)
