"""Composición corporal formativo (summary sheet → pentacompartimental)."""
from __future__ import annotations

from datetime import date, datetime, time

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams import composicion_ingest as C
from exams import sync_issues as si
from exams.calculations import EXTERNAL, compute_result_data
from exams.models import ExamResult, ExamTemplate

HEAD = [
    ["", "", "Medidas básicas", "", "Masa Muscular", "", "Masa Adiposa", "", "Indices",
     "Sumatoria de Pliegues [mm]", "Indice de Maduración", "Peak Height Velocity",
     "Centímetros por crecer", "Estatura Proyectada [cms]"],
    ["PACIENTES", "Informes", "M. corporal", "Talla", "kg", "%", "kg", "%", "IMO", "6 Pliegues",
     "Mirwald", "Mirwald", "Mirwald", "Mirwald"],
]


def row(name, when, peso=70.0, mm=35.0, ma=14.0, **kw):
    r = [name, when, peso, kw.get("talla", 175.0), mm, kw.get("mmp", round(mm / peso * 100, 2)), ma,
         kw.get("map", round(ma / peso * 100, 2)), 4.1, 40, kw.get("mirwald", ""), "", "", ""]
    return r


class ParseTests(SimpleTestCase):
    def test_columns_by_header_not_by_position(self):
        cols = C.columnas(HEAD)
        self.assertEqual(cols[2], "peso")
        self.assertEqual(cols[5], "masa_muscular_pct")
        self.assertEqual(cols[7], "masa_adiposa_pct")
        self.assertEqual(cols[10], "mirwald_offset")
        self.assertEqual(cols[13], "estatura_proyectada")

    def test_comma_decimals_and_text_dates(self):
        f = C.parse("SUB 15", HEAD + [["Juan Pérez", "13/10/2026", "80,45", "187", "36,553", "45,44"]])[0]
        self.assertEqual((f.fila, f.fecha, f.valores["peso"], f.valores["masa_muscular"]),
                         (3, date(2026, 10, 13), 80.45, 36.553))

    def test_shifted_row_is_detected(self):
        self.assertIsNone(C._incoherente({"peso": 70, "masa_muscular": 35, "masa_muscular_pct": 50}))
        self.assertIn("corridas", C._incoherente({"peso": 19.6, "masa_muscular": 174.1, "masa_muscular_pct": 34.7}))


class ComputeKeepsExternalValuesTests(TestCase):
    def test_masses_from_outside_are_not_blanked(self):
        club = Club.objects.create(name="Club")
        dept = Department.objects.create(club=club, name="Nutricional", slug="nutri")
        t = ExamTemplate.objects.create(department=dept, name="P", slug="p", config_schema={"fields": [
            {"key": "peso", "type": "number"}, {"key": "talla", "type": "number"},
            {"key": "masa_muscular", "type": "calculated", "formula": "[parte_muscular] * 2"},
            {"key": "imc", "type": "calculated", "formula": "[peso] / (([talla] / 100) ** 2)"},
        ]})
        plain, _ = compute_result_data(t, {"peso": 70, "talla": 175, "masa_muscular": 35})
        self.assertIsNone(plain["masa_muscular"])
        kept, _ = compute_result_data(t, {"peso": 70, "talla": 175, "masa_muscular": 35, EXTERNAL: "planilla"})
        self.assertEqual(kept["masa_muscular"], 35)
        self.assertAlmostEqual(kept["imc"], 22.857, places=2)  # the missing ones are still computed


class RunTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Club")
        dept = Department.objects.create(club=self.club, name="Nutricional", slug="nutri")
        self.t = ExamTemplate.objects.create(department=dept, name="Penta", slug="pentacompartimental",
                                             config_schema={"fields": [
                                                 {"key": "peso", "type": "number", "min": 20, "max": 150},
                                                 {"key": "talla", "type": "number", "min": 100, "max": 220},
                                                 {"key": "masa_muscular", "type": "calculated",
                                                  "formula": "[parte_muscular] * 2"},
                                             ]})
        self.u15 = Category.objects.create(club=self.club, name="SUB-15")
        fem = Category.objects.create(club=self.club, name="SUB-19 F - Femenino")
        self.juan = Player.objects.create(category=self.u15, first_name="Juan", last_name="Pérez")
        self.ana = Player.objects.create(category=fem, first_name="Ana", last_name="Rojas")
        Player.objects.create(category=self.u15, first_name="Ana", last_name="Rojas")  # a boy namesake

    def filas(self, *rows, tab="SUB 15"):
        return C.parse(tab, HEAD + [list(r) for r in rows])

    def test_creates_marked_results_keeping_the_masses(self):
        rep = C.run(self.club, self.filas(row("Juan Pérez", "08/10/2026", mirwald=-1.5)), commit=True)
        self.assertEqual(rep.creados, 1)
        r = ExamResult.objects.get()
        self.assertEqual((r.player, r.result_data["masa_muscular"], r.result_data["mirwald_offset"]),
                         (self.juan, 35.0, -1.5))
        self.assertEqual((r.result_data[EXTERNAL], r.result_data["origen"]), ("planilla", C.ORIGEN))
        self.t.refresh_from_db()
        self.assertIn("mirwald_offset", {f["key"] for f in self.t.config_schema["fields"]})

    def test_rerun_is_idempotent_and_applies_corrections(self):
        C.run(self.club, self.filas(row("Juan Pérez", "08/10/2026")), commit=True)
        rep = C.run(self.club, self.filas(row("Juan Pérez", "08/10/2026")), commit=True)
        self.assertEqual((rep.creados, rep.iguales), (0, 1))
        rep = C.run(self.club, self.filas(row("Juan Pérez", "08/10/2026", peso=71.0)), commit=True)
        self.assertEqual(rep.actualizados, 1)
        self.assertEqual(ExamResult.objects.get().result_data["peso"], 71.0)

    def test_an_isak_assessment_near_the_date_wins(self):
        ExamResult.objects.create(template=self.t, player=self.juan, result_data={"peso": 70},
                                  recorded_at=timezone.make_aware(datetime.combine(date(2026, 10, 6), time(12))))
        rep = C.run(self.club, self.filas(row("Juan Pérez", "08/10/2026")), commit=True)
        self.assertEqual((rep.ya_estaban, rep.creados, ExamResult.objects.count()), (1, 0, 1))

    def test_bad_rows_are_reported_not_loaded(self):
        rep = C.run(self.club, self.filas(
            row("Juan Pérez", "", peso=70),                           # no date
            row("Juan Pérez", "01/09/2026", peso=19.6, mm=174.1, mmp=34.7),  # shifted columns
            row("Nadie Conocido", "01/09/2026"),
        ), commit=True)
        self.assertEqual((rep.creados, len(rep.rechazadas), list(rep.sin_jugador)),
                         (0, 2, [("SUB 15", "Nadie Conocido")]))
        col = si.IssueCollector(self.club, "composicion_formativo", commit=False)
        si.from_composicion(col, rep, "Composición")
        kinds = sorted(i["kind"] for i in col.items.values())
        self.assertEqual(kinds, ["fila_rechazada", "fila_rechazada", "fuera_de_rango", "jugador_no_encontrado"])

    def test_women_tab_matches_only_women(self):
        C.run(self.club, self.filas(row("Ana Rojas", "01/09/2026", peso=55, mm=27, ma=12), tab="PLANTEL FEM"),
              commit=True)
        self.assertEqual(ExamResult.objects.get().player, self.ana)

    def test_twin_whose_middle_name_is_the_other_first_name(self):
        fem = Category.objects.get(name__contains="Femenino")
        g = Player.objects.create(category=fem, first_name="Grettel", last_name="Suazo")
        Player.objects.create(category=fem, first_name="Arantza", middle_name="Grettel", last_name="Suazo")
        C.run(self.club, self.filas(row("Grettel Suazo", "01/09/2026", peso=55, mm=27, ma=12), tab="PLANTEL FEM"),
              commit=True)
        self.assertEqual(ExamResult.objects.get().player, g)
