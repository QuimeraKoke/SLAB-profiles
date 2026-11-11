"use client";

/**
 * What the Centro de mando squad panels are reading, so every card can say it
 * the same way: the PERIOD (a Mon–Sun week, or any start–end the staff
 * picked) and the DAY chosen inside it (the day strip). Cards answer one or
 * the other — never both — and show which with `<ScopeBadge>`.
 */
import { createContext, useContext } from "react";

export interface PeriodWords {
  /** A start–end period (not a calendar week). */
  range: boolean;
  /** "la semana" / "el período" */
  the: string;
  /** "esta semana" / "este período" */
  this: string;
  /** "de la semana" / "del período" */
  of: string;
  /** "Semana" / "Período" */
  Name: string;
  /** "en la semana" / "en el período" */
  in: string;
  /** The day chosen in the strip (ISO) and how cards print it: "Dom 15 nov · MD+1". */
  day: string | null;
  dayText: string;
  /** "Semana 46 · 9 – 15 nov" / "20 oct – 11 nov · 23 días" */
  periodText: string;
}

const WEEK = { range: false, the: "la semana", this: "esta semana", of: "de la semana", Name: "Semana", in: "en la semana" };
const RANGE = { range: true, the: "el período", this: "este período", of: "del período", Name: "Período", in: "en el período" };

export const WEEK_WORDS: PeriodWords = { ...WEEK, day: null, dayText: "", periodText: "" };
export const RANGE_WORDS: PeriodWords = { ...RANGE, day: null, dayText: "", periodText: "" };

export function periodWords(range: boolean, info: { day: string | null; dayText: string; periodText: string }): PeriodWords {
  return { ...(range ? RANGE : WEEK), ...info };
}

export const PeriodContext = createContext<PeriodWords>(WEEK_WORDS);
export const usePeriod = () => useContext(PeriodContext);
