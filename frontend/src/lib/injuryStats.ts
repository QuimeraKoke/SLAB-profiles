/**
 * Injury indicators for comparing players — pure, over `InjuryRange` rows.
 *
 * Two different questions hide in "injuries in a period", and they need
 * different rules:
 *
 * * **How many** (incidence): injuries that STARTED in the period. An injury
 *   from last season that is still being rehabbed is not a new one.
 * * **How much it cost** (burden): days out that fall INSIDE the period,
 *   whenever the injury started. A 200-day ACL that began before the window
 *   still took every day of it.
 *
 * Mixing them — counting by overlap, or summing whole durations — makes a
 * player who got hurt once look like a serial case, or hides a long layoff.
 */

import {
  type InjuryRange,
  day,
  durationDays,
  endDay,
  shortType,
  todayIso,
} from "./injuryRanges";

const DAY_MS = 86_400_000;
const ms = (d: string) => Date.parse(`${d}T00:00:00Z`);
const between = (a: string, b: string) => Math.round((ms(b) - ms(a)) / DAY_MS);

/** Fuller: more than 28 days out is a severe injury. */
export const SEVERE_DAYS = 28;

export interface Ranking {
  nombre: string;
  n: number;
}

export interface InjuryStats {
  total: number;
  diasPerdidos: number;
  promedio: number | null;
  severas: number;
  recidivas: number;
  musculares: number;
  /** Share of the period's days the player was NOT injured, 0–100. */
  disponibilidad: number | null;
  porZona: Ranking[];
  porTipo: Ranking[];
  abierta: InjuryRange | null;
  ultima: InjuryRange | null;
  diasDesdeUltima: number | null;
}

function ranking(valores: string[]): Ranking[] {
  const c = new Map<string, number>();
  for (const v of valores) c.set(v, (c.get(v) ?? 0) + 1);
  return [...c.entries()]
    .map(([nombre, n]) => ({ nombre, n }))
    .sort((a, b) => b.n - a.n || a.nombre.localeCompare(b.nombre));
}

/**
 * `from = null` → the player's whole history. `injuries` must be one
 * player's; the caller filters.
 */
export function injuryStats(
  injuries: readonly InjuryRange[],
  from: string | null,
  to: string = todayIso(),
  today: string = todayIso(),
): InjuryStats {
  const desde = from ?? "0000-01-01";
  const nuevas = injuries.filter((l) => {
    const s = day(l.started_at);
    return s >= desde && s <= to;
  });

  // Burden: the union of injured days clipped to the window, so two
  // overlapping injuries do not count the same day twice.
  const tramos = injuries
    .map((l) => [day(l.started_at), endDay(l, today)] as const)
    .map(([s, e]) => [s < desde ? desde : s, e > to ? to : e] as const)
    .filter(([s, e]) => s <= e)
    .sort((a, b) => a[0].localeCompare(b[0]));
  let diasPerdidos = 0;
  let fin: string | null = null;
  for (const [s, e] of tramos) {
    if (fin === null || s > fin) {
      diasPerdidos += between(s, e);
      fin = e;
    } else if (e > fin) {
      diasPerdidos += between(fin, e);
      fin = e;
    }
  }

  // An open injury has no duration yet, but the days it has lasted so far
  // are certain: 46 days and counting is already severe.
  const duraciones = nuevas.map((l) => durationDays(l) ?? between(day(l.started_at), today));
  const ultima = [...injuries].sort((a, b) => b.started_at.localeCompare(a.started_at))[0] ?? null;
  const abierta = injuries.find((l) => !l.ended_at) ?? null;
  const periodo = from ? between(from, to) : 0;

  return {
    total: nuevas.length,
    diasPerdidos,
    promedio: duraciones.length
      ? Math.round(duraciones.reduce((a, b) => a + b, 0) / duraciones.length) : null,
    severas: duraciones.filter((d) => d > SEVERE_DAYS).length,
    recidivas: nuevas.filter((l) => l.summary.recurrencia === "Recurrente").length,
    musculares: nuevas.filter((l) => shortType(l) === "Muscular").length,
    disponibilidad: from && periodo > 0
      ? Math.max(0, Math.round((1 - diasPerdidos / periodo) * 100)) : null,
    porZona: ranking(nuevas.map((l) => l.summary.body_part || "Sin zona")),
    porTipo: ranking(nuevas.map(shortType)),
    abierta,
    ultima,
    diasDesdeUltima: ultima ? between(day(ultima.started_at), today) : null,
  };
}
