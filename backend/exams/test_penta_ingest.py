"""Pentacompartimental ingest — workbook parsing, cell coercion, name matching.

Covers `exams.penta_ingest`, the engine behind the `import_pentacompartimental`
CLI. Note that RAW_MAP reads the sheet BY COLUMN INDEX, so a real ISAK export
whose columns shift (a dropped column, an extra one) misfiles every measurement
silently — `talla` lands in `peso` with no error. Nothing here can catch that
for an arbitrary third-party file; the guard is that the export layout is fixed.

None of these need a database.
"""
from __future__ import annotations

import io
from datetime import date

import openpyxl
from django.test import SimpleTestCase

from exams import penta_ingest as P


class ColumnLayoutTests(SimpleTestCase):
    def test_name_and_date_columns_are_not_measurement_columns(self):
        # RAW_MAP is index-based; overlapping it with the name/date columns
        # would read a player's name as a measurement.
        self.assertNotIn(P.NAME_COL, P.RAW_MAP)
        self.assertNotIn(P.DATE_COL, P.RAW_MAP)

    def test_raw_map_covers_the_27_isak_measurements(self):
        self.assertEqual(len(P.RAW_MAP), 27)
        self.assertEqual(len(set(P.RAW_MAP.values())), 27, "duplicate field key")


class ParseWorkbookTests(SimpleTestCase):
    def _book(self, sheet_name=P.SHEET, rows=()):
        wb = openpyxl.Workbook()
        wb.active.title = sheet_name
        ws = wb.active
        for i, row in enumerate(rows, start=P.FIRST_DATA_ROW):
            for j, v in enumerate(row, start=1):
                ws.cell(row=i, column=j, value=v)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_rejects_a_non_xlsx_payload(self):
        with self.assertRaises(P.PentaParseError):
            P.parse_workbook(b"this is not a spreadsheet")

    def test_rejects_a_workbook_without_the_expected_sheet(self):
        with self.assertRaises(P.PentaParseError) as ctx:
            P.parse_workbook(self._book(sheet_name="Otra hoja"))
        self.assertIn("Otra hoja", str(ctx.exception))

    def test_skips_the_four_title_rows(self):
        # Only row 6 onward is data; the header rows must not surface.
        rows = P.parse_workbook(self._book(rows=[("Solo Yo", "05/08/2026")]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Solo Yo")


class CellCoercionTests(SimpleTestCase):
    def test_dates_in_the_export_and_iso_formats(self):
        self.assertEqual(P._to_date("05/08/2026"), date(2026, 8, 5))
        self.assertEqual(P._to_date("05-08-2026"), date(2026, 8, 5))
        self.assertEqual(P._to_date("2026-08-05"), date(2026, 8, 5))

    def test_day_first_is_not_read_as_month_first(self):
        # 13/07 is unambiguous: month-first parsing would raise, not silently
        # swap — but pin it so a future format change can't flip the order.
        self.assertEqual(P._to_date("13/07/2026"), date(2026, 7, 13))

    def test_unparseable_and_blank_dates_are_none(self):
        for bad in (None, "", "no es fecha", "32/13/2026"):
            self.assertIsNone(P._to_date(bad))

    def test_numbers_round_and_reject_text(self):
        self.assertEqual(P._num("75.7"), 75.7)
        self.assertEqual(P._num(1 / 3), 0.3333)
        self.assertIsNone(P._num("No aplica"))
        self.assertIsNone(P._num(None))


class NameTokenTests(SimpleTestCase):
    def test_accents_and_case_are_ignored(self):
        self.assertEqual(P._tokens("Cristóbal ULLOA"), ["cristobal", "ulloa"])

    def test_single_letter_tokens_are_dropped(self):
        self.assertNotIn("y", P._tokens("Juan y Pedro"))

    def test_prefix_match_handles_the_bolano_case(self):
        self.assertTrue(P._tok_match("bolano", "bolanos"))
        self.assertTrue(P._tok_match("bolanos", "bolano"))

    def test_short_tokens_do_not_prefix_match(self):
        # <4 chars must be exact, else "ana" would match "anastaze".
        self.assertFalse(P._tok_match("ana", "anastaze"))

    def test_unrelated_tokens_do_not_match(self):
        self.assertFalse(P._tok_match("vargas", "valenzuela"))


class PlausibilityGuardTests(SimpleTestCase):
    """The column-alignment guard.

    Exists because of 20 youth assessments found on 2026-08-22 holding `talla`
    values of 30–68 cm. A source file carried an extra leading column (the
    player's age), shifting every reading one field right: age → `peso`, weight →
    `talla`, height → `talla_sentado`. Nothing raised. The 5-mass decomposition
    was computed from the shifted inputs and produced a BMI of 54 and a muscle
    mass of 6.5 kg, which then went straight into those players' charts.

    A shifted row cannot be repaired afterwards — the true last reading
    (`pliegue_pierna`) lands in column 31, outside the read range — so the only
    place to catch it is the door.
    """

    def test_a_normal_assessment_passes(self):
        self.assertTrue(P.plausible_anthropometry({"talla": 148.6, "peso": 44.7}))
        self.assertTrue(P.plausible_anthropometry({"talla": 188.5, "peso": 84.0}))

    def test_the_real_shifted_rows_are_rejected(self):
        # Verbatim from the corrupted rows: weight landed in `talla`, age in
        # `peso`.
        for talla, peso in ((45.15, 11.0), (30.25, 10.6), (66.45, 14.9), (68.1, 15.0)):
            self.assertFalse(
                P.plausible_anthropometry({"talla": talla, "peso": peso}),
                f"talla={talla} peso={peso} debería rechazarse",
            )

    def test_height_in_metres_is_rejected(self):
        # The other plausible misencoding, and 1.48 would sail through any
        # "is it a number?" check.
        self.assertFalse(P.plausible_anthropometry({"talla": 1.48, "peso": 44.7}))

    def test_a_missing_value_is_not_plausible(self):
        self.assertFalse(P.plausible_anthropometry({"talla": 150.0}))
        self.assertFalse(P.plausible_anthropometry({"peso": 44.7}))
        self.assertFalse(P.plausible_anthropometry({}))

    def test_the_bounds_are_wide_enough_for_real_squads(self):
        # This club's real extremes: a 2014-born at 131 cm and a senior at
        # 194 cm. The guard must not reject either.
        from exams.penta_ingest import PESO_RANGE, TALLA_RANGE, plausible_anthropometry

        self.assertLessEqual(P.TALLA_RANGE[0], 131.0)
        self.assertGreaterEqual(P.TALLA_RANGE[1], 194.0)
        self.assertLessEqual(P.PESO_RANGE[0], 30.0)
