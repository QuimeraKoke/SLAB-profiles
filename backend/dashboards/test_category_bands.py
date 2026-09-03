"""The band a chart DRAWS has to be the one the category is judged by.

`AlertRule.config["ranges"]` made alerts per-category, but every widget kept
serialising the field's shared `reference_ranges`. So after seeding the club's
real thresholds the two sides disagreed: a Sub 11 was alerted at his own number
and shown a Sub 20's band. A dashboard with the wrong band looks right, which
is what makes it worse than no dashboard — hence the test.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from dashboards import category_bands
from dashboards.aggregation import resolve_widget
from dashboards.models import (Aggregation, ChartType, DepartmentLayout,
                               LayoutSection, Widget, WidgetDataSource)
from exams.models import ExamResult, ExamTemplate
from goals.models import AlertRule, AlertRuleKind, AlertSeverity

# The club's real T10 scales: a Sub 13 is "Muy Deficiente" over 1,9 s and a
# Sub 20 over 1,8 s. Same field, same template, different number.
BANDAS_SUB13 = [
    {"label": "Muy Deficiente", "min": 1.9, "color": "#dc2626"},
    {"label": "Elite", "max": 1.58, "color": "#0d9488"},
]
BANDAS_SUB20 = [
    {"label": "Muy Deficiente", "min": 1.8, "color": "#dc2626"},
    {"label": "Elite", "max": 1.53, "color": "#0d9488"},
]
# What the shared field carries — the older category's scale, which is exactly
# the wrong one to show a child.
BANDAS_CAMPO = [
    {"label": "Muy Deficiente", "min": 1.8, "color": "#dc2626"},
]


class CategoryBandsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.dept = Department.objects.create(club=cls.club, name="Físico",
                                             slug="fisico")
        cls.sub13 = Category.objects.create(club=cls.club, name="Serie 2013",
                                            cohort_year=2013)
        cls.sub20 = Category.objects.create(club=cls.club, name="SUB-20")
        cls.sin_regla = Category.objects.create(club=cls.club, name="Serie 2018",
                                                cohort_year=2018)
        cls.template = ExamTemplate.objects.create(
            department=cls.dept, name="Carreras", slug="carreras",
            config_schema={"fields": [{
                "key": "t10_best", "label": "T10", "type": "number",
                "unit": "s", "chart_type": "line",
                "reference_ranges": BANDAS_CAMPO,
            }]})
        cls.template.applicable_categories.set(
            [cls.sub13, cls.sub20, cls.sin_regla])
        for cat, bandas in ((cls.sub13, BANDAS_SUB13), (cls.sub20, BANDAS_SUB20)):
            AlertRule.objects.create(
                template=cls.template, field_key="t10_best", category=cat,
                kind=AlertRuleKind.BAND, severity=AlertSeverity.WARNING,
                scope={}, config={"ranges": bandas,
                                  "trigger_labels": ["Muy Deficiente"]})

        cls.jugadores = {}
        for cat in (cls.sub13, cls.sub20, cls.sin_regla):
            p = Player.objects.create(category=cat, first_name="J",
                                      last_name=cat.name.replace(" ", ""))
            cls.jugadores[cat.name] = p
            ExamResult.objects.create(
                template=cls.template, player=p,
                recorded_at=timezone.now() - timedelta(days=1),
                result_data={"t10_best": 1.85})

        layout = DepartmentLayout.objects.create(
            department=cls.dept, category=cls.sub13, name="Físico")
        section = LayoutSection.objects.create(layout=layout, title="Velocidad")
        # `comparison_table` es uno de los cinco tipos que SÍ emiten las
        # bandas al frontend. `multi_line` no las manda —el resolvedor calcula
        # el meta y no lo serializa— así que un test sobre él no probaría nada.
        cls.widget = Widget.objects.create(
            section=section, chart_type=ChartType.COMPARISON_TABLE.value,
            title="T10", column_span=1)
        WidgetDataSource.objects.create(
            widget=cls.widget, template=cls.template,
            aggregation=Aggregation.ALL.value, field_keys=["t10_best"])
        cls.selector = Widget.objects.create(
            section=section, chart_type=ChartType.LINE_WITH_SELECTOR.value,
            title="T10 línea", column_span=1)
        WidgetDataSource.objects.create(
            widget=cls.selector, template=cls.template,
            aggregation=Aggregation.ALL.value, field_keys=["t10_best"])

    def _bandas_dibujadas(self, categoria: str, widget=None) -> list[dict]:
        payload = resolve_widget(widget or self.widget,
                                 self.jugadores[categoria].id)
        filas = payload.get("rows") or payload.get("available_fields") or []
        for f in filas:
            if isinstance(f, dict) and f.get("key", "").endswith("t10_best"):
                return f.get("reference_ranges") or []
        return []

    # ── el invariante ───────────────────────────────────────────────────
    def test_el_grafico_dibuja_la_banda_de_la_categoria_del_jugador(self):
        self.assertEqual(self._bandas_dibujadas("Serie 2013")[0]["min"], 1.9)
        self.assertEqual(self._bandas_dibujadas("SUB-20")[0]["min"], 1.8)

    def test_tambien_en_el_grafico_de_linea_con_selector(self):
        # Los cinco tipos que emiten bandas pasan por el mismo `_field_meta`,
        # así que alcanza con verificar dos para cubrir la vía.
        self.assertEqual(
            self._bandas_dibujadas("Serie 2013", self.selector)[0]["min"], 1.9)
        self.assertEqual(
            self._bandas_dibujadas("SUB-20", self.selector)[0]["min"], 1.8)

    def test_sin_regla_propia_cae_a_las_del_campo(self):
        # Ninguna regla existente cambia de comportamiento.
        bandas = self._bandas_dibujadas("Serie 2018")
        self.assertEqual(bandas, BANDAS_CAMPO)

    # ── el resolvedor, aislado ──────────────────────────────────────────
    def test_build_junta_las_reglas_de_una_categoria(self):
        mapa = category_bands.build(self.sub13.id)
        clave = (self.template.family_id or self.template.id, "t10_best")
        self.assertEqual(mapa[clave], BANDAS_SUB13)

    def test_una_regla_sin_ranges_no_entra(self):
        # `ranges: []` es un descuido, no "sin bandas": cae al campo.
        AlertRule.objects.create(
            template=self.template, field_key="otro", category=self.sub13,
            kind=AlertRuleKind.BAND, severity=AlertSeverity.WARNING, scope={},
            config={"ranges": []})
        mapa = category_bands.build(self.sub13.id)
        self.assertNotIn((self.template.family_id or self.template.id, "otro"),
                         mapa)

    def test_una_regla_inactiva_no_dibuja(self):
        AlertRule.objects.filter(category=self.sub13).update(is_active=False)
        self.assertEqual(self._bandas_dibujadas("Serie 2013"), BANDAS_CAMPO)

    def test_sin_scope_no_cambia_nada(self):
        # Un caller que no entra al context manager ve lo de siempre.
        self.assertEqual(
            category_bands.for_field(self.template, "t10_best", BANDAS_CAMPO),
            BANDAS_CAMPO)

    def test_el_scope_se_limpia_al_salir(self):
        with category_bands.scope(self.sub13.id):
            self.assertEqual(
                category_bands.for_field(self.template, "t10_best",
                                         BANDAS_CAMPO)[0]["min"], 1.9)
        self.assertEqual(
            category_bands.for_field(self.template, "t10_best", BANDAS_CAMPO),
            BANDAS_CAMPO, "el ContextVar quedó sucio")

    def test_las_reglas_se_indexan_por_familia_de_plantilla(self):
        """Una regla apunta a UNA versión y el widget puede leer otra.

        Indexar por `id` haría que un bump de versión huerfanara las reglas y
        el gráfico volviera a la banda compartida sin que nada avise.
        """
        mapa = category_bands.build(self.sub13.id)
        clave, = [k for k in mapa if k[1] == "t10_best"]
        self.assertEqual(clave[0], self.template.family_id or self.template.id)
