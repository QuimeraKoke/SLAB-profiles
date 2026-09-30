/**
 * Injuries on time-axis charts — the pure half (no React, no Recharts).
 *
 * ⚠️ The charts' x-axis is NOT time
 * ---------------------------------
 * `useChartWindow` plots rows on a numeric INDEX: row i sits at x = i, and the
 * days between two rows have no position of their own. An injury therefore
 * has to be placed by interpolating its dates between the neighbouring rows,
 * and — because an injured player usually produces no GPS or wellness rows —
 * a three-month layoff often lands BETWEEN two adjacent points. So the band's
 * width says "where", never "how long": the duration always travels as text
 * ("34 d"), and every band gets a minimum width so a short one never vanishes.
 *
 * Days are compared as `YYYY-MM-DD` strings (the charts' own row key), so a
 * chart keyed by full timestamp (`MultiLine`) passes `recorded_at[:10]`.
 */

export interface InjurySummary {
  body_part?: string;
  lado?: string;
  type?: string;
  diagnosis?: string;
  severity?: string;
  dias_perdidos?: number;
  recurrencia?: string;
}

/** `GET /injuries/ranges` row. */
export interface InjuryRange {
  id: string;
  player_id: string;
  player_name: string;
  status: "open" | "closed";
  stage_label: string;
  title: string;
  started_at: string;
  ended_at: string | null;
  summary: InjurySummary;
}

export interface PlacedInjury {
  injury: InjuryRange;
  x1: number;
  x2: number;
  open: boolean;
  /** Starts before the first loaded row — the band has no visible onset. */
  clippedLeft: boolean;
}

/** Narrowest band, in index units: a 2-day sprain must still be seen. */
const MIN_WIDTH = 0.3;
const DAY_MS = 86_400_000;

export const day = (iso: string): string => iso.slice(0, 10);

const ms = (d: string): number => Date.parse(`${d}T00:00:00Z`);

export function todayIso(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Day at which the injury ends for drawing: its discharge, or today if open. */
export function endDay(inj: InjuryRange, today: string): string {
  return inj.ended_at ? day(inj.ended_at) : today;
}

/** Days between start and end (inclusive of neither), or null if open. */
export function durationDays(inj: InjuryRange): number | null {
  if (typeof inj.summary.dias_perdidos === "number") return inj.summary.dias_perdidos;
  if (!inj.ended_at) return null;
  return Math.round((ms(day(inj.ended_at)) - ms(day(inj.started_at))) / DAY_MS);
}

/**
 * Fractional index of a day over chronological row days.
 * Before the first row → -0.5, after the last → last + 0.5 (the domain edge).
 */
export function dayToIdx(d: string, days: readonly string[]): number {
  const n = days.length;
  if (n === 0) return 0;
  if (d <= days[0]) return d === days[0] ? 0 : -0.5;
  if (d >= days[n - 1]) return d === days[n - 1] ? n - 1 : n - 0.5;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (days[mid] <= d) lo = mid;
    else hi = mid;
  }
  if (days[lo] === d) return lo;
  const a = ms(days[lo]);
  const b = ms(days[hi]);
  return b > a ? lo + (ms(d) - a) / (b - a) : lo;
}

/**
 * Injuries placed on a chart's rows. Drops the ones entirely outside the
 * loaded data (ended before the first row, or started after the last).
 */
export function placeInjuries(
  injuries: readonly InjuryRange[],
  days: readonly string[],
  today: string = todayIso(),
): PlacedInjury[] {
  if (days.length === 0 || injuries.length === 0) return [];
  const first = days[0];
  const last = days[days.length - 1];
  const out: PlacedInjury[] = [];
  for (const inj of injuries) {
    const start = day(inj.started_at);
    const end = endDay(inj, today);
    if (end < first || start > last) continue;
    let x1 = dayToIdx(start, days);
    let x2 = inj.ended_at ? dayToIdx(end, days) : days.length - 0.5;
    if (x2 - x1 < MIN_WIDTH) {
      const mid = (x1 + x2) / 2;
      x1 = mid - MIN_WIDTH / 2;
      x2 = mid + MIN_WIDTH / 2;
    }
    out.push({ injury: inj, x1, x2, open: !inj.ended_at, clippedLeft: start < first });
  }
  return out;
}

/** Injuries overlapping [fromDay, toDay] — what the strip under a chart lists. */
export function injuriesBetween(
  injuries: readonly InjuryRange[],
  fromDay: string,
  toDay: string,
  today: string = todayIso(),
): InjuryRange[] {
  return injuries.filter(
    (inj) => day(inj.started_at) <= toDay && endDay(inj, today) >= fromDay,
  );
}

const SIDE: Record<string, string> = { Derecho: "D", Izquierdo: "I" };

/** "Muslo D" — region + side, the shortest name an injury has. */
export function shortName(inj: InjuryRange): string {
  // Without a region the title is just the free-text diagnosis — too long
  // for a chip; the one-word type says enough.
  const region = inj.summary.body_part || shortType(inj);
  const side = inj.summary.lado ? SIDE[inj.summary.lado] : undefined;
  return [region, side].filter(Boolean).join(" ");
}

/** "Muslo D · 34 d" / "Muslo D · en curso". */
export function shortLabel(inj: InjuryRange): string {
  const d = durationDays(inj);
  return `${shortName(inj)} · ${d === null ? "en curso" : `${d} d`}`;
}

/**
 * The tooltip line for a hovered day:
 *  - inside an injury → "En lesión: Muslo D · día 12/34"
 *  - up to 21 days after a discharge → "Retorno +5 d (Muslo D)", the "after"
 *    reading the clinicians look for.
 */
export function injuryContext(
  injuries: readonly InjuryRange[],
  d: string,
  today: string = todayIso(),
): string | null {
  for (const inj of injuries) {
    const start = day(inj.started_at);
    if (start <= d && d <= endDay(inj, today)) {
      const n = Math.round((ms(d) - ms(start)) / DAY_MS) + 1;
      const total = durationDays(inj);
      return `En lesión: ${shortName(inj)} · día ${n}${total !== null ? `/${total}` : ""}`;
    }
  }
  for (const inj of injuries) {
    if (!inj.ended_at) continue;
    const since = Math.round((ms(d) - ms(day(inj.ended_at))) / DAY_MS);
    if (since > 0 && since <= 21) return `Retorno +${since} d (${shortName(inj)})`;
  }
  return null;
}

/** "12 mar 2026" */
export function fmtDay(iso: string): string {
  return new Date(`${day(iso)}T12:00:00`).toLocaleDateString("es-CL", {
    day: "numeric", month: "short", year: "numeric",
  });
}

/** Full sentence for screen readers and the strip's title attribute. */
export function describeInjury(inj: InjuryRange): string {
  const s = inj.summary;
  const partes = [
    s.diagnosis || inj.title || "Lesión",
    [s.body_part, s.lado && s.lado !== "NA" ? s.lado.toLowerCase() : ""].filter(Boolean).join(" "),
    inj.ended_at
      ? `${fmtDay(inj.started_at)} a ${fmtDay(inj.ended_at)}`
      : `desde ${fmtDay(inj.started_at)}, en curso${inj.stage_label ? ` (${inj.stage_label})` : ""}`,
    s.severity ? `severidad ${s.severity.toLowerCase()}` : "",
    durationDays(inj) !== null ? `${durationDays(inj)} días` : "",
    s.recurrencia === "Recurrente" ? "recidiva" : "",
  ];
  return partes.filter(Boolean).join(", ");
}

/** One word for the Fuller type — "Esguince", "Muscular". */
const TYPE_SHORT: [RegExp, string][] = [
  [/muscular/i, "Muscular"],
  [/esguince|ligament/i, "Esguince"],
  [/tend/i, "Tendón"],
  [/menisc|cart[ií]lago/i, "Menisco"],
  [/fractura|estr[eé]s [oó]seo/i, "Fractura"],
  [/luxaci/i, "Luxación"],
  [/contusi|hematoma/i, "Contusión"],
  [/laceraci/i, "Laceración"],
  [/nervios/i, "Nervio"],
  [/conmoci/i, "Conmoción"],
];

export function shortType(inj: InjuryRange): string {
  const t = inj.summary.type ?? "";
  for (const [re, label] of TYPE_SHORT) if (re.test(t)) return label;
  // "Otro" says nothing on a marker: the diagnosis' first word does.
  const diag = (inj.summary.diagnosis ?? "").trim().split(/\s+/)[0];
  return diag ? diag.charAt(0).toUpperCase() + diag.slice(1).toLowerCase() : "Lesión";
}

/** "Fernández · Esguince · Tobillo" — the marker text when several players share a chart. */
export function markerLabel(inj: InjuryRange): string {
  const apellido = inj.player_name.trim().split(/\s+/).slice(1).join(" ") || inj.player_name;
  return [apellido, shortType(inj), inj.summary.body_part].filter(Boolean).join(" · ");
}
