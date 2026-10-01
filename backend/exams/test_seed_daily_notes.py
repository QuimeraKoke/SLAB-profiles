"""`seed_daily_notes`: one "Notas diarias" per department, found by slug."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ExamTemplate


class SeedDailyNotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cls.podo = Department.objects.create(club=cls.club, name="Podología", slug="podologia")
        cls.pe = Category.objects.create(club=cls.club, name="Primer Equipo")
        cls.pe.departments.add(cls.fisico, cls.podo)
        cls.s15 = Category.objects.create(club=cls.club, name="Serie 2015")
        cls.s15.departments.add(cls.fisico)
        cls.otra = Category.objects.create(club=cls.club, name="Femenino")   # sin pestaña Físico

    def correr(self):
        call_command("seed_daily_notes", "--club", "FC", "--create-if-missing",
                     "--all-applicable-categories", stdout=StringIO())

    def test_renombra_la_vieja_sin_cambiar_slug_ni_perder_historia(self):
        vieja = ExamTemplate.objects.create(
            name="Notas diarias Físico", slug="notas_diarias_fisico",
            department=self.fisico, config_schema={}, is_locked=True)
        vieja.applicable_categories.add(self.pe, self.otra)
        p = Player.objects.create(category=self.pe, first_name="A", last_name="B")
        ExamResult.objects.create(player=p, template=vieja, recorded_at=timezone.now(),
                                  result_data={"fecha": "2026-09-30", "nota": "x"})

        self.correr()

        t = ExamTemplate.objects.get(department=self.fisico)
        self.assertEqual(t.pk, vieja.pk, "renombrada en su lugar, no duplicada")
        self.assertEqual((t.name, t.slug), ("Notas diarias", "notas_diarias_fisico"))
        self.assertEqual(ExamResult.objects.filter(template=t).count(), 1)
        self.assertTrue(t.is_locked, "sin --unlock no se destraba")
        # Suma la Serie 2015 (tiene la pestaña) y NO suelta a Femenino.
        self.assertEqual(set(t.applicable_categories.all()), {self.pe, self.s15, self.otra})

    def test_crea_la_que_falta_con_slug_propio(self):
        self.correr()
        podo = ExamTemplate.objects.get(department=self.podo)
        fis = ExamTemplate.objects.get(department=self.fisico)
        self.assertEqual((podo.name, podo.slug), ("Notas diarias", "notas_diarias_podologia"))
        self.assertEqual(fis.slug, "notas_diarias_fisico",
                         "mismo nombre en dos departamentos, slugs distintos")
        self.assertEqual(set(podo.applicable_categories.all()), {self.pe})

    def test_correrlo_dos_veces_no_duplica(self):
        self.correr()
        self.correr()
        self.assertEqual(ExamTemplate.objects.filter(name="Notas diarias").count(), 2)

    def test_todas_llevan_documentos_y_la_historia_no_cambia(self):
        vieja = ExamTemplate.objects.create(
            name="Notas diarias Físico", slug="notas_diarias_fisico",
            department=self.fisico, config_schema={}, is_locked=True)
        p = Player.objects.create(category=self.pe, first_name="A", last_name="B")
        r = ExamResult.objects.create(player=p, template=vieja, recorded_at=timezone.now(),
                                      result_data={"fecha": "2026-09-30", "nota": "x"})
        self.correr()
        for t in ExamTemplate.objects.filter(name="Notas diarias"):
            campo = next(f for f in t.config_schema["fields"] if f["key"] == "documentos")
            self.assertEqual(campo["type"], "file")
            self.assertFalse(campo.get("required"), "opcional: las notas sin adjunto siguen válidas")
            self.assertTrue(t.template_fields.filter(key="documentos").exists())
        r.refresh_from_db()
        self.assertEqual(r.result_data, {"fecha": "2026-09-30", "nota": "x"})
