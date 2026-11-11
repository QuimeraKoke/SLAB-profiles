"""Guards for `exams.formativo_saltos_ingest` (the club's jump-control sheets).

Each test pins something the real sheets do: columns located by headers (a
weight column shifts everything; a blank POST header), the sheet's "BEST"
being an average (ignored), names written five ways, the paternal surname,
tabs with no date, and the club's reviewed table beating the alignment.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket, Category, Club, Department, Player, TeamSeason
from exams import formativo_saltos_ingest as ing
from exams.models import ExamResult, ExamTemplate

RCMJ_HEAD = ["MIXTA 1", "ALTURA DE CAIDA ", "", "", "", "", "", "", "TIEMPO DE CONTACTO", "", "", "", "", "", "",
             "ALTURA DEL SALTO REBOUND", "", "", "", "", "", "", "RSI PRE", "RSI POST"]
SUB7 = ["PRE 1", "PRE 2", "BEST PRE", "POST 1", "POST 2", "BEST POST", "Δ%"]
RCMJ_SUB = ["DEPORTISTA"] + SUB7 * 3 + ["Δ", "Δ"]


def rcmj_row(name, caida=(0.20, 0.21, 0.23, 0.21), contacto=(0.22, 0.225, 0.207, 0.221),
             rebote=(0.303, 0.357, 0.387, 0.356)):
    def block(v):
        return [v[0], v[1], (v[0] + v[1]) / 2, v[2], v[3], (v[2] + v[3]) / 2, 0]
    return [name] + block(caida) + block(contacto) + block(rebote) + [1.4, 1.7]


class ParseTests(SimpleTestCase):
    def test_r_cmj_por_encabezados_y_rsi_por_intento(self):
        tab = ing.parse_tab("M40 CLOA", [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")])
        self.assertEqual((tab.test, tab.number, tab.suffix, tab.label), ("rcmj", 40, "CLOA", "MIXTA 1"))
        data = ing.with_rsi(tab.test, tab.rows[0][1])
        self.assertAlmostEqual(data["rsi_pre_1"], round(0.303 / 0.22, 3))
        # El "BEST" de la planilla es un promedio: se ignora, el mejor es el máximo.
        self.assertEqual(data["rsi_pre_best"], max(data["rsi_pre_1"], data["rsi_pre_2"]))
        self.assertEqual(data["rsi_metodo"], "rebote / contacto")
        self.assertIn("rsi_delta_pct", data)

    def test_una_columna_de_peso_al_inicio_no_corre_los_datos(self):
        head = ["", "PESO 03-07-26"] + RCMJ_HEAD[1:]
        sub = ["DEPORTISTA", ""] + RCMJ_SUB[1:]
        row = [rcmj_row("KORN")[0], 72.5] + rcmj_row("KORN")[1:]
        tab = ing.parse_tab("M26", [head, sub, row])
        self.assertEqual(tab.rows[0][1]["contacto_pre_1"], 0.22)

    def test_post_sin_encabezado_se_ubica_despues_de_best_pre(self):
        sub = list(RCMJ_SUB)
        sub[4] = sub[5] = ""          # POST 1 / POST 2 del primer grupo sin título
        tab = ing.parse_tab("M9", [RCMJ_HEAD, sub, rcmj_row("KORN")])
        self.assertEqual(tab.rows[0][1]["caida_post_1"], 0.23)

    def test_cmj_usa_el_rsi_mod(self):
        head = ["VALD CMJ", "ALTURA DE SALTO", "", "", "", "", "", "", "RSI Mod", "", "", "", "", "", ""]
        sub = ["DEPORTISTA"] + SUB7 * 2
        row = ["CANELO", 40, 44, 44, 40.4, 43.3, 43.3, -1.6, 0.55, 0.61, 0.61, 0.57, 0.58, 0.58, -4.9]
        tab = ing.parse_tab("M10", [head, sub, row])
        data = ing.with_rsi(tab.test, tab.rows[0][1])
        self.assertEqual((tab.test, data["rsi_pre_best"], data["rsi_post_best"]), ("cmj", 0.61, 0.58))

    def test_promedio_y_textos_sueltos_no_son_jugadores(self):
        tab = ing.parse_tab("M40", [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN"),
                                    ["PROMEDIO", 0.2], ["Q1PQ"], ["ALBURQUENQUE", "", "#DIV/0!"]])
        self.assertEqual([n for n, _ in tab.rows], ["KORN"])

    def test_totales_y_control_de_peso_no_son_pestanas_de_salto(self):
        self.assertIsNone(ing.parse_tab("Totales", [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")]))
        self.assertIsNone(ing.parse_tab("CONTROL DE PESO", [["", "x"], ["DEPORTISTA", "14.09.26"], ["KORN", 70]]))

    def test_cinco_formas_de_escribir_un_nombre(self):
        self.assertEqual(ing.name_parts("K. GUZMAN"), (["GUZMAN"], ["K"]))
        self.assertEqual(ing.name_parts("S.GARCES"), (["GARCES"], ["S"]))
        self.assertEqual(ing.name_parts("CORTES B"), (["CORTES"], ["B"]))
        self.assertEqual(ing.name_parts("FUENTES M S14"), (["FUENTES"], ["M"]))
        self.assertEqual(ing.name_parts("DIEGO COFRE"), (["DIEGO", "COFRE"], []))

    def test_fecha_en_el_titulo(self):
        self.assertEqual(ing.date_in_title("M42 07-11", 2026), date(2026, 11, 7))
        self.assertEqual(ing.date_in_title("M42 7/11/26", 2026), date(2026, 11, 7))
        self.assertIsNone(ing.date_in_title("M40 CLOA", 2026))


class P:
    def __init__(self, pid, first, last, second=""):
        self.id, self.first_name, self.last_name, self.second_last_name, self.middle_name = pid, first, last, second, ""


class NameMatcherTests(SimpleTestCase):
    def test_manda_el_apellido_paterno(self):
        tomas, vicente = P(1, "Tomas", "Gonzalez", "Sandoval"), P(2, "Vicente", "Ramirez", "Gonzalez")
        m = ing.NameMatcher([tomas, vicente], [])
        self.assertEqual(m.match("GONZALEZ T")[0], tomas)
        self.assertEqual(m.match("GONZALEZ")[0], tomas, "el materno sólo si nadie calza por el paterno")

    def test_empate_por_quien_jugo_el_partido(self):
        b, s = P(1, "Benjamin", "Garces"), P(2, "Simon", "Garces")
        m = ing.NameMatcher([b, s], [])
        self.assertEqual(m.match("GARCES"), (None, "ambiguo (2)"))
        self.assertEqual(m.match("GARCES", played={2})[0], s)

    def test_empate_por_el_que_es_del_equipo(self):
        benja, clemente = P(1, "Benjamin", "Salas"), P(2, "Clemente", "Salas")
        m = ing.NameMatcher([benja, clemente], [], activity={1: 153, 2: 2})
        self.assertEqual(m.match("SALAS")[0], benja)

    def test_un_nombre_de_pila_solo_no_alcanza(self):
        m = ing.NameMatcher([P(1, "Diego", "Cofre")], [])
        self.assertEqual(m.match("DIEGO"), (None, "sin coincidencia"))


class AlignTests(SimpleTestCase):
    def test_un_microciclo_es_el_periodo_entre_partidos_y_la_sigla_decide(self):
        tabs = [ing.Tab(t, n, suf, "", "rcmj") for t, n, suf in
                (("M39", 39, ""), ("M40 CLOA", 40, "CLOA"), ("M40 UE", 40, "UE"))]
        kinds = {date(2026, 10, 17): "official", date(2026, 10, 22): "official",
                 date(2026, 10, 25): "official", date(2026, 10, 28): "friendly"}
        opp = {date(2026, 10, 17): "COLO COLO", date(2026, 10, 22): "COBRELOA",
               date(2026, 10, 25): "UNION ESPAÑOLA", date(2026, 10, 28): "COLINA"}
        out = ing.align_between_matches(tabs, kinds, opp, {}, ing.NameMatcher([], []), date(2026, 11, 3))
        # Con el amistoso del 28 la alineación corre las siglas; sin él, calzan.
        self.assertEqual(out, {"M39": date(2026, 10, 17), "M40 CLOA": date(2026, 10, 22),
                               "M40 UE": date(2026, 10, 25)})


class RunTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.get_or_create(code=code, defaults={"name": name, "age": age, "order": order})
        cls.cat = Category.objects.create(club=cls.club, name="SUB-20")
        TeamSeason.objects.create(team=cls.cat, season=2026, bracket=Bracket.objects.get(name="Sub 20"))
        cls.korn = Player.objects.create(category=cls.cat, first_name="Agustin", last_name="Korn")

    def write(self, tmp, tabs):
        import openpyxl
        book = openpyxl.Workbook()
        book.remove(book.active)
        for title, rows in tabs.items():
            ws = book.create_sheet(title)
            for r in rows:
                ws.append(r)
        path = Path(tmp) / "U20_Plantilla_control_carga_CMJ.xlsx"
        book.save(path)
        return str(path)

    def test_la_fecha_del_titulo_y_la_tabla_del_club_ganan(self):
        from load_control.models import JumpTabMatch
        JumpTabMatch.objects.create(club=self.club, team="U20", season=2026, tab="M40 CLOA",
                                    match_date=date(2026, 10, 22))
        JumpTabMatch.objects.create(club=self.club, team="U20", season=2026, tab="M33", match_date=None)
        with TemporaryDirectory() as tmp:
            path = self.write(tmp, {"M40 CLOA": [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")],
                                    "M42 07-11": [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")],
                                    "M33": [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")]})
            rep = ing.run(path, self.club, season=2026, commit=True)
        self.assertEqual(dict(rep.por_fuente), {"club": 1, "titulo": 1})
        rows = {r.result_data["hoja"]: r for r in ExamResult.objects.filter(template__slug="control_salto")}
        self.assertEqual(set(rows), {"M40 CLOA", "M42 07-11"}, "M33: el club dijo que no es partido")
        self.assertEqual(rows["M40 CLOA"].recorded_at.date(), date(2026, 10, 22))
        self.assertEqual((rows["M42 07-11"].result_data["fecha_fuente"], rows["M42 07-11"].player), ("titulo", self.korn))

    def test_correrlo_dos_veces_no_duplica(self):
        with TemporaryDirectory() as tmp:
            path = self.write(tmp, {"M42 07-11": [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")]})
            ing.run(path, self.club, season=2026, commit=True)
            rep = ing.run(path, self.club, season=2026, commit=True)
        self.assertEqual((rep.creados, rep.sin_cambios), (0, 1))
        self.assertEqual(ExamResult.objects.filter(template__slug="control_salto").count(), 1)

    def test_el_sync_automatico_no_mueve_una_fecha_propuesta(self):
        """The hourly sync must not silently re-date a team's history when the
        calendar alignment shifts; the manual command still re-aligns."""
        from unittest import mock

        tab = "M41"
        with TemporaryDirectory() as tmp:
            path = self.write(tmp, {tab: [RCMJ_HEAD, RCMJ_SUB, rcmj_row("KORN")]})
            with mock.patch.object(ing, "date_in_title", return_value=None), \
                    mock.patch.object(ing, "align_between_matches", return_value={tab: date(2026, 10, 25)}):
                ing.run(path, self.club, season=2026, commit=True)
            with mock.patch.object(ing, "date_in_title", return_value=None), \
                    mock.patch.object(ing, "align_between_matches", return_value={tab: date(2026, 10, 31)}):
                ing.run(path, self.club, season=2026, commit=True, keep_proposed_dates=True)
                row = ExamResult.objects.get(template__slug="control_salto")
                self.assertEqual((row.result_data["fecha_partido"], row.recorded_at.date()),
                                 ("2026-10-25", date(2026, 10, 25)), "automático: se queda donde estaba")
                ing.run(path, self.club, season=2026, commit=True)
                row.refresh_from_db()
                self.assertEqual(row.result_data["fecha_partido"], "2026-10-31", "a mano: re-alinea")
