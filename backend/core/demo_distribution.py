"""Muestreo DETERMINISTA sobre la distribución real de otro club.

El problema que resuelve: un club de demo generado con rangos inventados y
`random()` —que es lo que hace `seed_fake_exams`— produce datos que se ven
plausibles de a uno pero mienten en conjunto. Los percentiles no significan
nada, el radar sale como ruido, y dos corridas dan números distintos, así que
una captura de pantalla de ayer no se puede reproducir hoy.

Acá los valores salen de **remuestrear la distribución empírica real** del club
de origen. Tres propiedades, y las tres importan:

**1 · La distribución se conserva por construcción.** El valor de un jugador es
el cuantil `q` de los valores reales del club de origen para esa misma métrica
y categoría equivalente. Si el plantel demo recorre los cuantiles de forma
pareja, su histograma ES el del club de origen — no una aproximación.

**2 · Cero azar.** No hay PRNG. El cuantil de cada jugador sale de su identidad
(su posición dentro del plantel) por una fórmula fija. Dos corridas dan
exactamente los mismos números, y una demo grabada sigue siendo válida.

**3 · El jugador es coherente consigo mismo.** Cada uno lleva UN cuantil de
habilidad que usa en todas las métricas, desplazado un poco por métrica con un
offset también determinista. Sin esto, el mismo chico sale primero en sprint y
último en velocidad máxima: cada métrica sería un sorteo independiente, el
radar quedaría dentado y el comparador no contaría ninguna historia.

Y una cuarta, para las series históricas: el cuantil **deriva suavemente** con
el tiempo, así las curvas tienen tendencia en vez de saltar entre lecturas.

Módulo sin Django: es aritmética, se testea sin ORM.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left


def cuantil_de_jugador(indice: int, total: int) -> float:
    """El cuantil de habilidad de un jugador, en (0, 1).

    Reparte el plantel de forma pareja por el rango: con 24 jugadores salen
    0.02, 0.06, 0.10 … 0.98. Barrer el rango entero es lo que hace que el
    histograma del plantel demo coincida con el del club de origen; si en
    cambio se sorteara, con 24 muestras la cola quedaría vacía la mitad de las
    veces.

    Se evitan 0 y 1 exactos: son el mínimo y el máximo absolutos del club de
    origen, y ponerle a alguien el récord histórico exacto se nota.
    """
    if total <= 0:
        return 0.5
    return (indice + 0.5) / total


def _offset(semilla: str, amplitud: float) -> float:
    """Desvío determinista en [-amplitud, +amplitud] a partir de un texto.

    Es el reemplazo del azar: mismo texto, mismo número, siempre. Se usa para
    que un jugador no caiga en el MISMO cuantil en todas las métricas —eso lo
    volvería un clon perfecto del percentil— sin romper su perfil general.
    """
    h = hashlib.sha256(semilla.encode()).digest()
    # 16 bits bastan y sobran para un desvío de dos decimales.
    crudo = int.from_bytes(h[:2], "big") / 65535.0      # [0, 1]
    return (crudo * 2 - 1) * amplitud                    # [-a, +a]


def cuantil_para(
    base: float,
    jugador_id: str,
    metrica: str,
    *,
    dispersion: float = 0.18,
    paso: int = 0,
    pasos: int = 1,
    deriva: float = 0.10,
    variacion: float = 0.22,
) -> float:
    """El cuantil final de (jugador, métrica, lectura N), en [0.01, 0.99].

    `base` es el cuantil de habilidad del jugador. `dispersion` es cuánto puede
    apartarse en una métrica puntual: 0.18 deja a un jugador del percentil 70
    entre el 52 y el 88 según la métrica — distinto en cada una, pero
    reconociblemente el mismo jugador.

    ⚠️ **La deriva se reparte sobre la serie ENTERA, no por lectura.** Antes
    era lineal en `paso`, y con GPS —una sesión cada tres días, ~60 lecturas en
    seis meses— acumulaba ±0,72 de cuantil: todos terminaban clavados contra
    0,01 y 0,99, y la distribución generada salía mucho más ancha que la real
    (p90 de 11.281 m contra 7.394 reales). Con seis lecturas mensuales el
    defecto no se veía. Ahora `deriva` es el recorrido TOTAL de punta a punta,
    así que la tendencia existe y la escala no se deforma.

    `variacion` es el vaivén entre lecturas: una sesión de MD-1 y una de MD+2
    no se parecen ni para el mismo jugador, y sin esto cada uno dibujaría una
    recta casi plana. Es determinista por lectura, no ruido.
    """
    q = base + _offset(f"{jugador_id}|{metrica}", dispersion)
    # Dirección determinista: la mitad de los jugadores progresa en una métrica
    # y la otra mitad retrocede.
    sentido = 1.0 if _offset(f"{jugador_id}|{metrica}|dir", 1.0) >= 0 else -1.0
    if pasos > 1:
        avance = paso / (pasos - 1) - 0.5          # [-0.5, +0.5]
        q += sentido * deriva * 2 * avance
    q += _offset(f"{jugador_id}|{metrica}|{paso}", variacion)
    return min(0.99, max(0.01, q))


def valor_en_cuantil(ordenados: list[float], q: float) -> float | None:
    """El valor del cuantil `q` en una muestra YA ORDENADA, interpolando.

    Interpola entre los dos vecinos en vez de tomar el más cercano: con
    muestras chicas —una categoría con 20 lecturas de un test— el redondeo
    haría que varios jugadores compartan valor exacto, y una tabla con cinco
    veces el mismo número se lee como un error de carga.
    """
    n = len(ordenados)
    if n == 0:
        return None
    if n == 1:
        return ordenados[0]
    pos = q * (n - 1)
    bajo = int(pos)
    alto = min(bajo + 1, n - 1)
    frac = pos - bajo
    return ordenados[bajo] * (1 - frac) + ordenados[alto] * frac


class Distribucion:
    """La muestra real de una métrica, lista para remuestrear."""

    __slots__ = ("valores", "decimales")

    def __init__(self, valores: list[float]):
        self.valores = sorted(v for v in valores if v is not None)
        # Se copia la precisión que usa el club de origen: si sus tiempos van
        # con dos decimales y el demo saliera con seis, la tabla delataría que
        # el dato es sintético antes de que nadie mire los números.
        self.decimales = _decimales_tipicos(self.valores)

    def __len__(self) -> int:
        return len(self.valores)

    def muestrear(self, q: float) -> float | None:
        v = valor_en_cuantil(self.valores, q)
        return None if v is None else round(v, self.decimales)


def _decimales_tipicos(valores: list[float]) -> int:
    """Cuántos decimales usa la mayoría de la muestra (tope 2)."""
    if not valores:
        return 2
    cuantos = 0
    for v in valores[: min(len(valores), 50)]:
        texto = f"{v:.6f}".rstrip("0")
        dec = len(texto.split(".")[1]) if "." in texto else 0
        cuantos = max(cuantos, min(dec, 2))
    return cuantos


def indice_estable(clave: str, largo: int) -> int:
    """Índice determinista en `[0, largo)` a partir de un texto.

    Para elegir nombre, posición o plantilla sin sortear: el mismo jugador
    recibe siempre lo mismo, corrida tras corrida.
    """
    if largo <= 0:
        return 0
    h = hashlib.sha256(clave.encode()).digest()
    return int.from_bytes(h[:4], "big") % largo


def buscar_percentil(ordenados: list[float], valor: float) -> float:
    """Percentil de `valor` dentro de una muestra ordenada, en [0, 1].

    Inverso de `valor_en_cuantil`; sirve para verificar que lo generado cae
    donde se pretendía.
    """
    if not ordenados:
        return 0.5
    i = bisect_left(ordenados, valor)
    return i / max(1, len(ordenados) - 1)
