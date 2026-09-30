"""Daily meeting notes mirrored into the área's "Notas diarias"."""
from __future__ import annotations

from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.models import Category, Club, DailyNote, Department, Player
from exams.models import ExamResult


class DailyNoteSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.medico = Department.objects.create(club=cls.club, name="Médico", slug="medico")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        cat = Category.objects.create(club=cls.club, name="Primer Equipo")
        cat.departments.add(cls.medico, cls.fisico)
        call_command("seed_daily_notes", "--club", "FC", "--create-if-missing",
                     "--all-applicable-categories", stdout=StringIO())
        cls.player = Player.objects.create(category=cat, first_name="A", last_name="B")
        cls.user = get_user_model().objects.create_user(
            "doc", password="x", first_name="Ana", last_name="Molina")

    def nota(self, **kw):
        base = dict(player=self.player, department=self.medico, kind=DailyNote.KIND_PAUTA,
                    date=date(2026, 9, 29), text="Control de rodilla", created_by=self.user)
        base.update(kw)
        return DailyNote.objects.create(**base)

    def espejos(self):
        return ExamResult.objects.filter(result_data__origen="daily")

    def test_una_nota_con_area_queda_en_sus_notas_diarias(self):
        n = self.nota()
        (r,) = self.espejos()
        self.assertEqual(r.template.slug, "notas_diarias_medico")
        self.assertEqual(r.result_data["nota"], "Control de rodilla")
        self.assertEqual(r.result_data["fecha"], "2026-09-29")
        self.assertEqual(r.result_data["autor"], "Ana Molina")
        self.assertEqual(r.result_data["daily_note_id"], str(n.pk))
        self.assertEqual(r.recorded_at.date(), date(2026, 9, 29))

    def test_editar_la_nota_actualiza_el_espejo_sin_duplicar(self):
        n = self.nota()
        n.text = "Control de rodilla — sin dolor"
        n.save()
        (r,) = self.espejos()
        self.assertEqual(r.result_data["nota"], "Control de rodilla — sin dolor")

    def test_cambiar_de_area_mueve_el_espejo(self):
        n = self.nota()
        n.department = self.fisico
        n.save()
        (r,) = self.espejos()
        self.assertEqual(r.template.slug, "notas_diarias_fisico")

    def test_quitarle_el_area_o_borrarla_quita_el_espejo(self):
        n = self.nota()
        n.department = None
        n.save()
        self.assertFalse(self.espejos().exists())
        n2 = self.nota()
        n2.delete()
        self.assertFalse(self.espejos().exists())

    def test_generales_y_planes_no_se_espejan(self):
        self.nota(department=None)
        self.nota(kind=DailyNote.KIND_PLAN)
        self.assertFalse(self.espejos().exists())

    def test_el_backfill_es_idempotente(self):
        n = self.nota()
        ExamResult.objects.filter(result_data__daily_note_id=str(n.pk)).delete()   # "antes del link"
        out = StringIO()
        call_command("sync_daily_notes_to_exams", "--commit", stdout=out)
        self.assertIn("creada              : 1", out.getvalue())
        out = StringIO()
        call_command("sync_daily_notes_to_exams", "--commit", stdout=out)
        self.assertIn("igual               : 1", out.getvalue())
        self.assertEqual(self.espejos().count(), 1)
