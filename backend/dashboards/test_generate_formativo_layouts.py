"""Guards for `generate_formativo_layouts`.

The layout is derived from the data, which is what keeps it honest — but also
what makes it silently wrong if the derivation slips. Two failure modes worth a
test: a category getting charts for a test it never runs (empty panels that look
like missing data), and a chart type that does not carry the per-category bands
we just seeded (a trend drawn against the shared scale, which looks right).
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from dashboards.models import (ChartType, DepartmentLayout, TeamReportLayout)
from exams.models import ExamResult, ExamTemplate

# The five chart types that actually serialise reference bands to the frontend.
# `multi_line` computes the field meta and never emits it, so a trend drawn
# with it loses the thresholds.
CON_BANDAS = {
    ChartType.COMPARISON_TABLE.value, ChartType.LINE_WITH_SELECTOR.value,
    ChartType.GROUPED_BAR.value, ChartType.TEAM_ROSTER_MATRIX.value,
    ChartType.TEAM_DISTRIBUTION.value, ChartType.TEAM_TREND_LINE.value,
}


def campo(key, label, group, *, chart=True):
    f = {"key": key, "label": label, "type": "number", "unit": "s",
         "group": group}
    if chart:
        f["chart_type"] = "line"
    return f


class GenerarLayoutsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.fisico = Department.objects.create(club=cls.club, name="Físico",
                                               slug="fisico")
        cls.nutri = Department.objects.create(club=cls.club, name="Nutricional",
                                              slug="nutricional")
        cls.grande = Category.objects.create(club=cls.club, name="Serie 2008",
                                             cohort_year=2008)
        cls.chica = Category.objects.create(club=cls.club, name="Serie 2018",
                                            cohort_year=2018)
        cls.vacia = Category.objects.create(club=cls.club, name="Serie 2017",
                                            cohort_year=2017)

        cls.carreras = ExamTemplate.objects.create(
            department=cls.fisico, name="Carreras", slug="carreras",
            config_schema={"fields": [
                campo("t10_1", "T10 intento 1", "Velocidad", chart=False),
                campo("t10_best", "T10 mejor", "Velocidad"),
                campo("cod_der_best", "COD der", "Cambio de dirección"),
                {"key": "sesion", "label": "Sesión", "type": "text"},
                {"key": "origen", "label": "Origen", "type": "text"},
            ]})
        cls.fuerza = ExamTemplate.objects.create(
            department=cls.fisico, name="Fuerza", slug="fuerza",
            config_schema={"fields": [campo("rm", "1RM", "Resumen")]})
        # Sólo la grande corre Fuerza — es el anidamiento real del club.
        cls.carreras.applicable_categories.set([cls.grande, cls.chica, cls.vacia])
        cls.fuerza.applicable_categories.set([cls.grande])
        # Nutricional: plantilla que NO aplica al formativo, con datos igual.
        cls.penta = ExamTemplate.objects.create(
            department=cls.nutri, name="Penta", slug="pentacompartimental",
            config_schema={"fields": [campo("imc", "IMC", "Resumen")]})

        ahora = timezone.now()
        for cat in (cls.grande, cls.chica):
            p = Player.objects.create(category=cat, first_name="J",
                                      last_name=cat.name.replace(" ", ""))
            for i in range(4):
                ExamResult.objects.create(
                    template=cls.carreras, player=p,
                    recorded_at=ahora - timedelta(days=i + 1),
                    result_data={"t10_1": 1.9, "t10_best": 1.8 + i / 100,
                                 "cod_der_best": 2.5, "sesion": "x",
                                 "origen": "planilla"})
        grande_p = Player.objects.get(category=cls.grande)
        for i in range(4):
            ExamResult.objects.create(
                template=cls.fuerza, player=grande_p,
                recorded_at=ahora - timedelta(days=i + 1),
                result_data={"rm": 100 + i})
        # Penta con datos, plantilla no aplicable: el caso huérfano.
        ExamResult.objects.create(
            template=cls.penta, player=grande_p, recorded_at=ahora,
            result_data={"imc": 22.0})

    def correr(self, *args) -> str:
        salida = StringIO()
        call_command("generate_formativo_layouts", "--club", self.club.name,
                     *args, stdout=salida)
        return salida.getvalue()

    def _widgets(self, categoria, slug="fisico"):
        layout = DepartmentLayout.objects.get(category=categoria,
                                              department__slug=slug)
        return [w for s in layout.sections.all() for w in s.widgets.all()]

    # ── derivado del dato ───────────────────────────────────────────────
    def test_una_categoria_sin_datos_no_recibe_layout(self):
        # Un layout vacío se lee como "faltan datos" cuando el problema es que
        # esa categoría no corre el test.
        self.correr("--commit")
        self.assertFalse(
            DepartmentLayout.objects.filter(category=self.vacia).exists())

    def test_la_categoria_chica_recibe_menos_secciones_que_la_grande(self):
        """El anidamiento real: Fuerza empieza en Sub 13.

        Generar el set completo en todas daría a las más chicas paneles vacíos.
        """
        self.correr("--commit")
        grande = DepartmentLayout.objects.get(category=self.grande,
                                              department=self.fisico)
        chica = DepartmentLayout.objects.get(category=self.chica,
                                             department=self.fisico)
        self.assertEqual(
            {s.title for s in grande.sections.all()}, {"Carreras", "Fuerza"})
        self.assertEqual({s.title for s in chica.sections.all()}, {"Carreras"})

    def test_no_grafica_los_campos_de_procedencia_ni_las_etiquetas(self):
        self.correr("--commit")
        claves = {k for w in self._widgets(self.grande)
                  for src in w.data_sources.all() for k in src.field_keys}
        self.assertNotIn("origen", claves)
        self.assertNotIn("sesion", claves)

    def test_un_campo_con_pocas_lecturas_no_gana_widget(self):
        # Un punto solo no es una tendencia.
        p = Player.objects.get(category=self.chica)
        ExamResult.objects.create(
            template=self.carreras, player=p, recorded_at=timezone.now(),
            result_data={"campo_raro": 1.0})
        self.correr("--commit")
        claves = {k for w in self._widgets(self.chica)
                  for src in w.data_sources.all() for k in src.field_keys}
        self.assertNotIn("campo_raro", claves)

    # ── que la banda llegue ─────────────────────────────────────────────
    def test_todos_los_widgets_usan_tipos_que_emiten_bandas(self):
        """Si no, los umbrales por categoría no llegan al gráfico.

        `multi_line` calcula el meta del campo y no lo serializa, así que una
        tendencia dibujada con él pierde en silencio la escala de la categoría.
        """
        self.correr("--commit")
        for cat in (self.grande, self.chica):
            for w in self._widgets(cat):
                self.assertIn(w.chart_type, CON_BANDAS, f"{cat.name}/{w.title}")

    def test_la_tabla_de_ultimas_tomas_no_lleva_los_intentos_crudos(self):
        # Los tres intentos no tienen banda ni se miran de a uno: metidos en la
        # tabla la vuelven ilegible.
        self.correr("--commit")
        layout = DepartmentLayout.objects.get(category=self.grande,
                                              department=self.fisico)
        seccion = layout.sections.get(title="Carreras")
        tabla = seccion.widgets.get(chart_type=ChartType.COMPARISON_TABLE.value)
        claves = {k for src in tabla.data_sources.all() for k in src.field_keys}
        self.assertIn("t10_best", claves)
        self.assertNotIn("t10_1", claves)

    # ── datos huérfanos ─────────────────────────────────────────────────
    def test_los_datos_en_plantillas_no_aplicables_se_reportan_como_tales(self):
        """"Sin datos" y "hay datos que no puedo graficar" son cosas distintas.

        `pentacompartimental` aplica sólo a Primer Equipo y tiene 1165
        resultados de jugadores del formativo. Reportarlo como ausencia
        esconde el hueco de configuración.
        """
        salida = self.correr("--commit")
        self.assertIn("no aplica", salida)
        self.assertIn("nutricional", salida)
        self.assertFalse(
            DepartmentLayout.objects.filter(category=self.grande,
                                            department=self.nutri).exists())

    # ── la pestaña de la ficha ──────────────────────────────────────────
    def test_vincula_el_departamento_a_la_categoria(self):
        """Sin esto el layout existe y es inalcanzable.

        La ficha del jugador arma sus pestañas con `Category.departments`
        (perfil/[id]/page.tsx:130), no con los layouts. Ninguna categoría
        formativa lo tenía poblado, así que los 20 dashboards generados no
        aparecían en ninguna ficha.
        """
        self.assertFalse(self.grande.departments.exists())
        self.correr("--commit")
        self.assertIn("fisico",
                      self.grande.departments.values_list("slug", flat=True))

    def test_no_vincula_un_departamento_sin_layout(self):
        # Una pestaña vinculada sin layout renderiza un panel vacío, que se lee
        # como "faltan datos".
        self.correr("--commit")
        self.assertNotIn("nutricional",
                         self.grande.departments.values_list("slug", flat=True))
        self.assertFalse(self.vacia.departments.exists())

    def test_no_saca_un_departamento_que_ya_estaba(self):
        # El club puede haber vinculado uno a mano; sólo se agrega.
        self.grande.departments.add(self.nutri)
        self.correr("--commit")
        self.assertIn("nutricional",
                      self.grande.departments.values_list("slug", flat=True))

    # ── equipo ──────────────────────────────────────────────────────────
    def test_genera_tambien_los_layouts_de_equipo(self):
        self.correr("--commit")
        layout = TeamReportLayout.objects.get(category=self.grande,
                                              department=self.fisico)
        self.assertEqual(layout.scope, "period")
        tipos = {w.chart_type for s in layout.sections.all()
                 for w in s.widgets.all()}
        self.assertIn(ChartType.TEAM_ROSTER_MATRIX.value, tipos)

    def test_el_histograma_de_equipo_apunta_a_un_solo_campo(self):
        # Necesita una métrica; más de una serían varios widgets diciendo lo
        # mismo.
        self.correr("--commit")
        layout = TeamReportLayout.objects.get(category=self.grande,
                                              department=self.fisico)
        hist = [w for s in layout.sections.all() for w in s.widgets.all()
                if w.chart_type == ChartType.TEAM_DISTRIBUTION.value]
        self.assertTrue(hist)
        for w in hist:
            self.assertIn("field_key", w.display_config)
            self.assertEqual(
                len(list(w.data_sources.first().field_keys)), 1)

    # ── idempotencia ────────────────────────────────────────────────────
    def test_correrlo_dos_veces_reconstruye_y_no_duplica(self):
        self.correr("--commit")
        antes = len(self._widgets(self.grande))
        salida = self.correr("--commit")
        self.assertEqual(
            DepartmentLayout.objects.filter(category=self.grande,
                                            department=self.fisico).count(), 1)
        self.assertEqual(len(self._widgets(self.grande)), antes)
        self.assertIn("reconstruidos", salida)

    def test_skip_existing_conserva_lo_editado_a_mano(self):
        self.correr("--commit")
        layout = DepartmentLayout.objects.get(category=self.grande,
                                              department=self.fisico)
        seccion = layout.sections.first()
        seccion.title = "Editado por el club"
        seccion.save()
        self.correr("--commit", "--skip-existing")
        seccion.refresh_from_db()
        self.assertEqual(seccion.title, "Editado por el club")

    def test_sin_commit_no_escribe(self):
        self.correr()
        self.assertEqual(DepartmentLayout.objects.count(), 0)
        self.assertEqual(TeamReportLayout.objects.count(), 0)

    def test_se_puede_limitar_a_una_categoria(self):
        self.correr("--commit", "--category", "Serie 2018")
        self.assertTrue(DepartmentLayout.objects.filter(category=self.chica).exists())
        self.assertFalse(DepartmentLayout.objects.filter(category=self.grande).exists())
