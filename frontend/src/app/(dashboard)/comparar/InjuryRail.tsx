"use client";

/**
 * Injury markers under a `/comparar` chart — several players on one axis.
 *
 * A hatched band per injury (as on the profile) would bury a two- or
 * three-player chart, and whose band is whose would hang on colour alone. So
 * here each injury is a MARKER on the x-axis: a dot and a thin bar in the
 * player's colour, and a short text — "Fernández · Esguince · Tobillo" — so the
 * owner is named, not just coloured.
 *
 * The x of an injury is computed per player with the SAME transform as his
 * curve (days since his first record of this metric, or his age), which is
 * the only way the marker lands under his own points.
 *
 * Positioned in HTML, not SVG: the chart's plot area has fixed margins here
 * (`PLOT_LEFT` / `PLOT_RIGHT` must match the `LineChart` margin + `YAxis`
 * width in `Evolucion`), so a percentage of the x-domain is exact, and HTML
 * gives real links, focus and wrapping labels.
 */

import Link from "next/link";
import React from "react";

import { type InjuryRange, describeInjury, markerLabel } from "@/lib/injuryRanges";

import styles from "./InjuryRail.module.css";

/** LineChart margin.left (8) + YAxis width (64). */
export const PLOT_LEFT = 72;
/** LineChart margin.right. */
export const PLOT_RIGHT = 64;
const LANES = 3;
/** A label needs about this share of the plot before the next can sit beside it. */
const LABEL_SHARE = 0.22;

export interface RailMarker {
  injury: InjuryRange;
  color: string;
  x1: number;
  /** null → open, runs to the domain's right edge. */
  x2: number | null;
}

export function InjuryRail({
  markers,
  domain,
}: {
  markers: RailMarker[];
  domain: [number, number] | undefined;
}) {
  if (!domain || markers.length === 0) return null;
  const [lo, hi] = domain;
  const span = hi - lo;
  if (!(span > 0)) return null;
  const pct = (x: number) => Math.min(100, Math.max(0, ((x - lo) / span) * 100));

  const visibles = markers
    .filter((m) => m.x1 <= hi && (m.x2 ?? hi) >= lo)
    .sort((a, b) => a.x1 - b.x1);
  if (visibles.length === 0) return null;

  // Greedy lanes: a marker goes to the first lane whose last label it clears.
  const finDeCarril: number[] = [];
  const colocados: { m: RailMarker; lane: number }[] = [];
  let ocultos = 0;
  for (const m of visibles) {
    const at = pct(m.x1) / 100;
    let lane = finDeCarril.findIndex((fin) => at >= fin);
    if (lane === -1 && finDeCarril.length < LANES) lane = finDeCarril.length;
    if (lane === -1) {
      ocultos += 1;
      continue;
    }
    finDeCarril[lane] = at + LABEL_SHARE;
    colocados.push({ m, lane });
  }
  const carriles = Math.max(1, finDeCarril.length);

  return (
    <div
      className={styles.rail}
      style={{ marginLeft: PLOT_LEFT, marginRight: PLOT_RIGHT, height: carriles * 30 + 6 }}
      aria-label={`${visibles.length} lesiones en el gráfico`}
      role="list"
    >
      {colocados.map(({ m, lane }) => {
        const left = pct(m.x1);
        const right = pct(m.x2 ?? hi);
        const texto = `${m.injury.player_name}: ${describeInjury(m.injury)}`;
        return (
          <div key={m.injury.id} role="listitem" className={styles.item}
            style={{ top: lane * 30 }}>
            <span className={`${styles.bar} ${m.x2 === null ? styles.open : ""}`}
              style={{ left: `${left}%`, width: `max(4px, ${right - left}%)`, background: m.color }}
              aria-hidden />
            <Link
              href={`/perfil/${m.injury.player_id}?tab=lesiones`}
              className={styles.marker}
              style={{ left: `${left}%`, color: m.color }}
              aria-label={`Lesión de ${texto}. Ver en Lesiones`}
              title={texto}
            >
              <span className={styles.dot} style={{ background: m.color }} aria-hidden />
              <span className={styles.label}>{markerLabel(m.injury)}</span>
            </Link>
          </div>
        );
      })}
      {ocultos > 0 && (
        <span className={styles.more} style={{ top: (carriles - 1) * 30 }}>
          +{ocultos} lesiones más
        </span>
      )}
    </div>
  );
}
