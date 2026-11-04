"""The PF's anthropometry table per category, and the rule that a category's own
bands replace the club-wide ones (one reading, one verdict)."""
from __future__ import annotations

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.bands import band_for_value
from exams.models import ExamResult, ExamTemplate
from goals.management.commands.seed_antropometria_bands import TABLE, build_ranges
from goals.models import Alert, AlertRule, AlertRuleKind, AlertSeverity


def label(field, group, value):
    direction, labels, by_group = TABLE[field]
    return band_for_value(value, build_ranges(direction, labels, by_group[group]))["label"]


class TablaTests(SimpleTestCase):
    def test_pliegues_sub13_como_la_tabla(self):
        self.assertEqual(label("suma_pliegues", "Sub 13", 44), "Elite/Excelente")
        self.assertEqual(label("suma_pliegues", "Sub 13", 45), "Profesional/Bueno", "< 45 es estricto")
        self.assertEqual(label("suma_pliegues", "Sub 13", 58), "Aceptable")
        self.assertEqual(label("suma_pliegues", "Sub 13", 61), "Elevado")

    def test_masa_muscular_sube_es_mejor(self):
        self.assertEqual(label("masa_muscular_pct", "Sub 18-Proy", 53), "Elite/Excelente")
        self.assertEqual(label("masa_muscular_pct", "Sub 18-Proy", 52), "Profesional/Bueno", "> 52 es estricto")
        self.assertEqual(label("masa_muscular_pct", "Sub 18-Proy", 46), "Bajo")

    def test_imo_sin_huecos(self):
        # La tabla deja 4,2–4,3 sin banda en Sub 18-Proy: cae en Profesional.
        self.assertEqual(label("imo", "Sub 18-Proy", 4.25), "Profesional/Bueno")
        self.assertEqual(label("imo", "Sub 15-16", 3.7), "Aceptable")
        self.assertEqual(label("imo", "Sub 14", 3.1), "Bajo")


class PrecedenciaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        club = Club.objects.create(name="FC")
        dept = Department.objects.create(club=club, name="Nutrición", slug="nutricion")
        cls.sub13 = Category.objects.create(club=club, name="Serie 2013", cohort_year=2013)
        cls.adultos = Category.objects.create(club=club, name="Primer Equipo")
        cls.t = ExamTemplate.objects.create(department=dept, name="Penta", slug="pentacompartimental",
                                            config_schema={"fields": [{
                                                "key": "suma_pliegues", "label": "Σ 6 pliegues", "type": "number",
                                                "reference_ranges": [{"label": "Élite", "max": 30}, {"label": "Elevado", "min": 30}]}]})
        cls.t.applicable_categories.set([cls.sub13, cls.adultos])
        cls.t.rebuild_template_fields()
        AlertRule.objects.create(template=cls.t, field_key="suma_pliegues", kind=AlertRuleKind.BAND,
                                 severity=AlertSeverity.CRITICAL, scope={}, config={"trigger_labels": ["Elevado"]})
        direction, labels, by_group = TABLE["suma_pliegues"]
        AlertRule.objects.create(template=cls.t, field_key="suma_pliegues", category=cls.sub13,
                                 kind=AlertRuleKind.BAND, severity=AlertSeverity.CRITICAL, scope={},
                                 config={"ranges": build_ranges(direction, labels, by_group["Sub 13"]),
                                         "trigger_labels": ["Elevado"]})
        cls.chico = Player.objects.create(category=cls.sub13, first_name="Chico", last_name="Trece")
        cls.adulto = Player.objects.create(category=cls.adultos, first_name="Adulto", last_name="Uno")

    def save(self, player, v):
        ExamResult.objects.create(template=self.t, player=player, recorded_at=timezone.now(),
                                  result_data={"suma_pliegues": v})

    def test_la_banda_de_la_categoria_reemplaza_a_la_global(self):
        self.save(self.chico, 50)        # Elevado en la escala adulta, Bueno en Sub 13
        self.assertFalse(Alert.objects.filter(player=self.chico).exists())

    def test_la_categoria_alerta_con_su_umbral(self):
        self.save(self.chico, 65)
        self.assertEqual(Alert.objects.filter(player=self.chico).count(), 1, "una lectura, una alerta")

    def test_sin_bandas_propias_sigue_la_global(self):
        self.save(self.adulto, 50)
        self.assertTrue(Alert.objects.filter(player=self.adulto).exists())
