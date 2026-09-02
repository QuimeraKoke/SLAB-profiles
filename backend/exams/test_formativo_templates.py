"""Guards for `seed_formativo_templates`.

Two classes of silent failure here. A formula that is nearly right produces a
number that looks plausible and is wrong — nobody checks 1RM ÷ peso by hand. And
an `applicable_categories` set that is slightly off means a category is offered
a test it never runs, or worse, that ~13.000 GPS rows have no template to land
in and the import reports "0 emparejados" with no explanation.

Every expected value below comes from the club's own workbook cells.
"""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket, Category, Club, Department, Player
from exams.calculations import compute_result_data
from exams.models import ExamTemplate

SEASON = 2026


class FormativoTemplatesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.dept = Department.objects.create(club=cls.club, name="Físico",
                                             slug="fisico")
        cls.brackets = {}
        for order, (code, name, age) in enumerate(BRACKETS):
            cls.brackets[age] = Bracket.objects.create(
                code=code, name=name, age=age, order=order)
        # Series 2008–2018 → Sub 18 down to no rung at all in 2026.
        cls.series = {
            year: Category.objects.create(club=cls.club, name=f"Serie {year}",
                                          cohort_year=year)
            for year in range(2008, 2019)
        }
        # The club's own top squad: several cohorts, no cohort_year of its own.
        cls.sub20 = Category.objects.create(club=cls.club, name="SUB-20")
        cls.sub20.team_seasons.create(season=SEASON, bracket=cls.brackets[20])
        cls.senior = Category.objects.create(club=cls.club, name="Primer Equipo",
                                             is_senior=True)
        cls.femenino = Category.objects.create(club=cls.club, name="PEF - Femenino")
        # The command widens the two GPS exams but never creates them: there
        # are exactly two in the whole system by deliberate decision, and this
        # command is not where a third would come from.
        for slug, nombre in (("gps_sesion", "GPS sesión"),
                             ("gps_partido", "GPS partido")):
            ExamTemplate.objects.create(
                department=cls.dept, name=nombre, slug=slug,
                config_schema={"fields": [{"key": "tot_dist", "label": "DT",
                                           "type": "number", "unit": "m"}]})

    def setUp(self):
        salida = StringIO()
        call_command("seed_formativo_templates", "--club", self.club.name,
                     "--season", str(SEASON), stdout=salida)
        self.salida = salida.getvalue()

    def _t(self, slug) -> ExamTemplate:
        return ExamTemplate.objects.get(department=self.dept, slug=slug)

    def _calc(self, slug, datos):
        player = Player.objects.create(category=self.series[2010],
                                       first_name="X", last_name="Y")
        out, _ = compute_result_data(self._t(slug), datos, player=player)
        return out

    # ── las fórmulas, contra las celdas del club ────────────────────────
    def test_resistencia_reproduce_los_numeros_del_club(self):
        # Fila real: palier 51 → 2040 m, VO2 53.536. Exacto en las 862 filas.
        out = self._calc("resistencia", {"palier": 51})
        self.assertEqual(out["metros"], 2040)
        self.assertAlmostEqual(out["vo2_max"], 53.54, places=2)

    def test_fuerza_reproduce_los_numeros_del_club(self):
        # Raimundo Álvarez, 2024-12-20: PC 78.05, 1RM 145.3135691,
        # última carga 80 → %RM 55.0533584, FR 1.861801013.
        out = self._calc("fuerza", {"peso_corporal": 78.05,
                                    "rm_estimado": 145.3135691,
                                    "ultima_carga_kg": 80})
        self.assertAlmostEqual(out["pct_rm"], 55.05, places=2)
        self.assertAlmostEqual(out["fr"], 1.862, places=3)

    def test_mil_metros_reproduce_la_velocidad_media(self):
        out = self._calc("resistencia_1000m", {"tiempo_s": 221, "metros": 1000})
        self.assertAlmostEqual(out["vam"], 4.525, places=3)

    def test_el_mejor_de_un_tiempo_es_el_menor(self):
        """El caso que se equivoca solo si se copia de otra plantilla.

        En T10 el mejor intento es el más RÁPIDO; en CMJ es el más ALTO. Un
        `max` en el test de velocidad devuelve el peor intento y el gráfico
        sigue viéndose razonable.
        """
        out = self._calc("carreras", {"t10_1": 1.82, "t10_2": 1.79, "t10_3": 1.85})
        self.assertEqual(out["t10_best"], 1.79)
        self.assertAlmostEqual(out["t10_prom"], 1.82, places=2)

    def test_el_mejor_de_un_salto_es_el_mayor(self):
        out = self._calc("neuromuscular", {"cmj_1": 24.1, "cmj_2": 23.9,
                                           "cmj_3": 25.4})
        self.assertEqual(out["cmj_best"], 25.4)
        self.assertAlmostEqual(out["cmj_prom"], 24.47, places=2)

    def test_la_asimetria_de_COD_conserva_el_signo(self):
        """El signo dice qué lado trabajar; un valor absoluto lo esconde.

        Son tiempos, así que el lado más lento es el del número mayor.
        Positivo = derecha más lenta.
        """
        lento_izq = self._calc("carreras", {
            "cod_der_1": 2.28, "cod_der_2": 2.28, "cod_der_3": 2.28,
            "cod_izq_1": 2.41, "cod_izq_2": 2.41, "cod_izq_3": 2.41})
        self.assertLess(lento_izq["cod_asimetria"], 0)
        lento_der = self._calc("carreras", {
            "cod_der_1": 2.41, "cod_der_2": 2.41, "cod_der_3": 2.41,
            "cod_izq_1": 2.28, "cod_izq_2": 2.28, "cod_izq_3": 2.28})
        self.assertGreater(lento_der["cod_asimetria"], 0)

    def test_los_campos_importados_no_son_calculados(self):
        """`vam` del test de palier y `vo2_max` del 1000 m se importan.

        El primero es un lookup de 91 filas que el motor de fórmulas no puede
        hacer; el segundo no es función sólo del tiempo (240 s da 48.3 y 251 s
        da 51.1). Inventarles una fórmula reescribiría los números del club.
        """
        vam = next(f for f in self._t("resistencia").config_schema["fields"]
                   if f["key"] == "vam")
        self.assertEqual(vam["type"], "number")
        vo2 = next(f for f in self._t("resistencia_1000m").config_schema["fields"]
                   if f["key"] == "vo2_max")
        self.assertEqual(vo2["type"], "number")

    # ── a quién se le ofrece cada test ──────────────────────────────────
    def test_carreras_y_neuromuscular_van_a_todo_el_formativo(self):
        # El dato del club tiene filas de U8 a U20 en las dos familias.
        for slug in ("carreras", "neuromuscular"):
            nombres = set(self._t(slug).applicable_categories.values_list(
                "name", flat=True))
            self.assertIn("Serie 2018", nombres, slug)
            self.assertIn("SUB-20", nombres, slug)

    def test_las_series_bajo_Sub_13_no_reciben_fuerza_ni_resistencia(self):
        for slug in ("resistencia", "resistencia_1000m", "fuerza"):
            nombres = set(self._t(slug).applicable_categories.values_list(
                "name", flat=True))
            self.assertIn("Serie 2013", nombres, f"{slug}: Sub 13 sí lo hace")
            self.assertNotIn("Serie 2014", nombres, f"{slug}: Sub 12 no lo hace")
            self.assertNotIn("Serie 2018", nombres, slug)

    def test_el_techo_de_for_age_no_cuela_a_las_series_menores(self):
        """`Bracket.for_age(8)` devuelve Sub 11 porque es un TECHO.

        Sin guard, Serie 2018 pasaba un corte de "Sub 11 y más" y quedaba con
        GPS, que nunca corrió. Tercer lugar de este trabajo donde el techo hay
        que frenarlo a mano.
        """
        nombres = set(self._t("gps_sesion").applicable_categories.values_list(
            "name", flat=True))
        self.assertIn("Serie 2015", nombres, "Sub 11 sí tiene GPS")
        for year in (2016, 2017, 2018):
            self.assertNotIn(f"Serie {year}", nombres,
                             f"Serie {year} no corrió GPS")

    def test_el_GPS_llega_al_formativo_sin_sacar_al_primer_equipo(self):
        # Los ~13.000 registros juveniles de GPS no tenían plantilla donde
        # caer: gps_sesion sólo aplicaba a Primer Equipo.
        gps = self._t("gps_sesion")
        gps.applicable_categories.add(self.senior)
        call_command("seed_formativo_templates", "--club", self.club.name,
                     "--season", str(SEASON), stdout=StringIO())
        nombres = set(gps.applicable_categories.values_list("name", flat=True))
        self.assertIn("SUB-20", nombres)
        self.assertIn("Primer Equipo", nombres, "no debía tocar al senior")

    def test_no_se_le_cuelga_nada_a_senior_ni_femenino(self):
        # Los libros del formativo no cubren ninguna de las dos.
        for slug in ("carreras", "resistencia", "fuerza"):
            nombres = set(self._t(slug).applicable_categories.values_list(
                "name", flat=True))
            self.assertNotIn("Primer Equipo", nombres, slug)
            self.assertNotIn("PEF - Femenino", nombres, slug)

    def test_la_aplicabilidad_no_depende_de_Category_departments(self):
        """El filtro que tenía la primera versión.

        `Category.objects.filter(departments=dept)` resolvía a UNA categoría en
        este club —sólo Primer Equipo las tiene vinculadas— así que las cinco
        plantillas no se le ofrecían a nadie. `applicable_categories` es la
        puerta que lee la API; `Category.departments` responde otra pregunta.
        """
        self.assertFalse(self.series[2010].departments.exists())
        self.assertIn(self.series[2010],
                      self._t("carreras").applicable_categories.all())

    # ── GPS ─────────────────────────────────────────────────────────────
    def test_agrega_los_dos_campos_de_frecuencia_cardiaca(self):
        gps = self._t("gps_sesion")
        claves = {f["key"] for f in gps.config_schema["fields"]}
        self.assertIn("avg_hr_pct", claves)
        self.assertIn("max_hr_bpm", claves)
        self.assertIn("tot_dist", claves, "no debía pisar los campos existentes")

    def test_no_duplica_los_campos_de_pulso_al_recorrer_de_nuevo(self):
        gps = self._t("gps_sesion")
        for _ in range(2):
            call_command("seed_formativo_templates", "--club", self.club.name,
                         "--season", str(SEASON), stdout=StringIO())
        gps.refresh_from_db()
        claves = [f["key"] for f in gps.config_schema["fields"]]
        self.assertEqual(claves.count("avg_hr_pct"), 1)

    # ── idempotencia ────────────────────────────────────────────────────
    def test_correrlo_dos_veces_no_duplica_plantillas(self):
        call_command("seed_formativo_templates", "--club", self.club.name,
                     "--season", str(SEASON), stdout=StringIO())
        self.assertEqual(
            ExamTemplate.objects.filter(department=self.dept,
                                        slug="carreras").count(), 1)

    def test_una_plantilla_bloqueada_no_se_toca_sin_unlock(self):
        t = self._t("carreras")
        t.is_locked = True
        t.config_schema = {"fields": [{"key": "propio", "label": "Propio",
                                       "type": "number"}]}
        t.save()
        salida = StringIO()
        call_command("seed_formativo_templates", "--club", self.club.name,
                     "--season", str(SEASON), stdout=salida)
        t.refresh_from_db()
        self.assertEqual([f["key"] for f in t.config_schema["fields"]], ["propio"])
        self.assertIn("bloqueada", salida.getvalue())

    def test_un_departamento_inexistente_falla_con_las_opciones(self):
        with self.assertRaises(Exception) as ctx:
            call_command("seed_formativo_templates", "--club", self.club.name,
                         "--department-slug", "no-existe", stdout=StringIO())
        self.assertIn("fisico", str(ctx.exception))
