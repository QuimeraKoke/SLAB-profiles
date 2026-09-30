"""`exams.peso_diario_ingest` — the first team's daily weigh-in sheet."""
from __future__ import annotations

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Category, Club, Department, Player
from exams import peso_diario_ingest as ing
from exams.models import ExamResult

# 46294 = 2026-09-29, 46295 = 2026-09-30 (serial days since 1899-12-30).
CAB = [" ", "Apellido", "Categoría", "Estatura", "sumatoria de pliegues anterior",
       "sumatoria de pliegues Anterior", "sumatoria de pliegues actual", "Peso IDEAL",
       46294, 46295]


def grid(*filas):
    return [["", "", ""], CAB, *filas]            # a blank first row, like the club's


class PesoDiarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        nutri = Department.objects.create(club=cls.club, name="Nutricional", slug="nutricional")
        cls.pe = Category.objects.create(club=cls.club, name="Primer Equipo")
        cls.pe.departments.add(nutri)
        call_command("seed_peso_talla", "--club", "FC", "--create-if-missing", stdout=StringIO())
        cls.charles = Player.objects.create(category=cls.pe, first_name="Charles",
                                            last_name="Aranguiz", second_last_name="Sandoval")

    def correr(self, *filas, commit=True):
        filas_p, dias = ing.parse(grid(*filas))
        return ing.run(self.club, filas_p, dias, commit=commit)

    def test_una_celda_numerica_es_un_pesaje_con_su_ideal_y_su_imc(self):
        rep = self.correr(["Charles ", "Aránguiz", "Plantel", 172.2, 30, 29, 29, 69, 69.4, 69.0])
        self.assertEqual(rep.creados, 2)
        r = ExamResult.objects.get(player=self.charles, recorded_at__date=date(2026, 9, 30))
        d = r.result_data
        self.assertEqual((d["peso"], d["altura"], d["peso_ideal"]), (69.0, 172.2, 69))
        self.assertEqual(d["dif_ideal"], 0.0)
        self.assertEqual(d["imc"], 23.27)
        self.charles.refresh_from_db()
        self.assertEqual(float(self.charles.current_weight_kg), 69.0, "la ficha toma el último")

    def test_los_estados_no_son_pesos_y_se_cuentan(self):
        rep = self.correr(["Charles", "Aránguiz", "Plantel", 172.2, "", "", "", 69, "selección", "sub20"])
        self.assertEqual(rep.creados, 0)
        self.assertEqual(rep.estados, {"Selección": 1, "Sub 20": 1})

    def test_una_correccion_actualiza_y_no_duplica(self):
        self.correr(["Charles", "Aránguiz", "Plantel", 172.2, "", "", "", 69, 69.4, 69.0])
        rep = self.correr(["Charles", "Aránguiz", "Plantel", 172.2, "", "", "", 69, 69.4, 68.6])
        self.assertEqual((rep.creados, rep.actualizados, rep.iguales), (0, 1, 1))
        r = ExamResult.objects.get(player=self.charles, recorded_at__date=date(2026, 9, 30))
        self.assertEqual(r.result_data["peso"], 68.6)
        self.assertEqual(ExamResult.objects.filter(player=self.charles).count(), 2)

    def test_un_valor_imposible_no_entra(self):
        rep = self.correr(["Charles", "Aránguiz", "Plantel", 172.2, "", "", "", 69, 6.94, 69.0])
        self.assertEqual(rep.creados, 1)
        self.assertEqual(len(rep.fuera_de_rango), 1)

    def test_un_nombre_sin_jugador_se_reporta(self):
        rep = self.correr(["John", "Cortes", "Plantel-Sub 20", "", "", "", "", "", 70, 70.2])
        self.assertEqual(rep.creados, 0)
        self.assertEqual(len(rep.sin_jugador), 1)

    def test_sin_commit_no_escribe(self):
        self.correr(["Charles", "Aránguiz", "Plantel", 172.2, "", "", "", 69, 69.4, 69.0], commit=False)
        self.assertFalse(ExamResult.objects.exists())
