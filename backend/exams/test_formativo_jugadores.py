"""`exams.formativo_jugadores`: the JUGADORES tab into Player — foot wins,
birth date only fills, photos are copied once per Drive file."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import TestCase

from core.models import Category, Club, Player
from exams import formativo_jugadores as ing

CAB = ["JUGADOR", "FECHA DE NACIMIENTO", "AÑOS Y MESES", "CATEGORÍA", "POSICIÓN", "FOTOS", "PERFIL"]
FOTO = "https://drive.google.com/file/d/1QtPvudZYO-RVYmdSm7KNX99mcSV8_s6v/view?usp=sharing"


class JugadoresTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="U")
        cat = Category.objects.create(club=cls.club, name="Serie 2010", cohort_year=2010)
        cls.ana = Player.objects.create(category=cat, first_name="Ana", last_name="Perez",
                                        date_of_birth=date(2010, 3, 1), preferred_foot="left")
        cls.beto = Player.objects.create(category=cat, first_name="Beto", last_name="Soto")

    def correr(self, filas, **kw):
        import openpyxl

        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "eval.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "JUGADORES"
            ws.append(CAB)
            for f in filas:
                ws.append(f)
            wb.save(ruta)
            with mock.patch.object(ing, "descargar_foto", return_value=b"\xff\xd8jpeg") as dl:
                rep = ing.run(str(ruta), self.club, **kw)
            return rep, dl

    def test_el_pie_de_la_planilla_gana_y_el_nacimiento_solo_completa(self):
        rep, _ = self.correr([
            ["ANA PEREZ", datetime(2010, 3, 1), "", "U16", "", "", "DERECHO"],
            ["BETO SOTO", datetime(2010, 5, 9), "", "U16", "", "", "IZQUIERDO"],
        ], commit=True, fotos=False)
        self.ana.refresh_from_db()
        self.beto.refresh_from_db()
        self.assertEqual((self.ana.preferred_foot, self.beto.preferred_foot), ("right", "left"))
        self.assertEqual(self.beto.date_of_birth, date(2010, 5, 9))
        self.assertEqual((rep.pie_corregido, rep.pie_nuevo, rep.nacimiento), (1, 1, 1))

    def test_la_foto_se_copia_una_vez(self):
        fila = [["ANA PEREZ", datetime(2010, 3, 1), "", "U16", "", FOTO, ""]]
        rep, dl = self.correr(fila, commit=True)
        self.ana.refresh_from_db()
        self.assertEqual((rep.fotos, dl.call_count), (1, 1))
        self.assertTrue(self.ana.photo.name.endswith("1QtPvudZYO-RVYmdSm7KNX99mcSV8_s6v.jpg"))
        self.assertEqual(self.ana.photo_src, self.ana.photo.url, "la copia gana al link externo")
        rep, dl = self.correr(fila, commit=True)
        self.assertEqual((rep.fotos, dl.call_count), (0, 0), "sin cambios, no se vuelve a bajar")
        self.ana.photo.delete(save=False)

    def test_un_link_a_carpeta_no_es_una_foto(self):
        self.assertIsNone(ing.drive_id("https://drive.google.com/drive/folders/1Mvbk08nxOulI"))
