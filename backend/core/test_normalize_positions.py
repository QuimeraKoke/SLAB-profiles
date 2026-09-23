"""Guards de `normalize_positions`.

El riesgo de este comando no es que escriba mal una `role` —eso se ve a simple
vista en el reporte— sino que toque algo que no le corresponde. Cinco de las
veinte posiciones de la U. de Chile no tienen NINGÚN jugador pero sostienen 228
fichas de partido vía `EventParticipant.position_played`; una limpieza que se
llevara puestas las filas "vacías" borraría esa historia sin que nadie lo note
hasta buscarla. Por eso los tests se concentran en lo que NO tiene que pasar.
"""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.management.commands.normalize_positions import CANON
from core.models import Club, Category, Player, Position


def correr(**kwargs) -> str:
    out = StringIO()
    call_command("normalize_positions", stdout=out, **kwargs)
    return out.getvalue()


class NormalizePositionsTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.cat = Category.objects.create(club=self.club, name="A")
        # `role` arranca con el uso viejo (granularidad), que es lo que hay en prod.
        self.dc = Position.objects.create(
            club=self.club, abbreviation="DC", name="Defensa central",
            role="Específica", sort_order=0)
        self.mc = Position.objects.create(
            club=self.club, abbreviation="MC", name="Mediocampista",
            role="", sort_order=2)

    def test_escribe_la_linea_y_el_orden(self):
        correr(commit=True)
        self.dc.refresh_from_db()
        self.mc.refresh_from_db()
        self.assertEqual(self.dc.role, "Defensa")
        self.assertEqual(self.mc.role, "Mediocampo")
        self.assertEqual(self.dc.sort_order, CANON["DC"][1])
        self.assertLess(self.dc.sort_order, self.mc.sort_order,
                        "la defensa va antes que el mediocampo")

    def test_sin_commit_no_escribe(self):
        correr()
        self.dc.refresh_from_db()
        self.assertEqual(self.dc.role, "Específica")

    def test_no_borra_posiciones_ni_mueve_jugadores(self):
        # La posición sin jugadores es justamente la que hay que NO borrar:
        # en prod son las que sostienen las fichas de partido viejas.
        huerfana = Position.objects.create(
            club=self.club, abbreviation="VD", name="Volante derecho",
            role="Específica", sort_order=0)
        jugador = Player.objects.create(
            category=self.cat, first_name="A", last_name="B", position=self.dc)

        correr(commit=True)

        self.assertTrue(Position.objects.filter(pk=huerfana.pk).exists())
        self.assertEqual(Position.objects.filter(club=self.club).count(), 3)
        jugador.refresh_from_db()
        self.assertEqual(jugador.position_id, self.dc.id,
                         "nadie cambia de posición")

    def test_una_posicion_fuera_del_mapa_se_reporta_y_queda_intacta(self):
        rara = Position.objects.create(
            club=self.club, abbreviation="XYZ", name="Inventada",
            role="loquesea", sort_order=7)
        salida = correr(commit=True)
        rara.refresh_from_db()
        self.assertEqual(rara.role, "loquesea")
        self.assertEqual(rara.sort_order, 7)
        self.assertIn("XYZ", salida)
        self.assertIn("Sin entrada en CANON", salida)

    def test_contrasta_contra_la_secundaria_que_ya_cargo_el_club(self):
        # `secondary_position` venía usándose como la línea; si discrepa del
        # mapa, o el mapa está mal o el dato está mal — en los dos casos hay
        # que mirarlo, no resolverlo por nosotros.
        delantero = Position.objects.create(
            club=self.club, abbreviation="DEL", name="Delantero",
            role="", sort_order=3)
        Player.objects.create(
            category=self.cat, first_name="Coincide", last_name="X",
            position=self.dc, secondary_position=self.dc)
        Player.objects.create(
            category=self.cat, first_name="Discrepa", last_name="Y",
            position=self.dc, secondary_position=delantero)

        salida = correr(commit=True)
        self.assertIn("1 de 2 coinciden", salida)
        self.assertIn("Discrepa", salida)
        self.assertNotIn("Coincide", salida)

    def test_es_idempotente(self):
        correr(commit=True)
        segunda = correr(commit=True)
        self.assertIn("0 posición(es) actualizada(s)", segunda)
