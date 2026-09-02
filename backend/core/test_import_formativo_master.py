"""Guards for `import_formativo_master`.

The command creates 165 players and touches 84 more in one run, so the ways it
can be wrong are the ways that matter: merging two people into one, demoting a
first-team player to his birth cohort, or overwriting a good birth date with a
spreadsheet artifact. Each of those is silent — the run reports success and the
damage surfaces weeks later in someone's profile.

Every case here is taken from the real data.
"""
from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket, Category, Club, Player

CABECERA = ("nombre;cohorte;fecha_nacimiento;serie;posicion;estado;"
            "bracket_2026;fuente_fecha;fuente_cohorte;promocion")


def csv_con(*filas: str) -> str:
    return "\n".join([CABECERA, *filas]) + "\n"


class ImportFormativoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.create(code=code, name=name, age=age, order=order)

    def correr(self, contenido: str, *args) -> str:
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "maestro.csv"
            ruta.write_text(contenido, encoding="utf-8")
            salida = StringIO()
            call_command("import_formativo_master", "--csv", str(ruta),
                         "--club", self.club.name, "--season", "2026",
                         *args, stdout=salida)
            return salida.getvalue()

    def _serie(self, cohorte: int) -> Category:
        return Category.objects.create(club=self.club, name=f"Serie {cohorte}",
                                       cohort_year=cohorte)

    # ── el invariante central ───────────────────────────────────────────
    def test_dos_personas_con_la_misma_fecha_no_se_fusionan(self):
        """El caso que rompería todo en silencio.

        Cuatro jugadores del maestro comparten 2012-01-04 (celda arrastrada en
        la planilla). Emparejar sólo por fecha los colapsaría en uno; el guard
        exige además apellido en común.
        """
        serie = self._serie(2012)
        Player.objects.create(category=serie, first_name="Claudio",
                              last_name="Pincheira", date_of_birth=date(2012, 1, 4))
        self.correr(csv_con(
            "MARTIN CARRASCO SOTO;2012;2012-01-04;Serie 2012;MEDIOCAMPISTA;plantel;;;;",
        ), "--commit")
        self.assertEqual(
            Player.objects.filter(category__club=self.club).count(), 2,
            "Martín Carrasco se fusionó con Claudio Pincheira por compartir fecha",
        )

    def test_la_fecha_empareja_aunque_el_nombre_venga_incompleto(self):
        # El caso normal: SLAB guarda "Agustin Korn", el club escribe
        # "AGUSTIN KORN ALDUNATE".
        serie = self._serie(2007)
        p = Player.objects.create(category=serie, first_name="Agustin",
                                  last_name="Korn", date_of_birth=date(2007, 1, 3))
        self.correr(csv_con(
            "AGUSTIN KORN ALDUNATE;2007;2007-01-03;Serie 2007;DEFENSA CENTRAL;plantel;;;;",
        ), "--commit")
        self.assertEqual(Player.objects.filter(category__club=self.club).count(), 1)
        p.refresh_from_db()
        self.assertEqual(p.second_last_name, "Aldunate",
                         "debía completarle el apellido materno que faltaba")

    # ── las tres cosas que no hace sin pedirlo ──────────────────────────
    def test_no_baja_a_un_jugador_del_primer_equipo_a_su_cohorte(self):
        senior = Category.objects.create(club=self.club, name="Primer Equipo",
                                         is_senior=True)
        p = Player.objects.create(category=senior, first_name="Andres",
                                  last_name="Bolano", second_last_name="Vera",
                                  date_of_birth=date(2008, 1, 16))
        salida = self.correr(csv_con(
            "ANDRES BOLANO VERA;2008;2008-01-16;Serie 2008;EXTREMO;plantel;;;;",
        ), "--commit", "--reassign")     # incluso con --reassign
        p.refresh_from_db()
        self.assertEqual(p.category, senior)
        self.assertIn("categoría senior", salida)

    def test_no_pisa_la_fecha_de_la_base_sin_overwrite_dob(self):
        """2006-05-26 está arrastrada en la planilla para tres jugadores.

        Cada uno tiene en base una fecha distinta y correcta, así que dejar
        ganar al archivo corrompería los tres registros.
        """
        serie = self._serie(2006)
        p = Player.objects.create(category=serie, first_name="Ruben",
                                  last_name="Vera", second_last_name="Zamorano",
                                  date_of_birth=date(2006, 3, 14))
        salida = self.correr(csv_con(
            "RUBEN VERA ZAMORANO;2006;2006-05-26;Serie 2006;MEDIOCAMPISTA;plantel;;;;",
        ), "--commit")
        p.refresh_from_db()
        self.assertEqual(p.date_of_birth, date(2006, 3, 14))
        self.assertIn("Fecha en conflicto", salida)

    def test_no_mueve_de_categoria_sin_reassign(self):
        vieja = Category.objects.create(club=self.club, name="SUB-20")
        nueva = self._serie(2006)
        p = Player.objects.create(category=vieja, first_name="Alonso",
                                  last_name="Villegas", second_last_name="Munita",
                                  date_of_birth=date(2006, 6, 13))
        fila = "ALONSO VILLEGAS MUNITA;2006;2006-06-13;Serie 2006;DEFENSA CENTRAL;plantel;;;;"
        salida = self.correr(csv_con(fila), "--commit")
        p.refresh_from_db()
        self.assertEqual(p.category, vieja)
        self.assertIn("Categoría distinta", salida)

        self.correr(csv_con(fila), "--commit", "--reassign")
        p.refresh_from_db()
        self.assertEqual(p.category, nueva, "con --reassign sí debía moverlo")

    # ── la escalera ─────────────────────────────────────────────────────
    def test_las_series_bajo_Sub_11_no_reciben_TeamSeason(self):
        """`Bracket.for_age(8)` devuelve Sub 11 porque es un TECHO.

        Series 2016, 2017 y 2018 son tres grupos internos distintos y la ANFP
        no organiza competencia para ellos. Usar el techo les daría a los tres
        una TeamSeason de Sub 11, o sea tres equipos en un mismo bracket.
        """
        salida = self.correr(csv_con(
            "NICOLAS SOTO ROJAS;2018;2018-04-02;Serie 2018;EXTREMO;plantel;;;;",
            "PEDRO DIAZ LEIVA;2015;2015-04-02;Serie 2015;EXTREMO;plantel;;;;",
        ), "--commit")
        s2018 = Category.objects.get(club=self.club, cohort_year=2018)
        s2015 = Category.objects.get(club=self.club, cohort_year=2015)
        self.assertFalse(s2018.team_seasons.exists())
        self.assertEqual(s2015.team_seasons.get(season=2026).bracket.age, 11)
        self.assertIn("bajo Sub 11", salida)

    def test_el_bracket_salta_los_huecos_de_la_escalera(self):
        # Serie 2009 tiene 17 años en 2026 y no existe Sub 17: juega Sub 18.
        self.correr(csv_con(
            "JUAN PEREZ SOTO;2009;2009-05-05;Serie 2009;MEDIOCAMPISTA;plantel;;;;",
        ), "--commit")
        serie = Category.objects.get(club=self.club, cohort_year=2009)
        self.assertEqual(serie.team_seasons.get(season=2026).bracket.name, "Sub 18")

    def test_las_cohortes_sobre_edad_no_reciben_TeamSeason_juvenil(self):
        salida = self.correr(csv_con(
            "MARIO SILVA ROJAS;2004;2004-05-05;Serie 2004;MEDIOCAMPISTA;plantel;;;;",
        ), "--commit")
        serie = Category.objects.get(club=self.club, cohort_year=2004)
        self.assertFalse(serie.team_seasons.exists())
        self.assertIn("sobre-edad", salida)

    # ── simulación fiel ─────────────────────────────────────────────────
    def test_sin_commit_no_escribe_nada(self):
        antes = Player.objects.count(), Category.objects.count()
        self.correr(csv_con(
            "NUEVO JUGADOR TEST;2013;2013-05-05;Serie 2013;EXTREMO;plantel;;;;",
        ))
        self.assertEqual((Player.objects.count(), Category.objects.count()), antes)

    def test_la_simulacion_reporta_lo_mismo_que_el_commit(self):
        """Los `if commit:` de la primera versión hacían que la simulación
        tomara otro camino: no creaba las categorías nuevas y por eso no
        reportaba ni sus TeamSeason ni los jugadores que dependían de ellas.
        """
        filas = csv_con(
            "ANA SOTO LEIVA;2015;2015-05-05;Serie 2015;EXTREMO;plantel;;;;",
            "LUIS DIAZ MORA;2009;2009-05-05;Serie 2009;GUARDAMETA;plantel;;;;",
        )
        seco = self.correr(filas)
        firme = self.correr(filas, "--commit")
        quitar = lambda t: "\n".join(
            l for l in t.splitlines() if "SIMULACIÓN" not in l and "APLICADO" not in l)
        self.assertEqual(quitar(seco), quitar(firme))

    # ── nombres ─────────────────────────────────────────────────────────
    def test_el_nombre_compuesto_no_se_parte_mal(self):
        self.correr(csv_con(
            "JOSE MIGUEL SOTO ROJAS;2013;2013-05-05;Serie 2013;EXTREMO;plantel;;;;",
        ), "--commit")
        p = Player.objects.get(last_name="Soto")
        self.assertEqual((p.first_name, p.last_name, p.second_last_name),
                         ("Jose Miguel", "Soto", "Rojas"))

    def test_un_nombre_de_dos_tokens_deja_el_materno_vacio(self):
        # No se inventa: en estos archivos falta seguido.
        self.correr(csv_con(
            "ELIAS ROJAS;2005;2005-05-05;Serie 2005;EXTREMO;plantel;;;;",
        ), "--commit")
        p = Player.objects.get(last_name="Rojas")
        self.assertEqual(p.second_last_name, "")
