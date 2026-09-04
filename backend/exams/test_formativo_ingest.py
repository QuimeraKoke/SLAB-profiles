"""Guards for `exams.formativo_ingest`.

Four bugs showed up in this parser during phase 6, and every one of them was
silent — the import printed a clean report while losing or corrupting data:

* the test-name column in `CARRERAS` is headed `NEUROMUSCULAR`, so looking it
  up by the sheet's name read 0 of 4341 rows;
* `PRESS DE BANCO` has a phantom leading `FECHA`, so every value sat one column
  left of its own header and `PESO CORPORAL` would have come from the position;
* unattempted loads are written as `0`, which failed the 0.1 m/s floor and took
  678 of 682 `FUERZA` sessions down with them;
* 200 rows have no date at all and were dropped without a word.

Each has a test here. The fixtures are built with openpyxl so they hold the
same shape as the club's file, quirks included.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket, Category, Club, Department, Player
from exams import formativo_ingest as ing
from exams.models import ExamResult, ExamTemplate

D = datetime(2026, 3, 11)


def escribir(ruta: Path, hojas: dict[str, tuple[list, list]]) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    book.remove(book.active)
    for nombre, (cab, filas) in hojas.items():
        ws = book.create_sheet(nombre)
        ws.append(cab)
        for f in filas:
            ws.append(f)
    book.save(ruta)


CAB_LARGO = ["FECHA", "JUGADOR", "FECHA DE NACIMIENTO", "EDAD", "CATEGORÍA",
             "POSICIÓN", "NEUROMUSCULAR", "REP 1", "REP 2", "REP 3", "BEST", "PROM"]
CAB_FUERZA = ["FECHA", "JUGADOR", "FECHA DE NACIMIENTO", "EDAD", "CATEGORÍA",
              "POSICIÓN", "PESO CORPORAL (kg)", "1RM (kg)", "%RM", "FR (1RM/PC)",
              "ULTIMA CARGA (m/s)", "ULTIMA CARGA (kg)",
              "20 KG (1)", "20 KG (2)", "20 KG (3)", "BEST 20 KG",
              "30 KG (1)", "30 KG (2)", "30 KG (3)", "BEST 30 KG"]


class FormativoIngestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.dept = Department.objects.create(club=cls.club, name="Físico",
                                             slug="fisico")
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.create(code=code, name=name, age=age, order=order)
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2010",
                                          cohort_year=2010)
        cls.player = Player.objects.create(
            category=cls.cat, first_name="Damian", last_name="Solis",
            second_last_name="Rojas", date_of_birth=date(2010, 5, 4))

    def setUp(self):
        from django.core.management import call_command
        from io import StringIO
        call_command("seed_formativo_templates", "--club", self.club.name,
                     "--season", "2026", stdout=StringIO())

    def correr(self, hojas, **kw):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "eval.xlsx"
            escribir(ruta, hojas)
            return ing.run(str(ruta), self.club, **kw)

    # ── el pivot de las hojas largas ────────────────────────────────────
    def test_los_cuatro_tests_de_un_dia_son_UN_resultado(self):
        """La hoja escribe una fila por test; el club corrió UNA sesión.

        Un resultado por fila daría cuatro exámenes casi vacíos el mismo día y
        cuatro puntos diarios en cada gráfico.
        """
        filas = [
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "EXTREMO",
             "T10 (s)", 1.82, 1.79, None, 1.79, 1.81],
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "EXTREMO",
             "T30 (s)", 4.21, 4.18, None, 4.18, 4.20],
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "EXTREMO",
             "COD 505 DER", 2.31, 2.28, None, 2.28, 2.30],
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "EXTREMO",
             "COD 505 IZQ", 2.45, 2.41, None, 2.41, 2.43],
        ]
        rep = self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        self.assertEqual(rep.creados, 1)
        r = ExamResult.objects.get(template__slug="carreras")
        self.assertEqual(r.result_data["t10_1"], 1.82)
        self.assertEqual(r.result_data["t30_1"], 4.21)
        self.assertEqual(r.result_data["cod_der_1"], 2.31)
        self.assertEqual(r.result_data["cod_izq_1"], 2.45)

    def test_la_columna_del_test_se_encuentra_aunque_se_llame_NEUROMUSCULAR(self):
        """En `CARRERAS` la columna del test está titulada `NEUROMUSCULAR`.

        El club armó esa hoja copiando la otra y dejó el encabezado. Buscarla
        por el nombre de la hoja leyó 0 de 4341 filas y el reporte salió
        limpio.
        """
        filas = [[D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
                  "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]]
        rep = self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        self.assertEqual(rep.creados, 1)

    def test_el_mejor_no_se_toma_del_archivo(self):
        # Es derivado: la plantilla lo calcula. Importarlo guardaría la misma
        # conclusión dos veces y las dejaría divergir.
        filas = [[D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
                  "T10 (s)", 1.82, 1.79, None, 99.9, 1.81]]
        self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        r = ExamResult.objects.get(template__slug="carreras")
        self.assertEqual(r.result_data["t10_best"], 1.79,
                         "debía recalcularlo, no copiar el 99.9 del archivo")

    # ── el encabezado corrido ───────────────────────────────────────────
    def test_detecta_el_encabezado_corrido_de_PRESS_DE_BANCO(self):
        """La hoja declara `FECHA` y sus filas empiezan en el nombre.

        Leída literal, `PESO CORPORAL` sale de la columna de la posición.
        """
        cab = ["FECHA", "JUGADOR", "FECHA DE NACIMIENTO", "EDAD", "CATEGORÍA",
               "POSICIÓN", "PESO CORPORAL (kg)", "1RM (kg)", "%RM", "FR (1RM/PC)",
               "ULTIMA CARGA (m/s)", "ULTIMA CARGA (kg)"]
        # Una columna menos: el dato arranca en JUGADOR.
        filas = [["DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16",
                  "EXTREMO", 47.85, 34.53, 86.9, 0.72, 0.5, 30]]
        filas_ok, sin_fecha = ing._parse_ancho(
            _hoja_temporal({"PRESS DE BANCO": (cab, filas)}, "PRESS DE BANCO"),
            "PRESS DE BANCO")
        # Sin columna de fecha no hay resultado posible, pero el corrimiento se
        # detecta: el nombre se lee bien y la fila se cuenta como sin fecha.
        self.assertEqual(sin_fecha, 1)
        self.assertEqual(filas_ok, [])

    # ── ceros en la grilla de cargas ────────────────────────────────────
    def test_una_carga_no_intentada_viene_en_cero_y_no_es_una_medicion(self):
        """678 de 682 sesiones de FUERZA se perdían por esto.

        La planilla escribe 0 donde el jugador no intentó esa carga. Tomado
        como medición no pasa el piso de 0,1 m/s y se llevaba la sesión entera.
        """
        filas = [[D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16",
                  "EXTREMO", 47.85, 60.0, 50.0, 1.25, 0.8, 30,
                  1.2, 1.28, 1.19, 1.28,      # 20 kg
                  0, 0, 0, 0]]                # 30 kg no intentada
        rep = self.correr({"FUERZA": (CAB_FUERZA, filas)}, commit=True)
        self.assertEqual(rep.creados, 1)
        self.assertEqual(rep.fuera_de_rango, [], "el 0 no debía contar como error")
        r = ExamResult.objects.get(template__slug="fuerza")
        self.assertEqual(r.result_data["v_20kg"], 1.28)
        self.assertNotIn("v_30kg", r.result_data)

    # ── rango ───────────────────────────────────────────────────────────
    def test_un_valor_imposible_se_descarta_y_la_fila_se_carga(self):
        """`v_60kg=45992` es un número de fecha en una columna de velocidad.

        Se descarta el VALOR, no la sesión: un día de test trae varias pruebas
        y una celda mala no es razón para perder el T10 de ese día. Y como
        `best` es un MÍNIMO en los tests de tiempo, dejar un valor
        imposiblemente bajo lo haría ganar y sería la cifra del gráfico.
        """
        filas = [
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
             "T10 (s)", 1.82, 1.79, None, 1.79, 1.81],
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
             "T30 (s)", 2.68, 4.18, None, 2.68, 3.43],   # 2.68 s en 30 m: imposible
        ]
        rep = self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        self.assertEqual(rep.creados, 1)
        self.assertEqual(len(rep.fuera_de_rango), 1)
        r = ExamResult.objects.get(template__slug="carreras")
        self.assertEqual(r.result_data["t10_best"], 1.79, "el T10 del día se salvó")
        self.assertEqual(r.result_data["t30_best"], 4.18,
                         "el 2.68 no debía ganar el mínimo")

    # ── procedencia e idempotencia ──────────────────────────────────────
    def test_escribe_la_procedencia_en_cada_fila(self):
        filas = [[D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
                  "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]]
        self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        d = ExamResult.objects.get(template__slug="carreras").result_data
        self.assertEqual(d["origen"], ing.ORIGEN)
        self.assertEqual(d["origen_hoja"], "CARRERAS")
        self.assertIn("2026-03-11", d["origen_id"])

    def test_correrlo_dos_veces_no_duplica(self):
        hojas = {"CARRERAS": (CAB_LARGO, [
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
             "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]])}
        self.correr(hojas, commit=True)
        rep = self.correr(hojas, commit=True)
        self.assertEqual(rep.creados, 0)
        self.assertEqual(rep.ya_existian, 1)
        self.assertEqual(ExamResult.objects.count(), 1)

    def test_sin_commit_no_escribe(self):
        rep = self.correr({"CARRERAS": (CAB_LARGO, [
            [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
             "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]])})
        self.assertEqual(rep.creados, 1)
        self.assertEqual(ExamResult.objects.count(), 0)

    # ── fechas y emparejamiento ─────────────────────────────────────────
    def test_las_filas_sin_fecha_se_reportan_en_vez_de_desaparecer(self):
        filas = [[None, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "",
                  "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]]
        rep = self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        self.assertEqual(rep.creados, 0)
        self.assertEqual(rep.sin_fecha.get("CARRERAS"), 1)

    def test_empareja_por_fecha_de_nacimiento_con_el_nombre_incompleto(self):
        filas = [[D, "DAMIAN SOLIS", datetime(2010, 5, 4), 15, "U16", "",
                  "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]]
        rep = self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        self.assertEqual(rep.creados, 1)

    def test_dos_personas_con_la_misma_fecha_no_se_confunden(self):
        # Cuatro jugadores del club comparten 2012-01-04 por una celda
        # arrastrada; sólo la fecha los fusionaría.
        Player.objects.create(category=self.cat, first_name="Otro",
                              last_name="Distinto", date_of_birth=date(2010, 5, 4))
        filas = [[D, "NADIE PARECIDO", datetime(2010, 5, 4), 15, "U16", "",
                  "T10 (s)", 1.82, 1.79, None, 1.79, 1.81]]
        rep = self.correr({"CARRERAS": (CAB_LARGO, filas)}, commit=True)
        self.assertEqual(rep.creados, 0)
        self.assertEqual(len(rep.sin_jugador), 1)

    def test_el_ejercicio_distingue_sentadilla_de_press(self):
        # Las dos hojas caen en la misma plantilla el mismo día, así que sin el
        # ejercicio en la clave una taparía a la otra.
        f = [D, "DAMIAN SOLIS ROJAS", datetime(2010, 5, 4), 15, "U16", "EXTREMO",
             47.85, 60.0, 50.0, 1.25, 0.8, 30, 1.2, 1.28, 1.19, 1.28, 0, 0, 0, 0]
        rep = self.correr({"FUERZA": (CAB_FUERZA, [f]),
                           "PRESS DE BANCO": (CAB_FUERZA, [f])}, commit=True)
        self.assertEqual(rep.creados, 2)
        ejercicios = {r.result_data["ejercicio"]
                      for r in ExamResult.objects.filter(template__slug="fuerza")}
        self.assertEqual(ejercicios, {"Sentadilla", "Press de banco"})


def _hoja_temporal(hojas, nombre):
    """The raw cell grid of one sheet — what the parsers now take.

    They used to receive an openpyxl worksheet and call `iter_rows`; since the
    Google Sheets source landed they take a list of rows, so both origins look
    the same to them (see `exams.formativo_sources`).
    """
    from exams.formativo_sources import FuenteXlsx

    with TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "x.xlsx"
        escribir(ruta, hojas)
        fuente = FuenteXlsx(str(ruta))
        grid = fuente.filas(nombre)
        fuente.cerrar()
    return grid
