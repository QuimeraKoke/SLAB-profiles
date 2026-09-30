"""Guards for `exams.lesiones_formativo_ingest` — the matching half.

Every case here came out of the club's real sheet: a RUT that belongs to
someone else, two roster rows sharing a RUT, a roster with one surname fewer
than the sheet, surnames written first, and a namesake two years apart.
"""
from __future__ import annotations

from datetime import date, datetime

from django.test import TestCase

from core.models import Category, Club, Player, PlayerAlias
from exams import lesiones_formativo_ingest as ing

CAB = ["NOMBRE COMPLETO", "Rut", "Edad", "Categoria", "Posición",
       "Parte de cuerpo lesionada", "Lateralidad", "Tipo de lesion",
       "Diagnostico", "Musculo", "Causa", "Recurrencia", "Exposicion",
       "Contacto / Colisión", "Fecha de lesión", "Fecha de Alta",
       "Días perdidos por lesión", "Nº Partidos", "Tratamiento", "Columna 1",
       "Kine responsable", "Columna 2"]
NA = "#N/A (Did not find value in VLOOKUP evaluation.)"


def fila(nombre, rut=NA, edad=13, dia=datetime(2026, 3, 1)):
    return [nombre, rut, edad, "Sub 13", "Defensa", "Muslo", "Derecho",
            "Rotura muscular / Desgarro / Contractura / Calambre",
            "Desgarro isquiotibial", "Isquiotibiales", "Sobrecarga", "No",
            "Partido", "", dia, datetime(2026, 3, 20), 19, 2, "Kinesico",
            "1 Temporada", "Rojas", "Alta"]


class LesionesFormativoMatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cat = Category.objects.create(club=cls.club, name="Serie 2013")

        def jugador(nombre, apellido, segundo="", rut="", dob=date(2013, 1, 1)):
            return Player.objects.create(
                category=cat, first_name=nombre, last_name=apellido,
                second_last_name=segundo, national_id=rut, date_of_birth=dob)

        cls.nazih = jugador("Nazih", "Avendano")
        cls.tomas = jugador("Tomas", "Mandiola", rut="24.651.600-6")
        cls.jair = jugador("Jair", "Fuentes", "Orellana", rut="23907928-8")
        cls.seba = jugador("Sebastian", "Santaella", "Pabon", rut="23.907.928-8")
        cls.esteban = jugador("Esteban", "Caceres", "Gutierrez", dob=date(2009, 9, 15))
        cls.bayron = jugador("Bayron", "Rios", "Guerrero")

    def correr(self, filas, personales=None):
        lesiones, _ = ing.parse_lesiones([CAB, *filas])
        matcher = ing.Matcher(self.club, personales or {})
        return [matcher.match(l) for l in lesiones]

    def test_lee_las_columnas_sin_titulo_por_su_numero(self):
        """`Columna 1` y `Columna 2` normalizados sin dígitos serían la misma."""
        (les,), _ = ing.parse_lesiones([CAB, fila("NAZIH AVENDAÑO CORONA")])
        self.assertEqual(les.datos["fase_temporada"], "1 Temporada")
        self.assertEqual(les.datos["estado"], "Alta")
        self.assertEqual(les.datos["fecha_alta"], date(2026, 3, 20))
        self.assertEqual(les.datos["partidos"], 2)
        self.assertNotIn("rut", les.datos, "un #N/A no es un RUT")

    def test_el_RUT_se_compara_sin_puntos(self):
        (m,) = self.correr([fila("TOMAS MANDIOLA", rut="24651600-6")])
        self.assertEqual((m.player, m.metodo), (self.tomas, "rut"))

    def test_un_RUT_de_otra_persona_no_se_asigna(self):
        """La fila 554 real: el RUT de un chico de 11 en la fila de uno de 19."""
        (m,) = self.correr([fila("FRANCO FERNANDEZ RIVAS", rut="24651600-6", edad=19)])
        self.assertIsNone(m.player)
        self.assertEqual(m.metodo, "conflicto_rut")

    def test_un_RUT_compartido_en_SLAB_lo_desempata_el_nombre(self):
        (m,) = self.correr([fila("JAIR FUENTES ORELLANA", rut="23907928-8")])
        self.assertEqual(m.player, self.jair)

    def test_el_plantel_con_un_apellido_menos(self):
        (m,) = self.correr([fila("NAZIH AVENDAÑO CORONA")])
        self.assertEqual((m.player, m.metodo), (self.nazih, "parcial"))

    def test_los_apellidos_primero(self):
        (m,) = self.correr([fila("MANDIOLA TOMAS")])
        self.assertEqual(m.player, self.tomas)

    def test_un_homonimo_con_otra_edad_no_se_asigna(self):
        (m,) = self.correr([fila("ESTEBAN CACERES", edad=18, dia=datetime(2026, 8, 21))])
        self.assertEqual(m.metodo, "conflicto_edad")

    def test_una_edad_absurda_no_bloquea(self):
        """125 años es el YEARFRAC de la planilla sobre una fecha vacía."""
        (m,) = self.correr([fila("ESTEBAN CACERES", edad=125, dia=datetime(2026, 8, 21))])
        self.assertEqual(m.player, self.esteban)

    def test_un_error_de_tipeo_sugiere_pero_no_asigna(self):
        (m,) = self.correr([fila("BYRON RIOS GERRERO")])
        self.assertIsNone(m.player)
        matcher = ing.Matcher(self.club, {})
        player, puntaje = matcher.sugerencia("BYRON RIOS GERRERO")
        self.assertEqual(player, self.bayron)
        self.assertGreater(puntaje, 0.9)

    def test_un_alias_confirmado_resuelve(self):
        PlayerAlias.objects.create(player=self.bayron, kind=PlayerAlias.KIND_NICKNAME,
                                   value="BYRON RIOS GERRERO")
        (m,) = self.correr([fila("BYRON RIOS GERRERO")])
        self.assertEqual((m.player, m.metodo), (self.bayron, "alias"))

    def test_datos_personales_puente_por_RUT(self):
        personales = {"NAZIH AVENDANO": ing.Personal(
            rut="24651600-6".replace("-", ""), dob=None, tokens={"NAZIH", "AVENDANO"})}
        (m,) = self.correr([fila("NAZIH AVENDANO")], personales)
        # El RUT de Datos Personales es de Tomás: no comparte nombre → conflicto.
        self.assertEqual(m.metodo, "conflicto_rut")


class LesionesFormativoEscrituraTests(TestCase):
    """The write half: lifecycle, idempotency, and what must NOT be written."""

    @classmethod
    def setUpTestData(cls):
        from io import StringIO

        from django.core.management import call_command

        from core.models import Department

        cls.club = Club.objects.create(name="Universidad de Chile")
        Department.objects.create(club=cls.club, name="Médico", slug="medico")
        call_command("seed_lesiones", "--club", cls.club.name, "--create-if-missing",
                     stdout=StringIO())
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2013")
        cls.pe = Category.objects.create(club=cls.club, name="Primer Equipo", is_senior=True)
        cls.gabriel = Player.objects.create(category=cls.cat, first_name="Gabriel",
                                            last_name="Silva", date_of_birth=date(2013, 5, 28))
        cls.andres = Player.objects.create(category=cls.pe, first_name="Andres",
                                           last_name="Bolano", date_of_birth=date(2008, 1, 16))

    def plan(self, filas, hoy=date(2026, 9, 30)):
        lesiones, _ = ing.parse_lesiones([CAB, *filas])
        matcher = ing.Matcher(self.club, {})
        return ing.planificar([(l, matcher.match(l)) for l in lesiones], hoy)

    def escribir(self, filas, **kw):
        planes = self.plan(filas, **kw)
        return planes, ing.escribir(planes, fuente="test")

    def abierta(self, nombre="GABRIEL SILVA", dia=datetime(2026, 9, 22), edad=13):
        f = fila(nombre, dia=dia, edad=edad)
        f[15], f[16], f[21] = "", 8, "Lesionado"       # sin alta, días = TODAY()-fecha
        return f

    def test_una_lesion_con_alta_es_un_episodio_cerrado_con_su_duracion(self):
        from exams.models import Episode

        self.escribir([fila("GABRIEL SILVA")])
        ep = Episode.objects.get(player=self.gabriel)
        self.assertEqual(ep.status, Episode.STATUS_CLOSED)
        self.assertEqual(ep.results.count(), 2)
        d = ep.results.order_by("recorded_at").first().result_data
        self.assertEqual(d["dias_perdidos"], 19, "alta − lesión, no la columna")
        self.assertEqual(d["severity"], "Moderada")
        self.assertEqual(d["body_part"], "Muslo")
        self.assertEqual(d["type"], "Lesion muscular (desgarro/rotura)")
        self.assertEqual(ep.available_at.date(), date(2026, 3, 20))

    def test_los_dias_de_una_abierta_no_se_importan(self):
        """La columna es TODAY() − fecha: 1409 días para una lesión de 2022."""
        from exams.models import Episode

        self.escribir([self.abierta()])
        ep = Episode.objects.get(player=self.gabriel)
        self.assertEqual(ep.status, Episode.STATUS_OPEN)
        d = ep.results.get().result_data
        self.assertNotIn("dias_perdidos", d)
        self.assertNotIn("severity", d)
        self.gabriel.refresh_from_db()
        self.assertEqual(self.gabriel.status, Player.STATUS_INJURED)

    def test_otra_lesion_osea_no_es_una_fractura(self):
        f = fila("GABRIEL SILVA")
        f[7] = "Otra lesión osea"
        (p,) = self.plan([f])
        self.assertEqual(p.datos["type"], "Otro")
        self.assertEqual(p.datos["tipo_club"], "Otra lesión osea")

    def test_correrlo_dos_veces_no_duplica(self):
        from exams.models import Episode

        self.escribir([fila("GABRIEL SILVA")])
        planes, n = self.escribir([fila("GABRIEL SILVA")])
        self.assertEqual(n, {})
        self.assertEqual(Episode.objects.count(), 1)

    def test_una_re_corrida_cierra_la_que_el_club_dio_de_alta(self):
        from exams.models import Episode

        self.escribir([self.abierta()])
        dada = fila("GABRIEL SILVA", dia=datetime(2026, 9, 22))
        dada[15] = datetime(2026, 9, 29)
        _, n = self.escribir([dada])
        self.assertEqual(n, {"cerradas": 1})
        ep = Episode.objects.get(player=self.gabriel)
        self.assertEqual(ep.status, Episode.STATUS_CLOSED)
        self.gabriel.refresh_from_db()
        self.assertEqual(self.gabriel.status, Player.STATUS_AVAILABLE)

    def test_una_abierta_de_primer_equipo_no_se_abre(self):
        (p,) = self.plan([self.abierta("ANDRES BOLANO", dia=datetime(2026, 9, 26), edad=18)])
        self.assertEqual(p.accion, "omitir_senior")

    def test_una_lesion_ya_registrada_por_primer_equipo_se_salta(self):
        from exams.models import Episode, ExamTemplate
        from django.utils import timezone

        Episode.objects.create(
            player=self.andres, template=ExamTemplate.objects.get(slug="lesiones"),
            started_at=timezone.make_aware(datetime(2026, 8, 6, 12)))
        (p,) = self.plan([fila("ANDRES BOLANO", dia=datetime(2026, 8, 1), edad=18)])
        self.assertEqual(p.accion, "ya_existe")

    def test_alta_anterior_a_la_lesion_cierra_sin_duracion(self):
        f = fila("GABRIEL SILVA", dia=datetime(2024, 3, 23), edad=10)
        f[15] = datetime(2024, 1, 4)
        (p,) = self.plan([f])
        self.assertEqual(p.alta, date(2024, 3, 23))
        self.assertNotIn("dias_perdidos", p.datos)

    def test_un_alta_el_mismo_dia_queda_cerrada(self):
        """Apertura y cierre con la misma hora: el "último" salía al azar."""
        from exams.models import Episode

        f = fila("GABRIEL SILVA", dia=datetime(2026, 3, 1))
        f[15] = datetime(2026, 3, 1)
        self.escribir([f])
        ep = Episode.objects.get(player=self.gabriel)
        self.assertEqual(ep.status, Episode.STATUS_CLOSED)
        self.assertEqual(ep.results.order_by("recorded_at").last().result_data["severity"],
                         "Sin tiempo perdido")
