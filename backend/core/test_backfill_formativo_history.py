"""Guards for `backfill_formativo_history`.

The command rewrote 235 existing `since` dates and created 159 memberships in
one run. The failure modes are quiet: a spell that starts later than the player
actually joined, a call-up that silently widens who can see a minor's data, or
a duplicate spell that makes the history unreadable.
"""
from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import (Bracket, Category, Club, Player, PlayerCallUp,
                         PlayerTeamMembership as Membership)

CABECERA = ("nombre;cohorte;temporada;bracket;sesiones;primera;ultima;"
            "sobre_su_serie")


def csv_con(*filas: str) -> str:
    return "\n".join([CABECERA, *filas]) + "\n"


class BackfillHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.brackets = {}
        for order, (code, name, age) in enumerate(BRACKETS):
            cls.brackets[age] = Bracket.objects.create(
                code=code, name=name, age=age, order=order)

    def correr(self, contenido: str, *args) -> str:
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "historial.csv"
            ruta.write_text(contenido, encoding="utf-8")
            salida = StringIO()
            call_command("backfill_formativo_history", "--csv", str(ruta),
                         "--club", self.club.name, "--season", "2026",
                         *args, stdout=salida)
            return salida.getvalue()

    def _jugador(self, nombre: str, cohorte: int, **kwargs) -> Player:
        partes = nombre.split()
        categoria, _ = Category.objects.get_or_create(
            club=self.club, name=f"Serie {cohorte}",
            defaults={"cohort_year": cohorte})
        return Player.objects.create(
            category=categoria, first_name=partes[0], last_name=partes[1],
            second_last_name=partes[2] if len(partes) > 2 else "", **kwargs)

    # ── fechas ──────────────────────────────────────────────────────────
    def test_crea_la_pertenencia_con_la_primera_aparicion(self):
        p = self._jugador("Alonso Musrri Diaz", 2015)
        self.correr(csv_con(
            "ALONSO MUSRRI DIAZ;2015;2026;Sub 11;9;2026-02-03;2026-06-20;",
        ), "--commit")
        spell = p.team_memberships.get()
        self.assertEqual(spell.since, date(2026, 2, 3))
        self.assertEqual(spell.team, p.category)

    def test_la_evidencia_mas_antigua_gana_sobre_la_fecha_registrada(self):
        """El caso de los 219.

        `backfill_cohorts` usó la fecha del primer PARTIDO. Un entrenamiento o
        un test anterior prueba que el jugador ya estaba, así que la fecha del
        partido era sólo lo más antiguo que ese comando podía ver. `since` es
        una cota inferior: no son dos hechos en conflicto.
        """
        p = self._jugador("Agustin Korn Aldunate", 2007)
        Membership.objects.create(player=p, team=p.category,
                                  since=date(2025, 3, 2),
                                  reason="carga inicial (fecha del primer partido)")
        self.correr(csv_con(
            "AGUSTIN KORN ALDUNATE;2007;2024;Sub 20;12;2024-01-22;2024-11-30;",
        ), "--commit")
        spell = p.team_memberships.get()
        self.assertEqual(spell.since, date(2024, 1, 22))
        self.assertEqual(p.team_memberships.count(), 1, "no debía crear un 2º spell")

    def test_no_atrasa_una_fecha_que_ya_era_mas_antigua(self):
        # La cota inferior sólo puede bajar.
        p = self._jugador("Martin Tampe Uribe", 2010)
        Membership.objects.create(player=p, team=p.category,
                                  since=date(2023, 1, 15), reason="traspaso")
        self.correr(csv_con(
            "MARTIN TAMPE URIBE;2010;2026;Sub 16;5;2026-04-01;2026-05-01;",
        ), "--commit")
        spell = p.team_memberships.get()
        self.assertEqual(spell.since, date(2023, 1, 15))
        self.assertEqual(spell.reason, "traspaso", "no debía pisar el motivo")

    def test_una_aparicion_sobre_su_serie_igual_cuenta_como_estar_en_el_club(self):
        # Jugar arriba no cambia el equipo de origen, así que la fecha sirve
        # como evidencia de pertenencia a su propia serie.
        p = self._jugador("Alvaro Barrera Calderon", 2010)
        self.correr(csv_con(
            "ALVARO BARRERA CALDERON;2010;2026;Sub 18;3;2026-01-10;2026-02-10;sí",
        ), "--commit")
        self.assertEqual(p.team_memberships.get().since, date(2026, 1, 10))

    def test_no_inventa_pertenencia_sin_evidencia_fechada(self):
        # Seis jugadores del maestro no aparecen en ninguna sesión. Sin fecha
        # honesta, quedarse sin spell es mejor que fabricar una.
        p = self._jugador("Moussa Conde", 2013)
        self.correr(csv_con(
            "OTRO JUGADOR CUALQUIERA;2013;2026;Sub 13;3;2026-01-10;2026-02-10;",
        ), "--commit")
        self.assertFalse(p.team_memberships.exists())

    # ── citaciones ──────────────────────────────────────────────────────
    def test_sin_call_ups_no_crea_ninguna(self):
        self._jugador("Alejandro Bustamante Lara", 2010)
        salida = self.correr(csv_con(
            "ALEJANDRO BUSTAMANTE LARA;2010;2026;Sub 18;51;2026-03-01;2026-07-01;sí",
        ), "--commit")
        self.assertEqual(PlayerCallUp.objects.count(), 0)
        self.assertIn("Citaciones NO escritas", salida)

    def test_las_citaciones_se_crean_inactivas(self):
        """Activarlas ensancharía el acceso a datos de menores.

        `active=True` hace que el cuerpo técnico de esa categoría vea al
        jugador (`api.scoping.scope_players`). Concederlo desde una planilla
        es un cambio de permisos, no una importación de datos.
        """
        p = self._jugador("Alejandro Bustamante Lara", 2010)
        destino = Category.objects.create(club=self.club, name="Serie 2009",
                                          cohort_year=2009)
        destino.team_seasons.create(season=2026, bracket=self.brackets[18])
        self.correr(csv_con(
            "ALEJANDRO BUSTAMANTE LARA;2010;2026;Sub 18;51;2026-03-01;2026-07-01;sí",
        ), "--commit", "--call-ups")
        cu = PlayerCallUp.objects.get(player=p)
        self.assertFalse(cu.active)
        self.assertEqual(cu.category, destino)
        self.assertEqual(cu.since, date(2026, 3, 1))
        self.assertIn("51 sesiones", cu.note)

    def test_el_destino_se_resuelve_por_TeamSeason_no_por_la_etiqueta(self):
        """El plantel mayor se llama SUB-20, no "Serie 2006".

        Deducir la categoría desde "Sub 20" apuntaría a una Serie que no
        existe; hay que preguntarle a TeamSeason quién juega ese bracket.
        """
        p = self._jugador("Andher Gonzalez Herrera", 2009)
        bucket = Category.objects.create(club=self.club, name="SUB-20")
        bucket.team_seasons.create(season=2026, bracket=self.brackets[20])
        self.correr(csv_con(
            "ANDHER GONZALEZ HERRERA;2009;2026;Sub 20;7;2026-04-01;2026-06-01;sí",
        ), "--commit", "--call-ups")
        self.assertEqual(PlayerCallUp.objects.get(player=p).category, bucket)

    def test_solo_la_temporada_indicada(self):
        # Una aparición en Sub 16 en 2024 es historia, y PlayerCallUp no tiene
        # fecha de término para decirlo.
        self._jugador("Cesar Perez Gallegos", 2010)
        destino = Category.objects.create(club=self.club, name="Serie 2008",
                                          cohort_year=2008)
        destino.team_seasons.create(season=2026, bracket=self.brackets[18])
        self.correr(csv_con(
            "CESAR PEREZ GALLEGOS;2010;2024;Sub 18;9;2024-06-18;2024-12-20;sí",
        ), "--commit", "--call-ups")
        self.assertEqual(PlayerCallUp.objects.count(), 0)

    def test_no_duplica_una_citacion_existente(self):
        p = self._jugador("Andres Bolano Vera", 2008)
        destino = Category.objects.create(club=self.club, name="SUB-20")
        destino.team_seasons.create(season=2026, bracket=self.brackets[20])
        PlayerCallUp.objects.create(player=p, category=destino, active=True)
        salida = self.correr(csv_con(
            "ANDRES BOLANO VERA;2008;2026;Sub 20;5;2026-04-01;2026-06-01;sí",
        ), "--commit", "--call-ups")
        self.assertEqual(PlayerCallUp.objects.filter(player=p).count(), 1)
        self.assertTrue(PlayerCallUp.objects.get(player=p).active,
                        "no debía desactivar una citación creada a mano")
        self.assertIn("ya existían", salida)

    def test_no_se_cita_a_un_jugador_a_su_propia_categoria(self):
        p = self._jugador("Juan Perez Soto", 2009)
        p.category.team_seasons.create(season=2026, bracket=self.brackets[18])
        self.correr(csv_con(
            "JUAN PEREZ SOTO;2009;2026;Sub 18;9;2026-04-01;2026-06-01;sí",
        ), "--commit", "--call-ups")
        self.assertEqual(PlayerCallUp.objects.count(), 0)

    # ── robustez ────────────────────────────────────────────────────────
    def test_los_nombres_a_prueba_se_reportan_sin_romper(self):
        # 74 de los 77 no emparejados son jugadores a prueba, que la fase 2 no
        # importa. Es esperado, no un error.
        salida = self.correr(csv_con(
            "ADAM ALCANTARA;2012;2026;Sub 14;1;2026-01-10;2026-01-10;",
        ), "--commit")
        self.assertIn("Sin jugador en SLAB", salida)

    def test_sin_commit_no_escribe(self):
        self._jugador("Alonso Musrri Diaz", 2015)
        self.correr(csv_con(
            "ALONSO MUSRRI DIAZ;2015;2026;Sub 11;9;2026-02-03;2026-06-20;",
        ))
        self.assertEqual(Membership.objects.count(), 0)

    def test_correrlo_dos_veces_no_cambia_nada(self):
        p = self._jugador("Alonso Musrri Diaz", 2015)
        filas = csv_con(
            "ALONSO MUSRRI DIAZ;2015;2026;Sub 11;9;2026-02-03;2026-06-20;")
        self.correr(filas, "--commit")
        self.correr(filas, "--commit")
        self.assertEqual(p.team_memberships.count(), 1)
