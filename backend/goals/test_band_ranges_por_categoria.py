"""Umbrales de banda por categoría: la regla puede traer los suyos.

`AlertRule` ya era por categoría, pero `_band_evaluation` leía los umbrales del
CAMPO compartido — así que una regla para Sub 11 y otra para Sub 20 evaluaban con
los mismos números. El club mide el mismo test con bandas distintas por edad: en
su propia planilla, "Muy Deficiente" en RM Back Squat es <68,3 kg para Sub 13 y
<125 kg para Sub 18.

El test que sostiene todo el cambio es
`test_el_mismo_valor_cae_en_bandas_distintas_por_categoria`: sin él, dos reglas
con umbrales distintos producirían la misma alerta y nadie lo notaría, porque una
alerta con el umbral equivocado se ve igual que una correcta.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ExamTemplate
from goals.models import Alert, AlertRule, AlertRuleKind, AlertSeverity

# Las bandas reales del club, de las hojas FORMATO CONDICIONAL.
BANDAS_SUB13 = [
    {"label": "Muy Deficiente", "max": 68.3, "color": "#dc2626", "alert": True},
    {"label": "Deficiente", "min": 68.3, "max": 86.0, "color": "#f59e0b"},
    {"label": "Regular", "min": 86.0, "max": 100.4, "color": "#16a34a"},
    {"label": "Bueno", "min": 100.4, "color": "#16a34a"},
]
BANDAS_SUB18 = [
    {"label": "Muy Deficiente", "max": 125.0, "color": "#dc2626", "alert": True},
    {"label": "Deficiente", "min": 125.0, "max": 140.0, "color": "#f59e0b"},
    {"label": "Regular", "min": 140.0, "max": 161.0, "color": "#16a34a"},
    {"label": "Bueno", "min": 161.0, "color": "#16a34a"},
]


class BandasPorCategoriaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.dept = Department.objects.create(
            club=cls.club, name="Físico", slug="fisico")
        cls.sub13 = Category.objects.create(club=cls.club, name="Serie 2013",
                                            cohort_year=2013)
        cls.sub18 = Category.objects.create(club=cls.club, name="Serie 2008",
                                            cohort_year=2008)
        cls.template = ExamTemplate.objects.create(
            department=cls.dept, name="Fuerza", slug="fuerza",
            config_schema={"fields": [{
                "key": "rm_back_squat", "label": "RM Back Squat",
                "type": "number", "unit": "kg",
                # Las del CAMPO son las de la categoría mayor: es el default
                # que hoy se aplicaría a todos.
                "reference_ranges": BANDAS_SUB18,
            }]},
        )
        cls.template.applicable_categories.set([cls.sub13, cls.sub18])
        cls.template.rebuild_template_fields()
        cls.chico = Player.objects.create(
            category=cls.sub13, first_name="Chico", last_name="Trece")
        cls.grande = Player.objects.create(
            category=cls.sub18, first_name="Grande", last_name="Ocho")

    def _rule(self, category, ranges=None):
        cfg = {"trigger_labels": ["Muy Deficiente"]}
        if ranges is not None:
            cfg["ranges"] = ranges
        return AlertRule.objects.create(
            template=self.template, field_key="rm_back_squat",
            category=category, kind=AlertRuleKind.BAND, config=cfg,
            severity=AlertSeverity.WARNING, scope={},
        )

    def _save(self, player, valor):
        return ExamResult.objects.create(
            template=self.template, player=player,
            recorded_at=timezone.now(), result_data={"rm_back_squat": valor},
        )

    # ── el corazón del cambio ───────────────────────────────────────────
    def test_el_mismo_valor_cae_en_bandas_distintas_por_categoria(self):
        """90 kg es "Regular" para un Sub 13 y "Muy Deficiente" para un Sub 18.

        Es el caso que motivó todo: con las bandas en el campo, los dos leían
        los umbrales del mayor y al chico se le exigía el doble.
        """
        self._rule(self.sub13, ranges=BANDAS_SUB13)
        self._rule(self.sub18)                       # usa las del campo

        self._save(self.chico, 90.0)
        self._save(self.grande, 90.0)

        self.assertFalse(
            Alert.objects.filter(player=self.chico).exists(),
            "90 kg es Regular para un Sub 13: no debía alertar",
        )
        self.assertTrue(
            Alert.objects.filter(player=self.grande).exists(),
            "90 kg es Muy Deficiente para un Sub 18: debía alertar",
        )

    def test_el_umbral_del_chico_tambien_dispara_cuando_corresponde(self):
        # El guard del test anterior sería igual de feliz si la regla del chico
        # nunca disparara. Acá se comprueba que sí lo hace, bajo SU umbral.
        self._rule(self.sub13, ranges=BANDAS_SUB13)
        self._save(self.chico, 60.0)                 # < 68,3 → Muy Deficiente
        self.assertTrue(Alert.objects.filter(player=self.chico).exists())

    # ── compatibilidad ──────────────────────────────────────────────────
    def test_sin_ranges_se_usan_las_del_campo(self):
        # Toda regla existente cae por acá: el cambio no puede alterarlas.
        self._rule(self.sub18)
        self._save(self.grande, 100.0)               # < 125 en las del campo
        self.assertTrue(Alert.objects.filter(player=self.grande).exists())

    def test_una_lista_vacia_no_deja_la_regla_sin_umbrales(self):
        # `ranges: []` es un descuido, no "sin bandas". Cae al campo en vez de
        # dejar la regla muda para siempre.
        r = self._rule(self.sub18)
        r.config = {**r.config, "ranges": []}
        r.save(update_fields=["config"])
        self._save(self.grande, 100.0)
        self.assertTrue(Alert.objects.filter(player=self.grande).exists())

    # ── validación ──────────────────────────────────────────────────────
    def test_las_bandas_de_la_regla_se_validan_igual_que_las_del_campo(self):
        """Mismo validador, a propósito.

        Si divergieran, una banda válida en un lado sería inválida en el otro y
        nadie sabría cuál manda.
        """
        r = AlertRule(
            template=self.template, field_key="rm_back_squat",
            category=self.sub13, kind=AlertRuleKind.BAND, scope={},
            config={"ranges": [{"label": "Sin límites"}]},   # ni min ni max
        )
        with self.assertRaises(ValidationError):
            r.clean()

    def test_una_banda_sin_label_se_rechaza(self):
        r = AlertRule(
            template=self.template, field_key="rm_back_squat",
            category=self.sub13, kind=AlertRuleKind.BAND, scope={},
            config={"ranges": [{"min": 10, "max": 20}]},
        )
        with self.assertRaises(ValidationError):
            r.clean()

    def test_con_ranges_propias_el_campo_puede_no_tener_bandas(self):
        """El chequeo previo dejaba de aplicar.

        Antes `clean()` exigía que el campo tuviera `reference_ranges`, porque
        sin ellas la regla nunca dispararía. Con umbrales propios eso ya no es
        cierto, y seguir exigiéndolo bloquearía justamente el caso nuevo.
        """
        sin_bandas = ExamTemplate.objects.create(
            department=self.dept, name="Fuerza 2", slug="fuerza_2",
            config_schema={"fields": [{
                "key": "rm", "label": "RM", "type": "number", "unit": "kg",
            }]},
        )
        sin_bandas.applicable_categories.set([self.sub13])
        r = AlertRule(
            template=sin_bandas, field_key="rm", category=self.sub13,
            kind=AlertRuleKind.BAND, scope={},
            config={"ranges": BANDAS_SUB13},
        )
        r.clean()      # no debe lanzar

    def test_sin_ranges_y_sin_bandas_en_el_campo_sigue_siendo_error(self):
        # El chequeo original se conserva donde todavía tiene sentido.
        sin_bandas = ExamTemplate.objects.create(
            department=self.dept, name="Fuerza 3", slug="fuerza_3",
            config_schema={"fields": [{
                "key": "rm", "label": "RM", "type": "number", "unit": "kg",
            }]},
        )
        sin_bandas.applicable_categories.set([self.sub13])
        r = AlertRule(
            template=sin_bandas, field_key="rm", category=self.sub13,
            kind=AlertRuleKind.BAND, scope={}, config={},
        )
        with self.assertRaises(ValidationError):
            r.clean()
