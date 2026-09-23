"""Comparador de jugadores entre divisiones.

Responde la pregunta de proyección del club: *¿este Sub 17 ya rinde como un
jugador de Primer Equipo en su puesto?* Para eso cruza N jugadores de CUALQUIER
categoría sobre las mismas métricas, y agrega la media de la línea en el plantel
profesional como vara de medir.

Tres decisiones que vale la pena dejar escritas.

**La referencia es por LÍNEA, no por posición.** Primer Equipo y el formativo
usaban vocabularios distintos: cruzar por nombre exacto dejaba 154 de 354
juveniles sin contraparte —todos los laterales— y donde sí cruzaba, la media
salía de 1 a 3 jugadores. `Position.role` normalizado (ver
`core.positions.CANON`) da cuatro líneas donde el 100% queda cubierto y la
muestra profesional es Defensa 10 · Mediocampo 10 · Ataque 8 · Arquero 2.

**La `n` viaja con la media, siempre.** Arqueros son dos. Una media de dos
jugadores no se puede presentar igual que una de diez, y quien dibuje esto
tiene que poder decirlo.

**Las series salen crudas, con su fecha, más la fecha de nacimiento.** El eje lo
elige el consumidor: días desde el primer registro de cada uno (comparar
*formas* sin forzar que las fechas calcen) o edad del jugador (comparar a *la
misma edad*, que es la pregunta de proyección). Resolver el eje acá obligaría a
volver al servidor para cambiar de vista, y son los mismos datos.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from core.models import Player
from dashboards import category_bands
from dashboards.models import field_lookup
from exams.bands import band_for_value
from exams.models import ExamResult, ExamTemplate

# Tope de jugadores. No es una limitación técnica: seis series en un gráfico ya
# son más de las que un ojo separa, y el selector es la superficie donde eso se
# acota.
MAX_PLAYERS = 6

# Mínimo de compañeros con el dato para que un percentil signifique algo.
# Mismo criterio que `references.squad_percentile`: por debajo de esto el
# número existe pero no informa, y dibujarlo da una precisión que no hay.
_MIN_N = 3

# Las métricas NO tienen tope. Lo tenían mientras el payload cargaba la serie
# completa de todas: 6 jugadores × 12 métricas eran 240 KB, y con las 238 que
# ofrece el selector habrían sido ~4,7 MB. Ahora la serie viaja sólo para las
# métricas que el gráfico va a dibujar (`series_for`), y el resto manda nada
# más que su último valor — que es todo lo que la tabla y las tarjetas usan.
# Con eso el costo por métrica extra es una línea de JSON, no una serie.


def metric_key(template_slug: str, field_key: str) -> str:
    return f"{template_slug}:{field_key}"


def _nombre(p: Player) -> str:
    return " ".join(x for x in (p.first_name, p.last_name) if x).strip()


def compare(
    players: list[Player],
    metrics: list[tuple[ExamTemplate, str]],
    *,
    club_id: UUID,
    series_for: frozenset[str] | None = None,
    con_percentiles: bool = False,
    date_from=None,
    date_to=None,
) -> dict[str, Any]:
    """Payload del comparador. Ver el docstring del módulo para el porqué.

    `series_for`: las claves de métrica que necesitan su serie completa. El
    resto viaja sólo con el último valor. `None` = todas, que es lo que quieren
    los tests y cualquier consumidor que no sepa de esto.
    """
    meta = _metric_meta(metrics)
    keys = [m["key"] for m in meta]
    con_serie = set(keys) if series_for is None else set(series_for)

    # Los profesionales de las líneas involucradas entran a la MISMA consulta
    # que los jugadores pedidos: la referencia es un promedio de últimos
    # valores, no una agregación aparte.
    lineas = {p.position.role for p in players if p.position and p.position.role}
    profesionales = list(
        Player.objects.filter(
            category__club_id=club_id, category__is_senior=True, is_active=True,
            position__role__in=lineas or [""],
        ).select_related("position")
    ) if lineas else []

    # La ventana aplica a TODO —series, últimos valores, referencia y
    # percentiles— y no sólo a los gráficos: si la tarjeta mostrara el último
    # valor histórico mientras la curva muestra los últimos 6 meses, las dos
    # superficies hablarían de momentos distintos sin decirlo.
    series = _series(
        [*players, *profesionales], metrics, date_from, date_to,
    )

    jugadores_payload = [
        {
            "id": str(p.id),
            "name": _nombre(p),
            "category": p.category.name if p.category_id else None,
            "position": p.position.name if p.position_id else None,
            "line": p.position.role or None if p.position_id else None,
            # Vacío en TODO el formativo hoy (0 de 445). Quien dibuje la
            # tarjeta necesita un fallback de verdad, no un ícono roto.
            "photo_url": p.photo_url or None,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "values": {
                k: _ultimo(series.get((p.id, k)) or []) for k in keys
            },
            "series": {
                k: (series.get((p.id, k)) or []) if k in con_serie else []
                for k in keys
            },
        }
        for p in players
    ]

    bandas = _bandas_por_jugador(players, metrics, meta)
    for payload_p, p in zip(jugadores_payload, players):
        propias = bandas.get(p.id, {})
        payload_p["bands"] = {k: propias.get(k, []) for k in keys}
        payload_p["band_labels"] = {
            k: _etiqueta_banda((payload_p["values"] or {}).get(k), propias.get(k))
            for k in keys
        }

    # El fallback era de uso interno; no tiene por qué viajar.
    meta_publico = [{k: v for k, v in m.items() if not k.startswith("_")}
                    for m in meta]

    salida = {
        "metrics": meta_publico,
        "players": jugadores_payload,
        "benchmark": _benchmark(profesionales, keys, series),
    }
    if con_percentiles:
        # Opt-in: son una consulta por (familia, categoría) y sólo los usa el
        # radar. La tabla y las tarjetas leen valores, no rangos.
        salida["percentiles"] = percentiles(
            players, metrics, {m["key"]: m for m in meta}, date_from, date_to)
    return salida


def _metric_meta(metrics: list[tuple[ExamTemplate, str]]) -> list[dict[str, Any]]:
    out = []
    for template, field_key in metrics:
        field = field_lookup(template, field_key) or {}
        out.append({
            "key": metric_key(template.slug, field_key),
            "field_key": field_key,
            "template": template.slug,
            "template_label": template.name,
            "label": field.get("label", field_key),
            "unit": field.get("unit", ""),
            "direction_of_good": field.get("direction_of_good", "neutral"),
            # Fallback del campo. Las bandas que se muestran salen de la
            # categoría de CADA jugador (ver `_bandas_por_jugador`); esto es lo
            # que se usa cuando su categoría no tiene las suyas.
            "_fallback_ranges": field.get("reference_ranges") or [],
        })
    return out


def _series(
    players: list[Player], metrics: list[tuple[ExamTemplate, str]],
    date_from=None, date_to=None,
) -> dict[tuple[UUID, str], list[dict[str, Any]]]:
    """`(player_id, metric_key)` → puntos ordenados por fecha.

    Una sola consulta para todos los jugadores y todas las plantillas: el
    comparador puede pedir 6 jugadores × 12 métricas, y una consulta por celda
    serían 72 viajes a la base para dibujar una pantalla.
    """
    por_familia: dict[Any, list[tuple[str, str]]] = defaultdict(list)
    for template, field_key in metrics:
        por_familia[template.family_id].append(
            (field_key, metric_key(template.slug, field_key)))

    out: dict[tuple[UUID, str], list[dict[str, Any]]] = defaultdict(list)
    if not por_familia or not players:
        return out

    filas = (
        ExamResult.objects
        .filter(template__family_id__in=por_familia.keys(),
                player_id__in=[p.id for p in players])
        .values("player_id", "recorded_at", "result_data", "template__family_id")
        .order_by("recorded_at")
    )
    if date_from is not None:
        filas = filas.filter(recorded_at__gte=date_from)
    if date_to is not None:
        filas = filas.filter(recorded_at__lte=date_to)
    for fila in filas:
        for field_key, mkey in por_familia.get(fila["template__family_id"], []):
            crudo = (fila["result_data"] or {}).get(field_key)
            valor = _num(crudo)
            if valor is None:
                continue
            out[(fila["player_id"], mkey)].append({
                "recorded_at": fila["recorded_at"].isoformat(),
                "value": valor,
            })
    return out


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ultimo(puntos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """El último punto CON valor. `None` se distingue de 0 aguas arriba."""
    return puntos[-1] if puntos else None


def _benchmark(
    profesionales: list[Player],
    keys: list[str],
    series: dict[tuple[UUID, str], list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Media del último valor de cada profesional, por línea y métrica.

    Se promedian ÚLTIMOS VALORES y no todas las lecturas: la vara es "cómo está
    hoy el plantel profesional", no "cómo estuvo históricamente". Un jugador con
    200 mediciones no puede pesar 200 veces más que uno con una.
    """
    por_linea: dict[str, list[Player]] = defaultdict(list)
    for p in profesionales:
        if p.position and p.position.role:
            por_linea[p.position.role].append(p)

    out: dict[str, dict[str, Any]] = {}
    for linea, miembros in por_linea.items():
        metricas: dict[str, Any] = {}
        for k in keys:
            valores = [
                u["value"] for u in
                (_ultimo(series.get((p.id, k)) or []) for p in miembros)
                if u is not None
            ]
            metricas[k] = (
                {"mean": round(sum(valores) / len(valores), 2), "n": len(valores)}
                if valores else {"mean": None, "n": 0}
            )
        out[linea] = {
            # `n` de la línea vs `n` por métrica: no son lo mismo. Diez
            # profesionales en Defensa, pero quizá sólo tres tienen CMJ.
            "line_size": len(miembros),
            "metrics": metricas,
        }
    return out


# ─── Percentiles para el radar ───────────────────────────────────────


def percentiles(
    players: list[Player],
    metrics: list[tuple[ExamTemplate, str]],
    meta_por_clave: dict[str, dict[str, Any]],
    date_from=None,
    date_to=None,
) -> dict[str, dict[str, Any]]:
    """`player_id` → `metric_key` → `{pct, n, value}`, dentro de SU categoría.

    Por qué percentil y no el valor crudo: el radar pone en un mismo dibujo
    km/h, kg, segundos y centímetros, que no comparten escala. Y entre
    divisiones el valor crudo sólo diría la edad — un Sub 13 contra un Sub 20
    saldría aplastado. El percentil contra los PROPIOS pares contesta la
    pregunta que importa: quién está mejor parado en su grupo.

    ⚠️ **La dirección se corrige acá y es lo más delicado de este módulo.**
    El ranking natural es "cuántos valores son ≤ al tuyo". En T10 y COD 505
    menos es mejor, así que un jugador rápido saldría con percentil bajo y el
    radar lo dibujaría como el peor del plantel — un error que nadie detecta
    porque el gráfico se ve perfectamente normal. Con `direction_of_good ==
    "down"` el percentil se invierte, de modo que en el radar **más lejos del
    centro es siempre mejor**, en todos los ejes.

    `pct` es `None` cuando hay menos de `_MIN_N` compañeros con el dato: un
    percentil sobre dos personas no es un percentil, y dibujarlo igual sería
    inventar precisión.
    """
    from collections import defaultdict as _dd

    # Una consulta por (familia, categoría) en vez de una por celda.
    por_categoria: dict[Any, list[Player]] = _dd(list)
    for p in players:
        if p.category_id:
            por_categoria[p.category_id].append(p)

    out: dict[str, dict[str, Any]] = {str(p.id): {} for p in players}

    for cat_id, jugadores in por_categoria.items():
        for template, field_key in metrics:
            clave = metric_key(template.slug, field_key)
            direccion = (meta_por_clave.get(clave) or {}).get("direction_of_good")
            # La regla tiene que ser EXACTAMENTE la de la tarjeta: la última
            # lectura con VALOR NUMÉRICO en este campo. Un `distinct` sobre la
            # última fila no sirve —puede traer el campo ausente o en null— y
            # el radar decía "sin dato" para un jugador cuya tarjeta mostraba
            # 1.78. Dos superficies que leen el mismo dato y muestran distinto
            # es peor que cualquiera de las dos sola.
            #
            # De ahí el recorrido: filas ordenadas por jugador y fecha
            # descendente, y para cada uno la primera que coerciona a número.
            filas = (
                ExamResult.objects
                .filter(template__family_id=template.family_id,
                        player__category_id=cat_id,
                        result_data__has_key=field_key)
                .order_by("player_id", "-recorded_at")
                .values_list("player_id", "result_data")
            )
            # El universo del percentil también se acota: comparar contra el
            # plantel "de siempre" mientras el jugador se mide en los últimos
            # 6 meses mezclaría dos poblaciones distintas.
            if date_from is not None:
                filas = filas.filter(recorded_at__gte=date_from)
            if date_to is not None:
                filas = filas.filter(recorded_at__lte=date_to)
            valores: dict[Any, float] = {}
            for pid, data in filas:
                if pid in valores:
                    continue        # ya tomamos su lectura más reciente válida
                v = _num((data or {}).get(field_key))
                if v is not None:
                    valores[pid] = v
            universo = list(valores.values())
            for p in jugadores:
                propio = valores.get(p.id)
                if propio is None:
                    out[str(p.id)][clave] = {"pct": None, "n": len(universo),
                                             "value": None}
                    continue
                if len(universo) < _MIN_N:
                    out[str(p.id)][clave] = {"pct": None, "n": len(universo),
                                             "value": propio}
                    continue
                debajo = sum(1 for v in universo if v <= propio)
                pct = round(debajo / len(universo) * 100)
                if direccion == "down":
                    pct = 100 - pct
                out[str(p.id)][clave] = {"pct": pct, "n": len(universo),
                                         "value": propio}
    return out


def _etiqueta_banda(ultimo, bandas) -> str | None:
    """Nombre de la banda en la que cae el último valor, o `None`."""
    if not ultimo or not bandas:
        return None
    banda = band_for_value(ultimo["value"], bandas)
    return (banda or {}).get("label") or None


def _bandas_por_jugador(
    players: list[Player],
    metrics: list[tuple[ExamTemplate, str]],
    meta: list[dict[str, Any]],
) -> dict[Any, dict[str, list[dict]]]:
    """`player_id` → `metric_key` → las bandas de SU categoría.

    Por categoría y no una sola tabla compartida: es la razón de existir de las
    bandas por categoría — 41,89 cm de CMJ es "Bueno" en Sub 20 y otra cosa en
    Sub 13. Clasificar a los dos contra la misma escala sería exactamente el
    error que ese trabajo vino a corregir, y encima invisible: la etiqueta se
    vería perfectamente normal.
    """
    fallback = {m["key"]: m.get("_fallback_ranges") or [] for m in meta}
    por_categoria: dict[Any, list[Player]] = {}
    for p in players:
        por_categoria.setdefault(p.category_id, []).append(p)

    out: dict[Any, dict[str, list[dict]]] = {}
    for cat_id, jugadores in por_categoria.items():
        mapa = category_bands.build(cat_id) if cat_id else {}
        resuelto: dict[str, list[dict]] = {}
        for template, field_key in metrics:
            clave = metric_key(template.slug, field_key)
            propio = mapa.get(
                (template.family_id or template.id, field_key))
            resuelto[clave] = list(propio or fallback.get(clave) or [])
        for p in jugadores:
            out[p.id] = resuelto
    return out
