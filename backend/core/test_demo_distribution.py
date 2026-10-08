"""Guards del muestreo determinista para el club de demo.

Las tres propiedades que este módulo promete son fáciles de romper sin que se
note: un dato sintético se ve plausible de a uno aunque mienta en conjunto.
Cada test de acá corresponde a un defecto que efectivamente apareció mientras
se construía el seed.
"""
from __future__ import annotations

import statistics as st
from unittest import TestCase

from core.demo_distribution import (
    Distribucion, buscar_percentil, cuantil_de_jugador, cuantil_para,
    indice_estable, valor_en_cuantil,
)


class CuantilDeJugadorTests(TestCase):
    def test_barre_el_rango_completo(self):
        # Que el plantel recorra el rango entero es lo que hace que su
        # histograma coincida con el del club de origen. Sorteando, con 24
        # muestras las colas quedarían vacías la mitad de las veces.
        qs = [cuantil_de_jugador(i, 24) for i in range(24)]
        self.assertAlmostEqual(min(qs), 0.5 / 24)
        self.assertAlmostEqual(max(qs), 23.5 / 24)
        self.assertEqual(qs, sorted(qs))

    def test_nunca_toca_los_extremos(self):
        # 0 y 1 exactos son el mínimo y el máximo históricos del club real;
        # asignarle a alguien el récord exacto se nota.
        for n in (1, 5, 24, 100):
            for i in range(n):
                q = cuantil_de_jugador(i, n)
                self.assertGreater(q, 0.0)
                self.assertLess(q, 1.0)


class ValorEnCuantilTests(TestCase):
    def test_interpola_en_vez_de_redondear(self):
        # Sin interpolar, varios jugadores comparten valor exacto y una tabla
        # con cinco veces el mismo número se lee como error de carga.
        muestra = [10.0, 20.0, 30.0]
        self.assertEqual(valor_en_cuantil(muestra, 0.25), 15.0)
        self.assertEqual(valor_en_cuantil(muestra, 0.5), 20.0)

    def test_muestra_vacia_devuelve_None(self):
        self.assertIsNone(valor_en_cuantil([], 0.5))


class DeterminismoTests(TestCase):
    def test_mismo_insumo_mismo_numero(self):
        a = cuantil_para(0.4, "Sub 15|3", "t10_1", paso=2, pasos=10)
        b = cuantil_para(0.4, "Sub 15|3", "t10_1", paso=2, pasos=10)
        self.assertEqual(a, b)

    def test_cambia_con_el_jugador_y_con_la_metrica(self):
        base = dict(paso=0, pasos=10)
        self.assertNotEqual(
            cuantil_para(0.4, "Sub 15|3", "t10_1", **base),
            cuantil_para(0.4, "Sub 15|4", "t10_1", **base))
        self.assertNotEqual(
            cuantil_para(0.4, "Sub 15|3", "t10_1", **base),
            cuantil_para(0.4, "Sub 15|3", "cmj_1", **base))

    def test_indice_estable_es_estable(self):
        self.assertEqual(indice_estable("Sub 14|7|n", 32),
                         indice_estable("Sub 14|7|n", 32))


class DerivaAcotadaTests(TestCase):
    """El defecto que deformó la escala del GPS."""

    def test_una_serie_larga_no_clava_a_todos_contra_los_topes(self):
        # Con la deriva lineal por lectura, 60 sesiones acumulaban ±0,72 de
        # cuantil: todos terminaban en 0,01 o 0,99 y la distribución generada
        # salía mucho más ancha que la real (p90 de 11.281 m contra 7.394).
        qs = [cuantil_para(0.5, "Sub 20|5", "tot_dist", paso=p, pasos=60)
              for p in range(60)]
        pegados = sum(1 for q in qs if q <= 0.02 or q >= 0.98)
        self.assertLess(pegados, len(qs) * 0.25,
                        "la serie no puede vivir contra los topes")

    def test_la_serie_se_mueve_pero_no_se_dispara(self):
        qs = [cuantil_para(0.5, "Sub 20|5", "tot_dist", paso=p, pasos=60)
              for p in range(60)]
        self.assertGreater(st.pstdev(qs), 0.03, "una recta plana no es una serie")
        self.assertLess(max(qs) - min(qs), 0.85, "tampoco puede barrer todo")


class DistribucionTests(TestCase):
    def test_el_remuestreo_conserva_la_forma(self):
        # La propiedad central: el histograma del plantel demo tiene que ser
        # el del club de origen, no parecerse.
        origen = [float(x) for x in range(100)]
        d = Distribucion(origen)
        generado = [d.muestrear(cuantil_de_jugador(i, 24)) for i in range(24)]
        self.assertAlmostEqual(st.median(generado), st.median(origen), delta=2.0)
        self.assertAlmostEqual(min(generado), min(origen), delta=3.0)
        self.assertAlmostEqual(max(generado), max(origen), delta=3.0)

    def test_copia_la_precision_del_origen(self):
        # Tiempos del club con dos decimales y la demo con seis delataría el
        # dato sintético antes de que nadie mire los números.
        self.assertEqual(Distribucion([1.65, 1.72, 1.80]).decimales, 2)
        self.assertEqual(Distribucion([53.0, 61.0, 70.0]).decimales, 0)

    def test_percentil_es_el_inverso_del_muestreo(self):
        d = Distribucion([float(x) for x in range(100)])
        for q in (0.1, 0.5, 0.9):
            v = d.muestrear(q)
            self.assertAlmostEqual(buscar_percentil(d.valores, v), q, delta=0.05)
