"""Guards for the Formativo's wellness ingest.

Every one of these is a bug that already happened while writing it, and every
one of them is silent: the import reports success, the numbers stay in range,
and the data is wrong in a way nobody can see from the screen.
"""
from __future__ import annotations

from datetime import date, datetime

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams import wellness_formativo_ingest as ing
from exams.models import ExamResult, ExamTemplate


class CohortesDelTituloTests(SimpleTestCase):
    """`SUB 18 - 2025 - CAT 08-07` → qué cohortes cubre el documento."""

    def test_una_sola_cohorte(self):
        self.assertEqual(ing.cohortes_del_titulo("SUB 11 - 2026 - CAT 15"), [2015])

    def test_un_rango_se_expande(self):
        # `CAT 07-05` son TRES cohortes, no dos: 2007, 2006 y 2005.
        self.assertEqual(ing.cohortes_del_titulo("SUB 21 - 2026 - CAT 07-05"),
                         [2005, 2006, 2007])

    def test_el_guion_ya_no_esta_cuando_se_evalua(self):
        """La regresión: `norm` reemplaza el guion por un espacio.

        Una regex que siguiera buscando `08-07` devolvía [] justo en los dos
        documentos multi-cohorte — que son los que tienen a los homónimos, así
        que el desempate por cohorte no actuaba donde único hacía falta.
        """
        self.assertEqual(ing.cohortes_del_titulo("SUB 18 - 2025 - CAT 08-07"),
                         [2007, 2008])

    def test_un_titulo_sin_cat_no_inventa_cohortes(self):
        self.assertEqual(ing.cohortes_del_titulo("Wellness 2026"), [])
        self.assertEqual(ing.cohortes_del_titulo(""), [])


class ParseoTests(SimpleTestCase):
    def _grid_checkin(self, cabeceras, *filas):
        return [cabeceras, *filas]

    def test_mapea_por_nombre_y_no_por_posicion(self):
        """El orden de columnas cambia entre los ocho documentos.

        `SUB 13` pone peso e hidratación en las columnas 2 y 3 donde el resto
        las tiene en la 8 y la 10. Un lector posicional cargaría la hidratación
        dentro de la calidad de sueño de una categoría entera y reportaría
        éxito.
        """
        orden_a = ["Marca temporal", "JUGADOR", "CALIDAD SUEÑO", "Peso (kg)"]
        orden_b = ["Marca temporal", "JUGADOR", "Peso (kg)", "CALIDAD SUEÑO"]
        a, _ = ing.parsear([orden_a, [45665.5, "X Y", 4, 70]], rol="checkin")
        b, _ = ing.parsear([orden_b, [45665.5, "X Y", 70, 4]], rol="checkin")
        self.assertEqual(a[0]["calidad_sueno"], 4)
        self.assertEqual(b[0]["calidad_sueno"], 4)
        self.assertEqual(a[0]["peso"], b[0]["peso"])

    def test_acepta_las_variantes_de_encabezado_del_club(self):
        for cabecera in ("CALIDAD SUEÑO", "CALIDAD DEL SUEÑO"):
            filas, sin_mapear = ing.parsear(
                [["Marca temporal", "JUGADOR", cabecera], [45665.5, "X Y", 5]],
                rol="checkin")
            self.assertEqual(filas[0]["calidad_sueno"], 5, cabecera)
            self.assertEqual(sin_mapear, [], cabecera)
        for cabecera in ("Peso (kg)", "Peso (kg) solo número"):
            filas, _ = ing.parsear(
                [["Marca temporal", "JUGADOR", cabecera], [45665.5, "X Y", 62]],
                rol="checkin")
            self.assertEqual(filas[0]["peso"], 62, cabecera)

    def test_el_dano_del_checkout_tiene_dos_nombres(self):
        for cabecera in ("DAÑO MUSCULAR", "PERCEPCIÓN MOLESTIAS/DOLORES"):
            filas, sin_mapear = ing.parsear(
                [["Marca temporal", "JUGADOR", cabecera], [45665.5, "X Y", 3]],
                rol="checkout")
            self.assertEqual(filas[0]["dano_muscular"], 3, cabecera)
            self.assertEqual(sin_mapear, [], cabecera)

    def test_una_columna_nueva_se_reporta_no_se_descarta(self):
        """Un encabezado que el club agregue mañana tiene que gritar.

        Descartarlo en silencio es exactamente cómo una métrica desaparece sin
        que nadie lo note — ya pasó con cinco métricas del GPS.
        """
        _, sin_mapear = ing.parsear(
            [["Marca temporal", "JUGADOR", "PREGUNTA NUEVA"],
             [45665.5, "X Y", 1]], rol="checkin")
        self.assertEqual(sin_mapear, ["PREGUNTA NUEVA"])

    def test_suma_y_ua_no_se_importan_pero_tampoco_se_reportan(self):
        # Las calcula la plantilla; están declaradas para que no aparezcan como
        # columnas desconocidas.
        filas, sin_mapear = ing.parsear(
            [["Marca temporal", "JUGADOR", "CALIDAD SUEÑO", "SUMA"],
             [45665.5, "X Y", 4, 19]], rol="checkin")
        self.assertEqual(sin_mapear, [])
        self.assertNotIn("suma", filas[0])
        filas, sin_mapear = ing.parsear(
            [["Marca temporal", "JUGADOR", "Nivel de esfuerzo percibido", "AU"],
             [45665.5, "X Y", 6, 420]], rol="checkout")
        self.assertEqual(sin_mapear, [], "`AU` es el typo de uno de los ocho")
        self.assertNotIn("carga_interna", filas[0])

    def test_el_timestamp_conserva_la_hora(self):
        """La idempotencia es `(jugador, recorded_at)`.

        Truncar a medianoche haría que el segundo check-in de la semana pareciera
        un duplicado del primero.
        """
        filas, _ = ing.parsear(
            [["Marca temporal", "JUGADOR", "CALIDAD SUEÑO"],
             [46268.58700299769, "X Y", 4]], rol="checkin")
        self.assertEqual(filas[0]["_ts"], datetime(2026, 9, 3, 14, 5, 17))

    def test_ninguno_se_limpia_solo_en_las_columnas_de_molestia(self):
        filas, _ = ing.parsear(
            [["Marca temporal", "JUGADOR", "Señala tu dolor muscular",
              "Nivel de esfuerzo percibido"],
             [45665.5, "X Y", "Ninguno", 6]], rol="checkout")
        self.assertNotIn("dolor_muscular", filas[0])

    def test_un_no_legitimo_no_se_borra(self):
        """La regresión: `NO` está en la lista de "nada" porque es como el
        jugador dice que no le duele, pero también es la respuesta real de
        `¿Consumiste tu proteína post-entrenamiento?`. Aplicar el filtro a todo
        el texto convertía cada "No" en un campo ausente."""
        filas, _ = ing.parsear(
            [["Marca temporal", "JUGADOR", "Nivel de esfuerzo percibido",
              "¿Consumiste tu proteína post-entrenamiento?"],
             [45665.5, "X Y", 6, "No"]], rol="checkout")
        self.assertEqual(filas[0]["proteina_post"], "No")

    def test_una_fila_de_arrastre_no_entra(self):
        filas, _ = ing.parsear(
            [["Marca temporal", "JUGADOR", "CALIDAD SUEÑO"],
             [45665.5, "X Y", 4], ["", "", ""]], rol="checkin")
        self.assertEqual(len(filas), 1)


class ResolucionDeNombreTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="U")
        self.dept = Department.objects.create(club=self.club, name="F", slug="fisico")
        self.cats = {}
        for año in (2008, 2010, 2011, 2013):
            c = Category.objects.create(club=self.club, name=f"Serie {año}",
                                        cohort_year=año)
            c.departments.add(self.dept)
            self.cats[año] = c
        # SUB-20 es el bucket de arriba: junta varias cohortes y su
        # `cohort_year` es NULL.
        self.sub20 = Category.objects.create(club=self.club, name="SUB-20")
        self.sub20.departments.add(self.dept)

    def _jugador(self, nombre, apellido, segundo, cat, nac):
        return Player.objects.create(
            category=cat, first_name=nombre, last_name=apellido,
            second_last_name=segundo, date_of_birth=nac, is_active=True)

    def test_el_apellido_materno_entra_en_la_clave(self):
        """`Tomás De Araya` se guarda como last=`De` second=`Araya`.

        Buscar sólo por nombre + paterno pedía `TOMAS DE`, y 37 de sus
        check-ins volvían "sin jugador" con su ficha ahí al lado.
        """
        p = self._jugador("Tomas", "De", "Araya", self.cats[2013], date(2013, 5, 1))
        indice = ing.indice_jugadores(self.club)
        self.assertEqual(ing.resolver_jugador("TOMAS DE ARAYA", indice, [2013])[0], p)

    def test_la_cohorte_desempata_a_los_homonimos(self):
        """Los dos David Guzmán, que es el caso real del club."""
        vivanco = self._jugador("David", "Guzman", "Vivanco",
                                self.cats[2008], date(2008, 6, 9))
        bascur = self._jugador("David", "Guzman", "Bascur",
                               self.cats[2011], date(2011, 2, 10))
        indice = ing.indice_jugadores(self.club)
        self.assertEqual(ing.resolver_jugador("DAVID GUZMAN", indice, [2007, 2008])[0],
                         vivanco)
        self.assertEqual(ing.resolver_jugador("DAVID GUZMAN", indice, [2011])[0],
                         bascur)

    def test_sin_cohorte_que_desempate_se_reporta_no_se_adivina(self):
        self._jugador("David", "Guzman", "Vivanco", self.cats[2008], date(2008, 6, 9))
        self._jugador("David", "Guzman", "Bascur", self.cats[2011], date(2011, 2, 10))
        indice = ing.indice_jugadores(self.club)
        player, motivo = ing.resolver_jugador("DAVID GUZMAN", indice, [])
        self.assertIsNone(player)
        self.assertEqual(motivo, "ambiguo")

    def test_el_bucket_de_arriba_se_encuentra_por_fecha_de_nacimiento(self):
        """`SUB-20` no tiene `cohort_year`, así que sus jugadores sólo entran
        al índice por cohorte a través de su año de nacimiento."""
        p = self._jugador("Renato", "Cruzat", "", self.sub20, date(2007, 3, 3))
        indice = ing.indice_jugadores(self.club)
        self.assertEqual(
            ing.resolver_jugador("RENATO CRUZAT", indice, [2005, 2006, 2007])[0], p)

    def test_nombre_mas_materno_no_le_roba_la_clave_al_otro(self):
        """La regresión que costó ~970 filas.

        `Lucas Pantoja Nuñez` firma a veces `LUCAS NUÑEZ`, pero esa clave es de
        `Lucas Nuñez Leon`. Si las dos compiten en el mismo nivel, las dos
        quedan ambiguas y ninguna de las dos importa nada.
        """
        leon = self._jugador("Lucas", "Nuñez", "Leon", self.cats[2010],
                             date(2010, 4, 5))
        self._jugador("Lucas", "Pantoja", "Nuñez", self.cats[2011],
                      date(2011, 2, 12))
        indice = ing.indice_jugadores(self.club)
        self.assertEqual(ing.resolver_jugador("LUCAS NUÑEZ", indice, [])[0], leon)

    def test_el_nivel_secundario_actua_cuando_el_primario_no_encuentra_a_nadie(self):
        """`Mathias Restrepo Rojas` firma `MATHIAS ROJAS` — 760 filas suyas."""
        p = self._jugador("Mathias", "Restrepo", "Rojas", self.cats[2011],
                          date(2011, 3, 18))
        indice = ing.indice_jugadores(self.club)
        self.assertEqual(ing.resolver_jugador("MATHIAS ROJAS", indice, [2011])[0], p)

    def test_un_typo_de_un_caracter_se_perdona(self):
        p = self._jugador("Bryan", "Contreras", "", self.cats[2013],
                          date(2013, 1, 1))
        indice = ing.indice_jugadores(self.club)
        self.assertEqual(ing.resolver_jugador("BRAYAN CONTRERAS", indice, [2013])[0], p)

    def test_dos_typos_ya_no(self):
        self._jugador("Bryan", "Contreras", "", self.cats[2013], date(2013, 1, 1))
        indice = ing.indice_jugadores(self.club)
        player, motivo = ing.resolver_jugador("BRAYANO CONTRERAZ", indice, [2013])
        self.assertIsNone(player)
        self.assertEqual(motivo, "no_encontrado")

    def test_un_typo_ambiguo_no_se_resuelve(self):
        """Dos jugadores a UN carácter del mismo texto: reportar, no elegir.

        `PERAZ` está a un carácter de `PEREZ` y de `PERAS`, y a dos de `PERES`
        — que es por qué este caso necesita los dos apellidos exactos: con
        `Peres` habría un único candidato y la resolución sería correcta.
        """
        self._jugador("Juan", "Perez", "", self.cats[2013], date(2013, 1, 1))
        self._jugador("Juan", "Peras", "", self.cats[2013], date(2013, 2, 2))
        indice = ing.indice_jugadores(self.club)
        self.assertIsNone(ing.resolver_jugador("JUAN PERAZ", indice, [2013])[0])

    def test_el_orden_del_nombre_da_igual(self):
        p = self._jugador("Franco", "Caceres", "Perez", self.cats[2010],
                          date(2010, 4, 27))
        indice = ing.indice_jugadores(self.club)
        for escrito in ("FRANCO CACERES", "CACERES FRANCO",
                        "FRANCO CACERES PEREZ", "Franco Cáceres"):
            self.assertEqual(ing.resolver_jugador(escrito, indice, [2010])[0], p,
                             escrito)


class IngestaTests(TestCase):
    """El camino completo contra un documento simulado."""

    class DocFalso:
        def __init__(self, hojas):
            self._hojas = hojas

        def worksheets(self):
            return list(self._hojas)

        def values(self, hoja):
            return self._hojas[hoja]

    def setUp(self):
        self.club = Club.objects.create(name="U")
        self.dept = Department.objects.create(club=self.club, name="F", slug="fisico")
        self.cat = Category.objects.create(club=self.club, name="Serie 2013",
                                           cohort_year=2013)
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="Tomas", last_name="De",
            second_last_name="Araya", date_of_birth=date(2013, 5, 1),
            is_active=True)
        self.template = ExamTemplate.objects.create(
            name="Check-IN formativo", slug=ing.CHECKIN_SLUG, department=self.dept,
            config_schema={"fields": [
                {"key": "calidad_sueno", "type": "number", "label": "Sueño",
                 "min": 1, "max": 5},
            ]},
        )
        self.template.applicable_categories.add(self.cat)

    def _doc(self, *filas):
        return self.DocFalso({
            "CHECK IN": [["Marca temporal", "JUGADOR", "CALIDAD SUEÑO"], *filas],
        })

    def test_crea_los_resultados(self):
        rep = ing.ingerir(self._doc([46268.587, "TOMAS DE ARAYA", 4]),
                          titulo="SUB 13 - 2026 - CAT 13", club=self.club,
                          rol="checkin", commit=True)
        self.assertEqual(rep.creados, 1)
        r = ExamResult.objects.get()
        self.assertEqual(r.player, self.player)
        self.assertEqual(r.result_data["calidad_sueno"], 4)
        self.assertEqual(r.result_data["origen"], "google_sheets_formativo")

    def test_una_segunda_corrida_no_duplica(self):
        doc = self._doc([46268.587, "TOMAS DE ARAYA", 4])
        ing.ingerir(doc, titulo="SUB 13 - 2026 - CAT 13", club=self.club,
                    rol="checkin", commit=True)
        rep = ing.ingerir(doc, titulo="SUB 13 - 2026 - CAT 13", club=self.club,
                          rol="checkin", commit=True)
        self.assertEqual((rep.creados, rep.repetidos), (0, 1))
        self.assertEqual(ExamResult.objects.count(), 1)

    def test_dos_respuestas_del_mismo_dia_son_dos_filas(self):
        """Mismo día, distinta hora: no son un duplicado."""
        rep = ing.ingerir(
            self._doc([46268.25, "TOMAS DE ARAYA", 4],
                      [46268.75, "TOMAS DE ARAYA", 3]),
            titulo="SUB 13 - 2026 - CAT 13", club=self.club, rol="checkin",
            commit=True)
        self.assertEqual(rep.creados, 2)

    def test_sin_commit_no_escribe(self):
        rep = ing.ingerir(self._doc([46268.587, "TOMAS DE ARAYA", 4]),
                          titulo="SUB 13 - 2026 - CAT 13", club=self.club,
                          rol="checkin", commit=False)
        self.assertEqual(rep.creados, 1, "cuenta lo que haría")
        self.assertEqual(ExamResult.objects.count(), 0)

    def test_un_nombre_desconocido_se_reporta_y_no_frena_al_resto(self):
        rep = ing.ingerir(
            self._doc([46268.25, "JUGADOR QUE NO EXISTE", 4],
                      [46268.75, "TOMAS DE ARAYA", 3]),
            titulo="SUB 13 - 2026 - CAT 13", club=self.club, rol="checkin",
            commit=True)
        self.assertEqual(rep.creados, 1)
        self.assertEqual(rep.no_encontrados, {"JUGADOR QUE NO EXISTE": 1})

    def test_la_ventana_deja_afuera_lo_viejo(self):
        viejo = 45323.94       # 2024-02-01
        rep = ing.ingerir(self._doc([viejo, "TOMAS DE ARAYA", 4]),
                          titulo="SUB 13 - 2026 - CAT 13", club=self.club,
                          rol="checkin", commit=True,
                          desde=timezone.now() - timezone.timedelta(days=7)
                          if hasattr(timezone, "timedelta") else ing.ventana(7))
        self.assertEqual(rep.creados, 0)

    def test_una_hoja_que_no_existe_no_revienta(self):
        rep = ing.ingerir(self.DocFalso({"OTRA": []}),
                          titulo="SUB 13 - 2026 - CAT 13", club=self.club,
                          rol="checkin", commit=True)
        self.assertEqual((rep.filas, rep.creados), (0, 0))
