"""Conclusión en prosa de una comparación entre jugadores.

La tabla y los gráficos ya dicen QUÉ pasa. Esto dice qué IMPORTA: dos o tres
frases que señalan dónde está la diferencia real, dónde está cada uno respecto
de la vara del plantel profesional, y qué conviene mirar.

Sigue las mismas restricciones que `pdf/narrative.py`, por las mismas razones:

- **Sólo con el dato entregado.** Se le prohíbe inventar métricas, fechas o
  juicios médicos. La tabla de arriba sigue siendo la fuente de verdad.
- **Nunca bloquea la pantalla.** Sin API key, con un error de red, con una
  respuesta rara: devuelve `None` y la comparación se dibuja igual. Por eso
  además vive en su propio endpoint — la comparación no espera al modelo.
- **Cacheada por contenido.** La clave es el hash de la entrada, así que
  mirar la misma comparación dos veces no se cobra dos veces. Dos usuarios
  comparando los mismos jugadores comparten la conclusión.

⚠️ **Lo que NO se le manda: las series completas.** Una comparación puede
llevar miles de puntos, y mandarlos sería caro y peor: el modelo se pierde en
el ruido. Se le da el último valor, la referencia con su `n`, y una tendencia
resumida (primer vs último, % de cambio) — que es de lo que se puede concluir
algo.

Una sola llamada a `messages.create`, sin streaming (la salida es un párrafo).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Techo de salida: cubre el pensamiento adaptativo más un párrafo corto. Es un
# tope, no un gasto — la conclusión pedida son 2-4 frases.
_MAX_TOKENS = 4000

# Una semana. La entrada ya está en la clave, así que el único motivo para
# expirar es que cambie el prompt de acá; el `_PROMPT_VERSION` cubre eso.
_TTL = 60 * 60 * 24 * 7
_PROMPT_VERSION = "v1"

_SYSTEM = (
    "Eres un analista de ciencias del deporte de un club de fútbol. "
    "Escribís para el cuerpo técnico, en español de Chile, en tono directo "
    "y sin adornos.\n\n"
    "Te entregan una comparación entre jugadores de distintas divisiones: "
    "para cada métrica, el último valor de cada uno, su tendencia reciente, y "
    "cuando existe, la media de esa métrica en la misma línea del plantel "
    "profesional.\n\n"
    "Escribí una conclusión de 2 a 4 frases. Reglas estrictas:\n"
    "1. Usá SOLO los datos entregados. No inventes métricas, fechas, "
    "posiciones ni lesiones.\n"
    "2. Señalá dónde está la diferencia que importa, no todas las "
    "diferencias. Si dos valores son casi iguales, decí que están parejos.\n"
    "3. Cuando cites la referencia profesional, mencioná de cuántos jugadores "
    "sale si son menos de cinco — una media de dos no es una vara firme.\n"
    "4. Ojo con la dirección: en algunas métricas es mejor un valor más bajo "
    "(viene indicado en `mejor_es`). No asumas que más es mejor.\n"
    "5. No emitas diagnósticos médicos ni recomendaciones de carga. Describí "
    "lo que el dato muestra y, como mucho, qué conviene mirar.\n"
    "6. Si los datos no alcanzan para concluir nada, decilo en una frase.\n\n"
    "Respondé sólo con el párrafo, sin título ni viñetas."
)


def _clave(payload: dict[str, Any]) -> str:
    crudo = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "cmp-insight:" + hashlib.sha256(
        f"{_PROMPT_VERSION}|{crudo}".encode()).hexdigest()


def _tendencia(serie: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Primer valor, último y % de cambio. Resume una serie de miles de puntos
    en lo único que aporta a una conclusión: hacia dónde va."""
    if len(serie) < 2:
        return None
    primero, ultimo = serie[0]["value"], serie[-1]["value"]
    if primero in (None, 0):
        return {"desde": primero, "hasta": ultimo, "cambio_pct": None,
                "lecturas": len(serie)}
    return {
        "desde": primero, "hasta": ultimo,
        "cambio_pct": round((ultimo - primero) / abs(primero) * 100, 1),
        "lecturas": len(serie),
    }


def compactar(comparacion: dict[str, Any]) -> dict[str, Any]:
    """La comparación, reducida a lo que el modelo necesita para concluir."""
    metricas = comparacion.get("metrics") or []
    jugadores = comparacion.get("players") or []
    benchmark = comparacion.get("benchmark") or {}

    filas = []
    for m in metricas:
        clave = m["key"]
        fila: dict[str, Any] = {
            "metrica": m.get("label") or clave,
            "unidad": m.get("unit") or "",
            "examen": m.get("template_label") or "",
            # El modelo no puede deducir la dirección del nombre: en T10 y COD
            # menos es mejor, en 1RM y CMJ más.
            "mejor_es": {"up": "mas alto", "down": "mas bajo"}.get(
                m.get("direction_of_good"), "sin direccion definida"),
            "jugadores": [],
        }
        for p in jugadores:
            ultimo = (p.get("values") or {}).get(clave)
            fila["jugadores"].append({
                "nombre": p.get("name"),
                "categoria": p.get("category"),
                "ultimo": ultimo.get("value") if ultimo else None,
                "fecha": (ultimo.get("recorded_at") or "")[:10] if ultimo else None,
                "tendencia": _tendencia((p.get("series") or {}).get(clave) or []),
            })
        lineas = {p.get("line") for p in jugadores}
        if len(lineas) == 1 and (linea := jugadores[0].get("line")):
            ref = ((benchmark.get(linea) or {}).get("metrics") or {}).get(clave)
            if ref and ref.get("mean") is not None:
                fila["referencia_primer_equipo"] = {
                    "linea": linea, "media": ref["mean"], "n": ref.get("n", 0),
                }
        filas.append(fila)

    return {
        "jugadores": [
            {"nombre": p.get("name"), "categoria": p.get("category"),
             "posicion": p.get("position"), "linea": p.get("line")}
            for p in jugadores
        ],
        "metricas": filas,
    }


def conclusion(comparacion: dict[str, Any]) -> str | None:
    """Párrafo de conclusión, o `None` si no se pudo (nunca levanta)."""
    compacto = compactar(comparacion)
    # Con un solo jugador también hay algo que concluir: dónde está respecto
    # de la vara de su línea.
    if not compacto["metricas"] or not compacto["jugadores"]:
        return None

    clave = _clave(compacto)
    try:
        if (cacheado := cache.get(clave)) is not None:
            return cacheado or None
    except Exception:  # noqa: BLE001 — sin caché se paga de nuevo, no se rompe
        logger.warning("Caché no disponible para la conclusión.", exc_info=True)

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("Sin ANTHROPIC_API_KEY: la comparación va sin conclusión.")
        return None

    modelo = getattr(settings, "COMPARISON_MODEL", "") or settings.ANTHROPIC_MODEL
    texto = _llamar(api_key, modelo, compacto)
    try:
        # Se cachea incluso el fallo (""), para no reintentar en bucle contra
        # una API caída cada vez que alguien abre la pantalla.
        cache.set(clave, texto or "", _TTL if texto else 300)
    except Exception:  # noqa: BLE001
        pass
    return texto


def _llamar(api_key: str, modelo: str, compacto: dict[str, Any]) -> str | None:
    try:
        import anthropic
    except ImportError:
        logger.warning("SDK anthropic no instalado; sin conclusión.")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=modelo,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            # El sistema es idéntico en todas las comparaciones: cachear el
            # prefijo lo vuelve casi gratis a partir de la segunda.
            system=[{
                "type": "text",
                "text": _SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": (
                    "Comparación (JSON):\n\n"
                    f"{json.dumps(compacto, ensure_ascii=False, indent=1)}\n\n"
                    "Escribí la conclusión."
                ),
            }],
        )
    except Exception:  # noqa: BLE001 — la conclusión es aditiva, nunca crítica
        logger.exception("Falló la conclusión de la comparación.")
        return None

    from dashboards.llm_usage import log_usage
    log_usage("comparison", modelo, response)

    partes = [
        getattr(b, "text", "") or ""
        for b in (getattr(response, "content", []) or [])
        if getattr(b, "type", None) == "text"
    ]
    return "".join(partes).strip() or None
