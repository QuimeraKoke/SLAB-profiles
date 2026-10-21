"""Guards for `exams.kine_notes_ingest` — the formativo physios' log → Kinesiología notes."""
from __future__ import annotations

from datetime import date

from django.test import TestCase

from core.models import Category, Club, Department, Player
from exams import kine_notes_ingest as ing
from exams.management.commands.seed_daily_notes import con_campos_kine
from exams.models import ExamResult, ExamTemplate

CAB = ["Jugador", "Rut", "Fecha", "Tratante", "Categoria", "Tipo de intervencion", "Observaciones"]
ENE = 46034          # 2026-01-12 as the sheet stores it (Excel serial)


def grid(*filas):
    return [["", "", "", "", "", "", ""], CAB, *[list(f) for f in filas]]


def fila(nombre="ADIEL MUÑOZ LOAIZA", rut="23315547-0", fecha=ENE, tratante="L. Caputto",
         cat="Sub 16", tipo="Tratamiento", obs="Realiza calentamiento y primera parte con el grupo."):
    return [nombre, rut, fecha, tratante, cat, tipo, obs]


class KineNotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.kine = Department.objects.create(club=cls.club, name="Kinesiológico",
                                             slug="kinesiologico")
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2010", cohort_year=2010)
        cls.pe = Category.objects.create(club=cls.club, name="Primer Equipo", is_senior=True)
        cls.adiel = Player.objects.create(category=cls.cat, first_name="Adiel", last_name="Muñoz",
                                          second_last_name="Loaiza", national_id="23.315.547-0",
                                          date_of_birth=date(2010, 3, 1))
        cls.sin_dob = Player.objects.create(category=cls.cat, first_name="Gonzalo",
                                            last_name="Ahumada")
        cls.t = ExamTemplate.objects.create(department=cls.kine, name="Notas diarias",
                                            slug=ing.SLUG, config_schema=con_campos_kine({}))

    def correr(self, *filas, commit=True):
        return ing.run(grid(*filas), self.club, commit=commit)

    def notas(self):
        return ExamResult.objects.filter(template=self.t)

    def test_crea_la_nota_con_los_selectores(self):
        rep = self.correr(fila())
        self.assertEqual((rep.creadas, rep.via["rut"]), (1, 1))
        d = self.notas().get().result_data
        self.assertEqual((d["fecha"], d["tratante"], d["tipo_intervencion"]),
                         ("2026-01-12", "L. Caputto", "Tratamiento"))
        self.assertEqual(d["nota"], "Realiza calentamiento y primera parte con el grupo.")

    def test_el_asunto_es_el_comienzo_de_la_nota(self):
        larga = "Fortalecimiento de miembros superiores, circuito de core y trabajo de " \
                "movilidad de cadera con progresión a carrera"
        self.correr(fila(obs=larga))
        asunto = self.notas().get().result_data["asunto"]
        self.assertTrue(asunto.endswith("…") and len(asunto) <= ing.ASUNTO_MAX + 1)
        self.assertTrue(larga.startswith(asunto[:-1]))

    def test_por_nombre_si_el_rut_no_esta(self):
        rep = self.correr(fila(rut="#N/A (Did not find value)"))
        self.assertEqual((rep.creadas, rep.via["nombre"]), (1, 1))

    def test_un_homonimo_sin_fecha_de_nacimiento_no_calza(self):
        rep = self.correr(fila(nombre="GONZALO AHUMADA", rut="", cat="Sub 13"))
        self.assertEqual((rep.creadas, len(rep.sin_jugador)), (0, 1))

    def test_un_nombre_de_otra_edad_no_calza(self):
        rep = self.correr(fila(rut="", cat="Sub 21"))     # Adiel tiene 15
        self.assertEqual(len(rep.sin_jugador), 1)

    def test_fechas_imposibles_se_omiten_y_las_raras_se_reportan(self):
        filas = [fila(fecha=ENE + d, obs=f"sesión {d}") for d in range(25)]
        rep = self.correr(*filas, fila(fecha=-619888, obs="año 202"),
                          fila(fecha=45687, obs="2025-01-30"))
        self.assertEqual([f.obs for f in rep.fecha_invalida], ["año 202"])
        self.assertEqual([f.obs for f in rep.fecha_dudosa], ["2025-01-30"])
        self.assertEqual(rep.creadas, 26, "la de 2025 se importa igual")

    def test_es_espejo_crea_cambia_y_borra(self):
        self.correr(fila(obs="uno"), fila(obs="dos"), fila(obs="tres"))
        rep = self.correr(fila(obs="uno"), fila(obs="dos corregido"), fila(obs="tres"))
        self.assertEqual((rep.creadas, rep.borradas, rep.sin_cambio), (1, 1, 2))
        self.assertEqual(sorted(self.notas().values_list("result_data__nota", flat=True)),
                         ["dos corregido", "tres", "uno"])
        rep = self.correr(fila(obs="uno"), fila(obs="dos corregido"), fila(obs="tres"))
        self.assertEqual((rep.creadas, rep.borradas, rep.actualizadas), (0, 0, 0))

    def test_no_borra_media_historia_por_una_lectura_incompleta(self):
        self.correr(*[fila(obs=f"n{i}") for i in range(10)])
        rep = self.correr(fila(obs="n0"))
        self.assertTrue(rep.borrado_bloqueado)
        self.assertEqual(self.notas().count(), 10)

    def test_no_toca_las_notas_escritas_en_slab(self):
        ExamResult.objects.create(player=self.adiel, template=self.t,
                                  recorded_at="2026-01-10T12:00:00Z",
                                  result_data={"fecha": "2026-01-10", "nota": "a mano"})
        self.correr(fila())
        self.correr(fila(obs="otra"))
        self.assertTrue(self.notas().filter(result_data__nota="a mano").exists())

    def test_dos_filas_identicas_son_dos_notas(self):
        self.assertEqual(self.correr(fila(), fila()).creadas, 2)

    def test_un_tratante_nuevo_se_agrega_como_opcion(self):
        rep = self.correr(fila(tratante="J. Pérez", tipo="Podologia"))
        self.assertEqual(rep.opciones_nuevas, {"tratante": ["J. Pérez"]})
        self.t.refresh_from_db()
        campos = {f["key"]: f.get("options") for f in self.t.config_schema["fields"]}
        self.assertIn("J. Pérez", campos["tratante"])
        self.assertEqual(self.notas().get().result_data["tipo_intervencion"], "Podología",
                         "sin tilde en la planilla, una sola opción")

    def test_agrega_la_pestana_solo_en_juveniles(self):
        self.correr(fila())
        self.assertTrue(self.cat.departments.filter(pk=self.kine.pk).exists())
        self.assertTrue(self.t.applicable_categories.filter(pk=self.cat.pk).exists())
        self.assertFalse(self.pe.departments.filter(pk=self.kine.pk).exists())

    def test_sin_commit_no_escribe(self):
        rep = self.correr(fila(), commit=False)
        self.assertEqual((rep.creadas, self.notas().count()), (1, 0))

    def test_resembrar_conserva_las_opciones_agregadas(self):
        schema = con_campos_kine(self.t.config_schema, extra={"tratante": ["J. Pérez"]})
        de_nuevo = con_campos_kine(schema)
        tratante = next(f for f in de_nuevo["fields"] if f["key"] == "tratante")
        self.assertIn("J. Pérez", tratante["options"])
        self.assertIn("M. Vera", tratante["options"])
