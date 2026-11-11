"use client";

/**
 * The ONE time control of the Centro de mando squad panels:
 *
 *   [‹] [📅 Semana 46 · 9 – 15 nov] [›]  Ir a hoy
 *    Lu 9  Ma 10  Mi 11  Ju 12  Vi 13  [Sá 14 vs CC]  Do 15
 *    MD-5  MD-4   MD-3   MD-2   MD-1                  MD+1
 *
 * The period (a Mon–Sun week, or any start–end picked in the calendar) and
 * the day chosen inside it (the strip). Cards that add up days read the
 * period; cards about one day read the strip's day — each says which with a
 * ScopeBadge. Days after today cannot be chosen (they have no data yet).
 */

import React, { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

import CalendarPicker, { addDays, daysBetween, mondayOf, rivalShort, shortLabel } from "@/components/loadControl/CalendarPicker";
import { type DayNav } from "@/lib/loadControl";

import styles from "./loadControl.module.css";

const WD = ["Do", "Lu", "Ma", "Mi", "Ju", "Vi", "Sá"];

/** The day to show when the period changes: today if it is inside, else the
 *  last day of a past period, else its first day. */
export function dayIn(start: string, end: string, today: string, wanted?: string | null): string {
  if (wanted && wanted >= start && wanted <= end && wanted <= today) return wanted;
  if (today >= start && today <= end) return today;
  return end < today ? end : start;
}

export const isCalendarWeek = (start: string, end: string) => mondayOf(start) === start && daysBetween(start, end) === 6;

export function periodText(nav: DayNav): string {
  const n = daysBetween(nav.start_date, nav.end_date) + 1;
  return nav.range
    ? `${shortLabel(nav.start_date)} – ${shortLabel(nav.end_date)} · ${n} ${n === 1 ? "día" : "días"}`
    : `Semana ${nav.number} · ${shortLabel(nav.start_date)} – ${shortLabel(nav.end_date)}`;
}

export function dayText(nav: DayNav): string {
  const d = new Date(`${nav.day}T12:00:00`);
  const md = nav.days?.find((x) => x.date === nav.day);
  const tag = md?.opponent ? `vs ${md.opponent}` : md?.md_label || nav.md_label;
  return `${WD[d.getDay()]} ${shortLabel(nav.day)}${tag ? ` · ${tag}` : ""}`;
}

export default function PeriodBar({ nav, categoryId, today, strip, onPeriod, onDay }: {
  nav: DayNav;
  categoryId: string;
  today: string;
  /** Show the day strip (tabs with day cards). */
  strip: boolean;
  onPeriod: (start: string, end: string, day: string) => void;
  onDay: (day: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const len = daysBetween(nav.start_date, nav.end_date) + 1;
  const shift = (n: number) => {
    const a = addDays(nav.start_date, n), b = addDays(nav.end_date, n);
    onPeriod(a, b, dayIn(a, b, today, addDays(nav.day, n)));
  };
  const toToday = () => {
    if (!nav.range) { const mon = mondayOf(today); onPeriod(mon, addDays(mon, 6), today); return; }
    onPeriod(addDays(today, -(len - 1)), today, today);
  };
  const atToday = nav.day === today && nav.end_date >= today && nav.start_date <= today;
  const text = periodText(nav);

  return (
    <div className={styles.periodBar}>
      <div className={styles.periodRow} role="group" aria-label="Período">
        <button type="button" className={styles.iconBtn} onClick={() => shift(-len)}
          aria-label={nav.range ? `Período anterior (${len} días antes)` : "Semana anterior"}>
          <ChevronLeft size={18} aria-hidden="true" />
        </button>
        <span className={styles.calWrap}>
          <button type="button" className={styles.dateBtn} onClick={() => setOpen((v) => !v)} aria-expanded={open}
            aria-haspopup="dialog" aria-label={`${text}. Cambiar semana o fechas`}>
            <CalendarDays size={15} aria-hidden="true" />
            <strong>{text}</strong>
            {!nav.range && !nav.planned && <span className={styles.muted}>· sin planificar</span>}
          </button>
          {open && (
            <CalendarPicker categoryId={categoryId} today={today} start={nav.start_date} end={nav.end_date} day={nav.day}
              onPick={(a, b, d) => onPeriod(a, b, dayIn(a, b, today, d))} onClose={() => setOpen(false)} />
          )}
        </span>
        <button type="button" className={styles.iconBtn} onClick={() => shift(len)}
          aria-label={nav.range ? `Período siguiente (${len} días después)` : "Semana siguiente"}>
          <ChevronRight size={18} aria-hidden="true" />
        </button>
        {!atToday && <button type="button" className={styles.linkButton} onClick={toToday}>Ir a hoy</button>}
      </div>
      {strip && nav.days && <DayStrip nav={nav} today={today} onDay={onDay} />}
    </div>
  );
}

function DayStrip({ nav, today, onDay }: { nav: DayNav; today: string; onDay: (d: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const days = nav.days ?? [];

  // Keep the chosen day in view on long periods.
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [nav.day]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const allowed = days.filter((d) => d.date <= today).map((d) => d.date);
    if (!allowed.length) return;
    const i = allowed.indexOf(nav.day);
    const next = e.key === "Home" ? allowed[0] : e.key === "End" ? allowed[allowed.length - 1]
      : allowed[Math.max(0, Math.min(allowed.length - 1, i + (e.key === "ArrowLeft" ? -1 : 1)))];
    onDay(next);
    requestAnimationFrame(() => ref.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
  };

  return (
    <div ref={ref} className={styles.strip} role="radiogroup" aria-label="Elige el día que quieres ver" onKeyDown={onKey}>
      {days.map((d) => {
        const dt = new Date(`${d.date}T12:00:00`);
        const future = d.date > today;
        const match = d.kind === "official" || d.kind === "friendly";
        const on = d.date === nav.day;
        const sub = match ? (d.opponent ? `vs ${rivalShort(d.opponent)}` : "Partido") : d.md_label || (d.kind === "rest" ? "Descanso" : "");
        const label = `${["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"][dt.getDay()]} ${shortLabel(d.date)}`
          + `${match ? `, partido ${d.kind === "official" ? "oficial" : "amistoso"}${d.opponent ? ` vs ${d.opponent}` : ""}` : d.md_label ? `, ${d.md_label}` : ""}`
          + `${d.date === today ? " (hoy)" : ""}${future ? ", todavía sin datos" : ""}`;
        return (
          <button key={d.date} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1}
            aria-label={label} aria-disabled={future} disabled={future}
            title={match && d.opponent ? `${d.kind === "official" ? "Oficial" : "Amistoso"} vs ${d.opponent}` : undefined}
            className={[styles.chip, on && styles.chipOn, match && (d.kind === "official" ? styles.chipOfficial : styles.chipFriendly),
              d.date === today && styles.chipToday].filter(Boolean).join(" ")}
            onClick={() => onDay(d.date)}>
            <span className={styles.chipDay}>{WD[dt.getDay()]} {dt.getDate()}</span>
            <span className={styles.chipSub}>{sub || " "}</span>
          </button>
        );
      })}
    </div>
  );
}
