"""Suplementación: the regimen template and multiple-choice values downstream."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from api.export import _humanize
from core.models import Category, Club, Department
from exams.models import ExamTemplate


class SuplementacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.nut = Department.objects.create(club=cls.club, name="Nutricional", slug="nutricional")
        cls.cat = Category.objects.create(club=cls.club, name="Primer Equipo")
        cls.cat.departments.add(cls.nut)

    def seed(self):
        call_command("seed_suplementacion", "--club", "FC", "--commit", stdout=StringIO())
        return ExamTemplate.objects.get(slug="suplementacion")

    def test_plantilla_con_la_lista_del_club_y_seleccion_multiple(self):
        t = self.seed()
        campo = next(f for f in t.config_schema["fields"] if f["key"] == "suplementos")
        self.assertTrue(campo["multiple"])
        self.assertEqual((len(campo["options"]), campo["options"][-1]), (24, "Otro"))
        self.assertTrue(t.input_config["modifiers"]["prefill_from_last"])
        self.assertIn(self.cat, t.applicable_categories.all())

    def test_resembrar_conserva_lo_que_agrego_el_club(self):
        t = self.seed()
        campo = next(f for f in t.config_schema["fields"] if f["key"] == "suplementos")
        campo["options"] = campo["options"][:-1] + ["Zinc", "Otro"]
        t.save()
        t = self.seed()
        opciones = next(f for f in t.config_schema["fields"] if f["key"] == "suplementos")["options"]
        self.assertIn("Zinc", opciones)
        self.assertEqual(opciones[-1], "Otro")
        self.assertEqual(ExamTemplate.objects.filter(slug="suplementacion").count(), 1)

    def test_el_excel_escribe_la_lista_en_una_celda(self):
        campo = {"type": "categorical", "multiple": True}
        self.assertEqual(_humanize(["Creatina", "Omega 3"], campo), "Creatina, Omega 3")
