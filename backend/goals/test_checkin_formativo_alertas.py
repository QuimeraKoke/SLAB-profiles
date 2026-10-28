"""Check-IN formativo: alerts on 1 and 2 («Crítico»), not on 3 («Aviso»).

The club's call (2026-10-28): a 3 is an ordinary day, and an alert for every 3
buried the 1s and 2s on the Centro de mando. The check-OUT keeps both.
"""
from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.management.commands.seed_wellness_formativo import BANDAS_1_5, Command
from exams.models import ExamResult, ExamTemplate
from goals.evaluator import evaluate_threshold_rules_for_result
from goals.models import AlertRule


class CheckinFormativoAlertasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        club = Club.objects.create(name="U")
        dept = Department.objects.create(club=club, name="Físico", slug="fisico")
        cls.cat = Category.objects.create(club=club, name="Serie 2010", cohort_year=2010)
        cls.player = Player.objects.create(category=cls.cat, first_name="A", last_name="B")
        campos = [{"key": k, "label": k, "type": "number", "min": 1, "max": 5,
                   "reference_ranges": BANDAS_1_5}
                  for k in ("nivel_fatiga", "calidad_sueno", "nivel_estres", "estado_animo",
                            "dano_muscular", "partido_recuperacion", "partido_explosivas",
                            "partido_fisico")]
        cls.checkin = ExamTemplate.objects.create(
            department=dept, name="Check-IN", slug="checkin_formativo",
            config_schema={"fields": campos})
        cls.checkout = ExamTemplate.objects.create(
            department=dept, name="Check-OUT", slug="checkout_formativo",
            config_schema={"fields": campos})
        for t in (cls.checkin, cls.checkout):
            t.applicable_categories.set([cls.cat])
        cmd = Command()
        cmd.stdout = open("/dev/null", "w")
        cmd._alertas()

    def responder(self, template, key, valor):
        r = ExamResult.objects.create(template=template, player=self.player,
                                      recorded_at=timezone.now(), result_data={key: valor})
        return evaluate_threshold_rules_for_result(r)

    def test_el_seed_crea_solo_critico_en_el_checkin(self):
        sev = set(AlertRule.objects.filter(template=self.checkin)
                  .values_list("severity", flat=True))
        self.assertEqual(sev, {"critical"})
        self.assertEqual(set(AlertRule.objects.filter(template=self.checkout)
                             .values_list("severity", flat=True)), {"critical", "warning"})

    def test_un_3_no_alerta_y_un_2_o_1_si(self):
        self.assertEqual(self.responder(self.checkin, "nivel_fatiga", 3), [])
        for valor in (2, 1):
            alertas = self.responder(self.checkin, "nivel_fatiga", valor)
            self.assertEqual([a.severity for a in alertas], ["critical"], valor)

    def test_el_checkout_sigue_avisando_en_3(self):
        alertas = self.responder(self.checkout, "partido_fisico", 3)
        self.assertEqual([a.severity for a in alertas], ["warning"])
