/**
 * Whether a change in a metric is an improvement, a decline, or neither —
 * the ONE place the ▲/▼ colour of a delta is decided.
 *
 * The direction comes from the field (`direction_of_good` on the exam
 * template): "up" = more is better (CMJ, VO₂, 1RM), "down" = less is better
 * (sprint times, CK, asymmetry). Anything else — "neutral", or unset, like
 * every GPS load metric: more distance is not better or worse by itself —
 * gets NO judgement: the arrow says which way it moved, in neutral ink.
 *
 * Never colour a delta by its sign alone: that paints a better jump red or a
 * slower sprint green, depending on which way the component author guessed.
 */
export type DeltaTone = "good" | "bad" | "neutral" | "flat";

export function deltaTone(
  delta: number | null | undefined,
  directionOfGood: string | null | undefined,
): DeltaTone {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return "neutral";
  if (delta === 0) return "flat";
  if (directionOfGood === "up") return delta > 0 ? "good" : "bad";
  if (directionOfGood === "down") return delta < 0 ? "good" : "bad";
  return "neutral";
}

/** Hover text for the arrow, so the colour is never the only cue. */
export function deltaToneTitle(tone: DeltaTone): string | undefined {
  if (tone === "good") return "Mejora";
  if (tone === "bad") return "Empeora";
  if (tone === "neutral") return "Cambio (esta métrica no tiene dirección de mejora definida)";
  return undefined;
}
