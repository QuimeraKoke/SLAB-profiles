"use client";

/**
 * A player's injuries on a time-axis chart: hatched vertical bands with a
 * solid onset line, plus an HTML strip under the chart listing the ones in
 * view. Placement rules live in `lib/injuryRanges.ts`; this file only draws.
 *
 * Why it looks like this
 * ----------------------
 * * **Grayish red, hatched, vertical.** Red, amber and green are already the
 *   club's threshold bands, drawn as HORIZONTAL flat fills. An injury has to
 *   read as a different kind of thing without relying on colour: it runs
 *   vertically, it is textured, and it starts with a solid line — solid so it
 *   is never mistaken for the tooltip's dashed cursor.
 * * **Behind the series.** Same rule as the club bands: in SVG the order of
 *   the children is the paint order, so these go right after
 *   `referenceBandAreas` and before any line.
 * * **The strip is the interactive part.** Recharts' tooltip follows data
 *   points, not areas, so hovering a band cannot be made reliable; the strip
 *   gives real links, focus and an `aria-label` per injury, and the tooltip
 *   adds one line when the hovered point falls in (or right after) one.
 *
 * Like `referenceBandAreas`, the band helpers return arrays of elements and
 * not a wrapper component: Recharts inspects its children by type.
 */

import Link from "next/link";
import React, { useId, useMemo } from "react";
import { ReferenceArea, ReferenceLine } from "recharts";

import { usePlayerInjuries } from "@/components/perfil/PlayerInjuries/PlayerInjuriesContext";
import {
  type InjuryRange,
  type PlacedInjury,
  describeInjury,
  fmtDay,
  injuriesBetween,
  injuryContext,
  placeInjuries,
  shortLabel,
} from "@/lib/injuryRanges";

import styles from "./InjuryBands.module.css";

/** Muted, grayish red: reads as "injury" without competing with the bands. */
export const INJURY_INK = "#9a5b5b";

export function injuryDefs(patternId: string): React.ReactElement {
  return (
    <defs key={`defs-${patternId}`}>
      <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse"
        patternTransform="rotate(45)">
        <rect width="6" height="6" fill={INJURY_INK} fillOpacity={0.09} />
        <line x1="0" y1="0" x2="0" y2="6" stroke={INJURY_INK} strokeWidth={1.4}
          strokeOpacity={0.5} />
      </pattern>
    </defs>
  );
}

export function injuryBandAreas(
  placed: readonly PlacedInjury[],
  opts: {
    patternId: string;
    xDomain?: [number, number];
    /** Short "Muslo D · 34 d" on the band itself — full-width charts only. */
    labels?: boolean;
    yAxisId?: string | number;
    xAxisId?: string | number;
  },
): React.ReactElement[] {
  if (placed.length === 0) return [];
  const span = opts.xDomain ? opts.xDomain[1] - opts.xDomain[0] : 0;
  const out: React.ReactElement[] = [];
  for (const p of placed) {
    const ancho = span > 0 ? (p.x2 - p.x1) / span : 0;
    out.push(
      <ReferenceArea
        key={`inj-${p.injury.id}`}
        x1={p.x1}
        x2={p.x2}
        yAxisId={opts.yAxisId}
        xAxisId={opts.xAxisId}
        fill={`url(#${opts.patternId})`}
        stroke="none"
        ifOverflow="hidden"
        label={opts.labels && ancho >= 0.1 ? {
          value: shortLabel(p.injury),
          position: "insideTop",
          fill: INJURY_INK,
          fontSize: 10,
          fontWeight: 600,
        } : undefined}
      />,
    );
    if (!p.clippedLeft) {
      out.push(
        <ReferenceLine
          key={`inj-start-${p.injury.id}`}
          x={p.x1}
          yAxisId={opts.yAxisId}
          xAxisId={opts.xAxisId}
          stroke={INJURY_INK}
          strokeWidth={1.5}
          strokeOpacity={0.7}
          ifOverflow="hidden"
        />,
      );
    }
  }
  return out;
}

export interface ChartInjuries {
  playerId: string | null;
  injuries: InjuryRange[];
  placed: PlacedInjury[];
  patternId: string;
  /** Tooltip line for a hovered day, or null. */
  contextFor: (day: string | undefined) => string | null;
}

/**
 * Everything a chart needs, from the chronological `YYYY-MM-DD` of its rows.
 * Memoised on the rows, not on the window: the pan re-renders every frame.
 */
export function useChartInjuries(days: readonly string[]): ChartInjuries {
  const { playerId, injuries } = usePlayerInjuries();
  const raw = useId();
  const patternId = `inj-${raw.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const placed = useMemo(() => placeInjuries(injuries, days), [injuries, days]);
  return {
    playerId,
    injuries,
    placed,
    patternId,
    contextFor: (d) => (d ? injuryContext(injuries, d) : null),
  };
}

/**
 * The injuries overlapping the visible window, as links to the Lesiones tab.
 * `compact` (half-width cards) keeps only region + duration on the chip; the
 * full sentence is always in the `aria-label` and the `title`.
 */
export function InjuryStrip({
  chart,
  fromDay,
  toDay,
  compact = false,
}: {
  chart: ChartInjuries;
  fromDay?: string;
  toDay?: string;
  compact?: boolean;
}) {
  if (!chart.playerId || !fromDay || !toDay) return null;
  const enVista = injuriesBetween(chart.injuries, fromDay, toDay);
  if (enVista.length === 0) return null;
  return (
    <ul className={styles.strip} aria-label={`${enVista.length} lesiones en el período visible`}>
      {enVista.map((inj) => {
        const texto = describeInjury(inj);
        return (
          <li key={inj.id}>
            <Link
              href={`/perfil/${chart.playerId}?tab=lesiones`}
              className={`${styles.chip} ${inj.ended_at ? "" : styles.abierta}`}
              aria-label={`Lesión: ${texto}. Ver en Lesiones`}
              title={texto}
            >
              <span className={styles.swatch} aria-hidden />
              <span className={styles.nombre}>{shortLabel(inj)}</span>
              {!compact && (
                <span className={styles.detalle}>
                  {inj.summary.diagnosis ? ` · ${inj.summary.diagnosis}` : ""}
                  {" · "}
                  {fmtDay(inj.started_at)}
                  {inj.ended_at ? ` – ${fmtDay(inj.ended_at)}` : ""}
                  {inj.summary.severity ? ` · ${inj.summary.severity}` : ""}
                  {!inj.ended_at && inj.stage_label ? ` · ${inj.stage_label}` : ""}
                </span>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** The tooltip line itself, styled consistently across charts. */
export function InjuryTooltipLine({ text, light = false }: { text: string | null; light?: boolean }) {
  if (!text) return null;
  return <span className={`${styles.tooltipLine} ${light ? styles.tooltipLineLight : ""}`}>{text}</span>;
}
