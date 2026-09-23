"use client";

/**
 * Las bandas del club, dibujadas como franjas horizontales detrás de las series.
 *
 * El backend ya las manda resueltas POR CATEGORÍA en cada `FieldMeta`
 * (`aggregation._field_meta` → `category_bands.for_field`), así que un Sub 15 ve
 * las suyas y un Sub 20 las suyas sin que el renderer se entere. Acá sólo se
 * pintan.
 *
 * ⚠️ La escala Y manda, no las bandas
 * -----------------------------------
 * Las franjas se CLAMPEAN al dominio que ya calculó `fullRangeDomain` sobre los
 * datos, y van con `ifOverflow="hidden"`. Es deliberado: si la banda pudiera
 * estirar el eje, un plantel entero apretado en "Bueno" se dibujaría aplastado
 * contra una escala que llega hasta "Elite", y la evolución real —que es lo que
 * el gráfico existe para mostrar— se volvería una línea plana. La banda es una
 * referencia visual; el dato es el protagonista.
 *
 * Una banda que cae entera fuera de lo visible simplemente no se dibuja.
 *
 * Se devuelve un array de elementos y no un componente que envuelva: Recharts
 * inspecciona sus children por tipo para decidir qué hacer con cada uno, y un
 * wrapper propio lo deja sin reconocer las `ReferenceArea`.
 */

import React from "react";
import { ReferenceArea } from "recharts";

import type { ReferenceBand } from "@/lib/types";

/** Gris neutro para una banda sin color propio. */
const SIN_COLOR = "#94a3b8";

/** Suave: la franja tiene que leerse sin competirle a la línea que va encima. */
const OPACIDAD = 0.14;

export function referenceBandAreas(
  bands: ReferenceBand[] | undefined,
  yDomain: [number, number] | undefined,
  opts: { yAxisId?: string | number; opacity?: number } = {},
): React.ReactElement[] {
  if (!bands || bands.length === 0 || !yDomain) return [];

  const [lo, hi] = yDomain;
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return [];

  const opacity = opts.opacity ?? OPACIDAD;
  const areas: React.ReactElement[] = [];

  bands.forEach((band, i) => {
    // Sin `min` / sin `max` = banda abierta: se extiende hasta el borde visible.
    const desde = typeof band.min === "number" ? band.min : lo;
    const hasta = typeof band.max === "number" ? band.max : hi;
    const y1 = Math.max(desde, lo);
    const y2 = Math.min(hasta, hi);
    if (!(y2 > y1)) return;

    areas.push(
      <ReferenceArea
        key={`band-${i}-${band.label}`}
        y1={y1}
        y2={y2}
        yAxisId={opts.yAxisId}
        fill={band.color || SIN_COLOR}
        fillOpacity={opacity}
        stroke="none"
        ifOverflow="hidden"
      />,
    );
  });

  return areas;
}
