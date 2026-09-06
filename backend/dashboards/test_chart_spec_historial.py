"""El gráfico de un jugador que cambió de categoría.

`_normalize_spec` resolvía la plantilla estrictamente por
`applicable_categories`, así que un jugador ascendido del formativo llegaba a
Primer Equipo con los gráficos arrancando de cero. En el plantel real son 11 de
35, y para ellos el historial juvenil ES la mayor parte de lo que SLAB sabe:
Cristóbal Ulloa tenía 689 lecturas y ni un gráfico.

Lo que este archivo fija es la SEPARACIÓN de dos preguntas que
`applicable_categories` mezclaba:

* "¿esta categoría puede CARGAR este examen?" — sigue siendo suya, y sigue
  cerrada (`/players/{id}/templates`, el selector del registrador);
* "¿se puede LEER el historial propio del jugador?" — la respuesta es sí, y por
  eso la lectura cae al club cuando la categoría no aplica.
"""
from __future__ import annotations

from django.test import TestCase

from core.models import Category, Club, Department
from dashboards.chart_spec import _SpecError, _normalize_spec
from exams.models import ExamTemplate

TIPOS = {"line", "comparison_table"}


def _spec(slug: str) -> dict:
    return {
        "chart_type": "line",
        "title": "Sueño",
        "sources": [{"template_slug": slug, "field_keys": ["calidad_sueno"]}],
    }


class ResolucionDePlantillaTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="U")
        self.dept = Department.objects.create(club=self.club, name="Físico",
                                              slug="fisico")
        self.formativo = Category.objects.create(club=self.club,
                                                 name="Serie 2008")
        self.senior = Category.objects.create(club=self.club,
                                              name="Primer Equipo")
        self.tpl = ExamTemplate.objects.create(
            name="Check-IN formativo", slug="checkin_formativo",
            department=self.dept, is_active_version=True,
            config_schema={"fields": [
                {"key": "calidad_sueno", "type": "number", "label": "Sueño",
                 "min": 1, "max": 5},
            ]},
        )
        self.tpl.applicable_categories.add(self.formativo)

    def test_la_categoria_que_aplica_resuelve(self):
        _, _, _, fuentes = _normalize_spec(self.formativo,
                                           _spec("checkin_formativo"), TIPOS)
        self.assertEqual(fuentes[0]["template"], self.tpl)

    def test_la_categoria_que_no_aplica_igual_resuelve_dentro_del_club(self):
        """El caso del ascendido: Primer Equipo no llena el formulario del
        formativo, pero sus jugadores promovidos tienen ese historial."""
        _, _, _, fuentes = _normalize_spec(self.senior,
                                           _spec("checkin_formativo"), TIPOS)
        self.assertEqual(fuentes[0]["template"], self.tpl)

    def test_la_aplicable_le_gana_a_la_del_club(self):
        """Si la categoría tiene su propia versión, esa manda.

        Importa cuando dos plantillas comparten slug entre departamentos o
        versiones: el fallback es un ÚLTIMO recurso, no un empate.
        """
        otra = ExamTemplate.objects.create(
            name="Check-IN formativo v2", slug="checkin_formativo",
            department=self.dept, is_active_version=False, version=2,
            config_schema={"fields": [
                {"key": "calidad_sueno", "type": "number", "label": "Sueño",
                 "min": 1, "max": 5},
            ]},
        )
        otra.applicable_categories.add(self.senior)
        _, _, _, fuentes = _normalize_spec(self.senior,
                                           _spec("checkin_formativo"), TIPOS)
        self.assertEqual(fuentes[0]["template"], otra)

    def test_no_cruza_de_club(self):
        """El fallback llega hasta el club y ni un paso más.

        Misma regla que el resolvedor de wellness: leer la plantilla de otro
        club no da un error, da un número — y eso es peor.
        """
        otro_club = Club.objects.create(name="Otro club")
        otro_dept = Department.objects.create(club=otro_club, name="Físico",
                                              slug="fisico")
        ExamTemplate.objects.create(
            name="Ajeno", slug="solo_del_otro_club", department=otro_dept,
            is_active_version=True,
            config_schema={"fields": [
                {"key": "calidad_sueno", "type": "number", "label": "S",
                 "min": 1, "max": 5},
            ]},
        )
        with self.assertRaises(_SpecError) as ctx:
            _normalize_spec(self.senior, _spec("solo_del_otro_club"), TIPOS)
        self.assertIn("club", str(ctx.exception))

    def test_una_plantilla_inexistente_sigue_fallando(self):
        with self.assertRaises(_SpecError):
            _normalize_spec(self.senior, _spec("no_existe"), TIPOS)

    def test_prefiere_la_version_activa(self):
        vieja = ExamTemplate.objects.create(
            name="Check-IN formativo v0", slug="checkin_formativo",
            department=self.dept, is_active_version=False, version=0,
            config_schema={"fields": [
                {"key": "calidad_sueno", "type": "number", "label": "S",
                 "min": 1, "max": 5},
            ]},
        )
        _, _, _, fuentes = _normalize_spec(self.senior,
                                          _spec("checkin_formativo"), TIPOS)
        self.assertEqual(fuentes[0]["template"], self.tpl)
        self.assertNotEqual(fuentes[0]["template"], vieja)
