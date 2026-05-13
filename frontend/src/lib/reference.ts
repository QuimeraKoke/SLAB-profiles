/**
 * Helpers for clinical reference bands (TemplateField.reference_ranges).
 *
 * Bands are validated server-side as ordered, disjoint, with at most one
 * band open on each end. These helpers assume that contract — they walk
 * linearly without re-validating.
 */

import type { ReferenceBand } from "@/lib/types";

/** Find the band a numeric value falls into, or null when no band matches.
 *
 *  Semantics (matches server-side validation):
 *   - `min` is inclusive; `max` is exclusive — `30` falls in `{min:30,max:200}`
 *     and NOT in `{min:0,max:30}`. Picked exclusive on max so chained bands
 *     `[..., {max: 30}, {min: 30, max: 200}, ...]` don't double-claim the
 *     boundary value.
 *   - A band with no `min` matches values ≤ `max`.
 *   - A band with no `max` matches values ≥ `min`.
 */
export function findBandForValue(
  value: number,
  bands: ReferenceBand[] | undefined,
): ReferenceBand | null {
  if (!bands || bands.length === 0) return null;
  if (!Number.isFinite(value)) return null;
  for (const band of bands) {
    const hasMin = typeof band.min === "number";
    const hasMax = typeof band.max === "number";
    if (hasMin && value < (band.min as number)) continue;
    if (hasMax && value >= (band.max as number)) continue;
    return band;
  }
  return null;
}

/** Color for a band — explicit `color` overrides; otherwise we derive a
 *  default from a small palette indexed by label semantics. Falls back
 *  to a neutral gray when nothing matches. */
export function bandColor(band: ReferenceBand): string {
  if (band.color) return band.color;
  const lower = band.label.toLowerCase();
  if (lower.includes("normal") || lower.includes("óptim") || lower.includes("optim")) {
    return "#16a34a"; // green
  }
  if (lower.includes("bajo") || lower.includes("low")) {
    return "#fbbf24"; // amber
  }
  if (lower.includes("elevad") || lower.includes("alto") || lower.includes("high")) {
    return "#f59e0b"; // orange
  }
  if (lower.includes("sever") || lower.includes("crít") || lower.includes("crit")) {
    return "#dc2626"; // red
  }
  return "#6b7280"; // neutral gray
}

/** Compact static summary of all bands for the form hint when no value
 *  is entered yet. Example: "Normal 30-200 · Elevado 200-400 · Severo ≥400". */
export function summarizeBands(bands: ReferenceBand[]): string {
  return bands
    .map((b) => {
      const range = formatBandRange(b);
      return `${b.label}${range ? " " + range : ""}`;
    })
    .join(" · ");
}

/** Inline range text for a single band ("30-200", "≥400", "<30"). */
export function formatBandRange(b: ReferenceBand): string {
  const hasMin = typeof b.min === "number";
  const hasMax = typeof b.max === "number";
  if (hasMin && hasMax) return `${b.min}-${b.max}`;
  if (hasMax) return `<${b.max}`;
  if (hasMin) return `≥${b.min}`;
  return "";
}
