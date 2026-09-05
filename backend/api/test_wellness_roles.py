"""The wellness resolver: which form a category fills, and how it scores.

Every failure this guards against is silent and looks like a real number.

* Pinning the surfaces to the `checkin_fisico` slug made the Formativo's
  65.000 check-ins invisible: the Daily and the Centro de mando queried a
  template that youth categories don't fill, found nothing, and reported
  "0/68 respondieron" — indistinguishable from a squad that didn't answer.
* Averaging the Formativo's items raw scores a wrecked player at 90. Three of
  its five items are inverted (fatiga, estrés, daño muscular) where all five of
  Primer Equipo's point the same way, and the result still looks like a
  wellness score.
* Inverting as `1 − v/max` caps a perfect answer at 88 instead of 100, because
  the best value on a 1–5 scale is 1 and `1 − 1/5` is 0.8.
* A dimension that is not also a score item used to render nothing: its max was
  never collected, `dimension_pct` returned None and the chip simply wasn't
  there.
"""
from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from api import wellness as w
from api.command_center import build_command_center
from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ExamTemplate


def _escala(key, mn, mx):
    return {"key": key, "label": key, "type": "number", "min": mn, "max": mx}


class WellnessRoleResolverTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="U")
        self.dept = Department.objects.create(club=self.club, name="Físico", slug="fisico")
        self.senior = Category.objects.create(club=self.club, name="Primer Equipo")
        self.youth = Category.objects.create(club=self.club, name="Serie 2013")
        for c in (self.senior, self.youth):
            c.departments.add(self.dept)

        # Primer Equipo's legacy form: no `wellness` block at all. It has to
        # keep working unchanged — that is the whole point of the fallback.
        self.legacy = ExamTemplate.objects.create(
            name="Check-in físico", slug="checkin_fisico", department=self.dept,
            config_schema={"fields": [
                _escala("recuperacion", 1, 10), _escala("cuerpo", 1, 5),
                _escala("energia", 1, 5), _escala("animo", 1, 5),
                _escala("sueno", 1, 5),
            ]},
        )
        self.legacy.applicable_categories.add(self.senior)

        self.checkin = ExamTemplate.objects.create(
            name="Check-IN formativo", slug="checkin_formativo", department=self.dept,
            config_schema={
                "fields": [
                    _escala("calidad_sueno", 1, 5), _escala("nivel_fatiga", 1, 5),
                    _escala("nivel_estres", 1, 5), _escala("estado_animo", 1, 5),
                    _escala("dano_muscular", 1, 5),
                ],
                "wellness": {
                    "role": "checkin",
                    "items": [["calidad_sueno", "Sueño"], ["nivel_fatiga", "Fatiga"],
                              ["nivel_estres", "Estrés"], ["estado_animo", "Ánimo"],
                              ["dano_muscular", "Daño muscular"]],
                    "inverted": ["nivel_fatiga", "nivel_estres", "dano_muscular"],
                    "dimensions": [["calidad_sueno", "Sueño"]],
                },
            },
        )
        self.checkin.applicable_categories.add(self.youth)

        self.checkout = ExamTemplate.objects.create(
            name="Check-OUT formativo", slug="checkout_formativo", department=self.dept,
            config_schema={
                "fields": [_escala("rpe", 0, 10), _escala("dano_muscular", 1, 5)],
                "wellness": {
                    "role": "checkout",
                    "items": [["rpe", "RPE"], ["dano_muscular", "Daño muscular"]],
                    "inverted": ["rpe", "dano_muscular"],
                    "dimensions": [["rpe", "RPE"], ["dano_muscular", "Daño muscular"]],
                },
            },
        )
        self.checkout.applicable_categories.add(self.youth)

    # ── which template is the form ─────────────────────────────────────

    def test_una_categoria_sin_declaracion_cae_al_checkin_historico(self):
        self.assertEqual([t.slug for t in w.templates_for(self.senior)],
                         ["checkin_fisico"])

    def test_la_categoria_que_declara_gana_al_slug_historico(self):
        self.assertEqual([t.slug for t in w.templates_for(self.youth)],
                         ["checkin_formativo"])

    def test_el_checkout_solo_existe_donde_se_declara(self):
        self.assertEqual([t.slug for t in w.templates_for(self.youth, role="checkout")],
                         ["checkout_formativo"])
        # Sin declaración NO hay fallback: el Primer Equipo no llena check-out,
        # y devolver el check-in acá lo mostraría como si lo llenara.
        self.assertEqual(w.templates_for(self.senior, role="checkout"), [])

    def test_roles_for(self):
        self.assertEqual(w.roles_for(self.senior), ["checkin"])
        self.assertEqual(w.roles_for(self.youth), ["checkin", "checkout"])

    # ── el puntaje ─────────────────────────────────────────────────────

    def test_el_checkin_perfecto_del_formativo_da_100(self):
        """El caso que el `1 − v/max` tapaba: llegaba a 88, no a 100."""
        perfecto = {"calidad_sueno": 5, "estado_animo": 5,
                    "nivel_fatiga": 1, "nivel_estres": 1, "dano_muscular": 1}
        self.assertEqual(w.score_for(self.youth, perfecto), 100)

    def test_el_peor_checkin_del_formativo_toca_el_piso_de_la_escala(self):
        """20, no 0.

        La fracción es `v ÷ max`, no un reescalado min–max, así que el peor
        valor posible de una escala 1–5 vale 1/5. Es la misma propiedad que
        hace que el peor check-in del Primer Equipo dé 18 en vez de 0; tocarla
        movería todos los números históricos de los dos planteles.
        """
        pesimo = {"calidad_sueno": 1, "estado_animo": 1,
                  "nivel_fatiga": 5, "nivel_estres": 5, "dano_muscular": 5}
        self.assertEqual(w.score_for(self.youth, pesimo), 20)

    def test_ignorar_los_invertidos_da_el_puntaje_al_reves(self):
        """La razón de que exista `score_for`: acertar los items y errar los
        invertidos produce un número que apunta exactamente al revés."""
        destruido = {"calidad_sueno": 1, "estado_animo": 1,
                     "nivel_fatiga": 5, "nivel_estres": 5, "dano_muscular": 5}
        crudo = w.score(destruido, w.field_max(self.youth),
                        w.items_for(self.youth))          # sin `inverted`
        self.assertEqual(crudo, 68, "el jugador destruido puntúa 'bueno'")
        self.assertEqual(w.score_for(self.youth, destruido), 20)

    def test_el_primer_equipo_no_cambia(self):
        # Escalas mixtas: recuperación 1–10 contra cuatro de 1–5.
        pleno = {"recuperacion": 10, "cuerpo": 5, "energia": 5, "animo": 5, "sueno": 5}
        self.assertEqual(w.score_for(self.senior, pleno), 100)
        self.assertEqual(w.score_for(self.senior, {"recuperacion": 1, "cuerpo": 1,
                                                   "energia": 1, "animo": 1, "sueno": 1}), 18)

    def test_un_item_ausente_no_hunde_el_puntaje(self):
        # Promedia lo respondido; un campo vacío no cuenta como cero.
        self.assertEqual(w.score_for(self.youth, {"calidad_sueno": 5, "estado_animo": 5}), 100)

    def test_sin_ninguna_respuesta_devuelve_None(self):
        self.assertIsNone(w.score_for(self.youth, {}))

    def test_el_checkout_puntua_invertido(self):
        # Sesión suave y sin molestias → alto; dura y dolorida → bajo.
        self.assertEqual(w.score_for(self.youth, {"rpe": 0, "dano_muscular": 1},
                                     role="checkout"), 100)
        # 10 y no 0: el RPE va de 0 a 10 (llega al piso real) y el daño
        # muscular de 1 a 5, cuyo peor valor vale 1/5.
        self.assertEqual(w.score_for(self.youth, {"rpe": 10, "dano_muscular": 5},
                                     role="checkout"), 10)

    # ── dimensiones ────────────────────────────────────────────────────

    def test_una_dimension_que_no_es_item_del_puntaje_igual_tiene_escala(self):
        """La regresión silenciosa: sin su max, `dimension_pct` da None y el
        chip no aparece — sin error que lo delate."""
        self.checkin.config_schema["wellness"]["dimensions"] = [["estado_animo", "Ánimo"]]
        self.checkin.config_schema["wellness"]["items"] = [["calidad_sueno", "Sueño"]]
        self.checkin.save()
        self.assertIn("estado_animo", w.field_max(self.youth))
        self.assertEqual(
            w.dimension_pct_for(self.youth, {"estado_animo": 5}, "estado_animo"), 100)

    def test_la_dimension_invertida_se_espeja(self):
        self.assertEqual(
            w.dimension_pct_for(self.youth, {"nivel_fatiga": 1}, "nivel_fatiga"), 100)
        self.assertEqual(
            w.dimension_pct_for(self.youth, {"nivel_fatiga": 5}, "nivel_fatiga"), 20)


class CommandCenterCheckoutTests(TestCase):
    """El payload sólo trae el check-out donde la categoría lo llena."""

    def setUp(self):
        base = WellnessRoleResolverTests()
        base.setUp()
        self.__dict__.update(base.__dict__)
        self.jugador = Player.objects.create(
            category=self.youth, first_name="A", last_name="B", is_active=True)
        Player.objects.create(category=self.senior, first_name="C", last_name="D",
                              is_active=True)

    def test_una_categoria_sin_checkout_no_trae_la_llave(self):
        cc = build_command_center(self.senior)
        self.assertEqual(cc["wellness_roles"], ["checkin"])
        self.assertNotIn("checkout", cc)
        # Y tampoco la fila de calidad de datos: "Sin plantilla" se leería como
        # una falta de configuración y no como un formulario que no existe.
        self.assertNotIn("Check-OUT", [r["source"] for r in cc["data_quality"]])

    def test_la_categoria_con_checkout_lo_trae_puntuado(self):
        ExamResult.objects.create(
            player=self.jugador, template=self.checkout,
            recorded_at=timezone.now(), result_data={"rpe": 0, "dano_muscular": 1},
        )
        cc = build_command_center(self.youth)
        self.assertEqual(cc["wellness_roles"], ["checkin", "checkout"])
        self.assertEqual(cc["checkout"]["wellness"]["value"], 100)
        self.assertEqual(cc["checkout"]["adherence"]["responded"], 1)
        self.assertIn("Check-OUT", [r["source"] for r in cc["data_quality"]])

    def test_el_checkin_del_formativo_ya_no_mira_el_slug_del_primer_equipo(self):
        """La regresión de origen: `checkin_formativo` contaba como 0 respuestas."""
        ExamResult.objects.create(
            player=self.jugador, template=self.checkin, recorded_at=timezone.now(),
            result_data={"calidad_sueno": 5, "estado_animo": 5, "nivel_fatiga": 1,
                         "nivel_estres": 1, "dano_muscular": 1},
        )
        cc = build_command_center(self.youth)
        self.assertEqual(cc["kpis"]["wellness"]["value"], 100)
        self.assertEqual(cc["kpis"]["wellness"]["responses"], 1)
        self.assertEqual(cc["checkin_adherence"]["responded"], 1)
