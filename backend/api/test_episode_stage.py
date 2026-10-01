"""Changing an injury's stage must change it — or say why it can't."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.utils import timezone
from ninja.errors import HttpError

from api.schemas import StageAdvanceIn
from core.models import Category, Club, Department, Player
from exams.models import Episode, ExamResult, ExamTemplate


class EpisodeStageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        club = Club.objects.create(name="FC")
        Department.objects.create(club=club, name="Médico", slug="medico")
        call_command("seed_lesiones", "--club", "FC", "--create-if-missing", stdout=StringIO())
        cls.t = ExamTemplate.objects.get(slug="lesiones")
        cat = Category.objects.create(club=club, name="Primer Equipo")
        cls.p = Player.objects.create(category=cat, first_name="Andrés", last_name="Bolaño")
        cls.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")

    def setUp(self):
        self.hoy = timezone.localdate()
        self.ep = Episode.objects.create(player=self.p, template=self.t,
                                         started_at=self.aware(self.hoy - timedelta(days=10), 0))
        ExamResult.objects.create(
            player=self.p, template=self.t, episode=self.ep,
            recorded_at=self.ep.started_at,
            result_data={"stage": "aguda", "body_part": "Muslo", "type": "Lesion muscular (desgarro/rotura)",
                         "body_part_detail": "Bíceps femoral"})

    def aware(self, d, h):
        return timezone.make_aware(datetime.combine(d, datetime.min.time().replace(hour=h)))

    def cambiar(self, stage, fecha=None):
        from api.routers import advance_episode_stage

        req = RequestFactory().post("/x")
        req.user = self.su
        return advance_episode_stage(req, str(self.ep.pk),
                                     StageAdvanceIn(stage=stage, effective_date=fecha))

    def estado(self):
        self.ep.refresh_from_db()
        return self.ep.stage, self.ep.status

    def test_dos_cambios_el_mismo_dia_gana_el_ultimo(self):
        """El caso de Hormazábal y Aránguiz: RTP y "Dar de alta" el mismo día."""
        self.cambiar("rtp", self.hoy.isoformat())
        self.cambiar("closed", self.hoy.isoformat())
        self.assertEqual(self.estado(), ("closed", Episode.STATUS_CLOSED))

    def test_un_cambio_de_hoy_gana_a_lo_registrado_mas_temprano_hoy(self):
        """El caso de Bolaño: ya había un registro de hoy a media mañana."""
        ExamResult.objects.create(player=self.p, template=self.t, episode=self.ep,
                                  recorded_at=self.aware(self.hoy, 10),
                                  result_data={"stage": "aguda", "body_part": "Muslo"})
        self.cambiar("intermedia", self.hoy.isoformat())
        self.assertEqual(self.estado()[0], "intermedia")

    def test_una_fecha_futura_se_rechaza_con_motivo(self):
        with self.assertRaises(HttpError) as ctx:
            self.cambiar("rtp", (self.hoy + timedelta(days=3)).isoformat())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("futura", str(ctx.exception))

    def test_una_fecha_anterior_a_la_ultima_se_rechaza_con_motivo(self):
        """El caso de Zaldivia: el alta quedaba detrás de un registro posterior."""
        self.cambiar("rtp", (self.hoy - timedelta(days=2)).isoformat())
        with self.assertRaises(HttpError) as ctx:
            self.cambiar("closed", (self.hoy - timedelta(days=5)).isoformat())
        self.assertIn("anterior a la última actualización", str(ctx.exception))
        self.assertEqual(self.estado()[0], "rtp")

    def test_mismo_dia_que_el_ultimo_registro_pasado(self):
        dia = self.hoy - timedelta(days=4)
        ExamResult.objects.create(player=self.p, template=self.t, episode=self.ep,
                                  recorded_at=self.aware(dia, 12), result_data={"stage": "intermedia"})
        self.cambiar("reintegro", dia.isoformat())
        self.assertEqual(self.estado()[0], "reintegro")

    def test_la_definicion_se_arrastra_desde_los_datos(self):
        self.cambiar("intermedia")
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.title, "Bíceps femoral — Muslo")
        ultimo = ExamResult.objects.filter(episode=self.ep).order_by("-created_at").first()
        self.assertEqual(ultimo.result_data["body_part_detail"], "Bíceps femoral")

    def test_dar_de_alta_hoy_cierra_y_marca_disponible(self):
        self.cambiar("closed", self.hoy.isoformat())
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, Episode.STATUS_CLOSED)
        self.assertEqual(timezone.localtime(self.ep.available_at).date(), self.hoy)
