"""The Formativo master builder must read the same ladder as `core.Bracket`.

`backend/scripts/build_formativo_master.py` is standalone — it parses the
club's workbooks without Django, so it carries its own `ANFP_LADDER` constant.
That is a second copy of reference data, and the whole reason the script exists
is that the club's own spreadsheet derived brackets with arithmetic
(`season - cohort`) and invented Sub 17, Sub 19 and Sub 21 in the process.

If the two copies drift, the CSV that seeds phase 2 files players under rungs
the app does not have, and nothing fails loudly: the numbers just come out
wrong for one cohort. So the constant is pinned here rather than trusted.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from django.test import TestCase

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_formativo_master.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("build_formativo_master", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LadderParityTests(TestCase):
    """Compares the script's constant against `backfill_cohorts.BRACKETS`.

    An earlier version of this file built its own brackets in `setUpTestData`,
    which made the parity check vacuous — it compared the script's constant to
    rungs the test had just invented, so the two could drift from the app
    together and still pass. `BRACKETS` is where the app declares the ladder,
    so that is the thing to pin to.
    """

    @classmethod
    def setUpTestData(cls):
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.create(code=code, name=name, age=age, order=order)

    def setUp(self):
        self.script = _load_script()

    def test_el_script_declara_la_misma_escalera_que_la_app(self):
        de_la_app = tuple(age for _, _, age in BRACKETS if age is not None)
        self.assertEqual(
            self.script.ANFP_LADDER, de_la_app,
            "ANFP_LADDER quedó desincronizada de backfill_cohorts.BRACKETS — "
            "el CSV de la fase 1 asignaría jugadores a peldaños que la app no "
            "tiene, y nada falla: sólo salen mal los números de una cohorte",
        )

    def test_la_escalera_conserva_los_huecos_de_la_ANFP(self):
        # Fija el valor esperado: el test de paridad pasaría igual si las dos
        # declaraciones cambiaran juntas a una escalera sin huecos.
        self.assertEqual(self.script.ANFP_LADDER, (11, 12, 13, 14, 15, 16, 18, 20))
        self.assertTrue(Bracket.objects.filter(age__isnull=True).exists(),
                        "falta el peldaño senior: for_age no tendría dónde caer")

    def test_cada_edad_cae_en_el_mismo_peldano_que_Bracket_for_age(self):
        """Recorre todas las edades del rango juvenil, no una muestra.

        Los huecos son exactamente donde una implementación paralela se
        equivoca: 17 → Sub 18 y 19 → Sub 20 son los dos casos que la
        aritmética del club erraba.

        Desde 11 para arriba, porque abajo las dos funciones responden
        preguntas distintas — ver el test siguiente.
        """
        ladder = Bracket.ladder()
        for age in range(11, 24):
            esperado = Bracket.for_age(age, ladder)
            obtenido = self.script.bracket_for_age(age)
            if esperado.is_senior:
                self.assertEqual(obtenido, self.script.ABOVE_LADDER, f"edad {age}")
            else:
                self.assertEqual(obtenido, esperado.age, f"edad {age}")

    def test_bajo_Sub_11_las_dos_funciones_difieren_a_proposito(self):
        """`Bracket.for_age` da un TECHO; el script da la serie que se juega.

        Un niño de 8 años *puede* ser inscrito en Sub 11, y por eso
        `Bracket.for_age(8)` devuelve Sub 11: pregunta "¿cuál es el peldaño más
        bajo que lo admite?".

        El maestro del formativo pregunta otra cosa: "¿qué compite esta cohorte
        esta temporada?". El club tiene 52 jugadores en tres grupos internos
        (U8, U9, U10) que la ANFP no organiza, y meterlos todos en Sub 11
        fusionaría tres series distintas en una. `Category.season_label_parts()`
        ya modela esto: para una cohorte bajo el peldaño más bajo devuelve
        "Serie 2018" sin sufijo Sub.

        Se fija acá para que la diferencia sea una decisión y no una sorpresa.
        """
        ladder = Bracket.ladder()
        for age in (8, 9, 10):
            techo = Bracket.for_age(age, ladder)
            self.assertEqual(techo.age, 11, f"edad {age}: el techo sigue siendo Sub 11")
            self.assertEqual(self.script.bracket_for_age(age), self.script.BELOW_LADDER)

    def test_los_huecos_de_la_escalera(self):
        # El guard de arriba pasaría igual si las dos implementaciones
        # estuvieran mal de la misma forma. Acá se fija el valor esperado.
        self.assertEqual(self.script.bracket_for_age(17), 18)
        self.assertEqual(self.script.bracket_for_age(19), 20)
        self.assertEqual(self.script.bracket_for_age(16), 16)
        self.assertEqual(self.script.bracket_for_age(10), self.script.BELOW_LADDER)
        self.assertEqual(self.script.bracket_for_age(21), self.script.ABOVE_LADDER)


class EvidenciaDeSesionTests(TestCase):
    def setUp(self):
        self.script = _load_script()

    def test_una_etiqueta_de_sesion_se_lee_contra_su_propia_temporada(self):
        """`U13` en 2024 y `U13` en 2026 describen cohortes distintas.

        Votar la etiqueta cruda archivaba al jugador en el bracket que jugó
        hace dos años: 122 de 430 jugadores salían mal por esto.
        """
        self.assertEqual(self.script.implied_cohort(13, 2024), 2011)
        self.assertEqual(self.script.implied_cohort(13, 2026), 2013)

    def test_U21_es_Sub_20(self):
        # El club dice Sub 20; sus planillas dicen U21 para el mismo plantel.
        self.assertEqual(self.script.bracket_norm("U21"), 20)
        self.assertEqual(self.script.bracket_norm("U20"), 20)
        self.assertIsNone(self.script.bracket_norm("SPARRING"))
        self.assertIsNone(self.script.bracket_norm("#N/A"))
