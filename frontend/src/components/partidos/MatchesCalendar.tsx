"use client";

import React, { useMemo } from "react";
import Link from "next/link";

import type { CalendarEvent } from "@/lib/types";
import styles from "./MatchesCalendar.module.css";

interface MatchesCalendarProps {
  matches: CalendarEvent[];
  /** Current month being viewed (1-12). */
  month: number;
  year: number;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
}

const WEEKDAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MONTH_LABELS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

/** Build a 6×7 grid of dates anchored on the visible month. Lun-first. */
function buildMonthGrid(year: number, month: number): Date[] {
  const firstOfMonth = new Date(year, month - 1, 1);
  // JS getDay: 0=Sun..6=Sat. We want Lun (1) as the first column,
  // mapped to index 0. So Mon=0..Sun=6.
  const dayOfWeek = (firstOfMonth.getDay() + 6) % 7;
  const start = new Date(year, month - 1, 1 - dayOfWeek);
  const cells: Date[] = [];
  for (let i = 0; i < 42; i++) {
    cells.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  }
  return cells;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export default function MatchesCalendar({
  matches,
  month,
  year,
  onPrev,
  onNext,
  onToday,
}: MatchesCalendarProps) {
  const grid = useMemo(() => buildMonthGrid(year, month), [year, month]);
  const today = new Date();

  // Index matches by yyyy-mm-dd for O(1) day lookup.
  const matchesByDay = useMemo(() => {
    const out = new Map<string, CalendarEvent[]>();
    for (const m of matches) {
      const d = new Date(m.starts_at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      const list = out.get(key);
      if (list) list.push(m);
      else out.set(key, [m]);
    }
    // Sort each day's matches by start time.
    for (const list of out.values()) {
      list.sort(
        (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
      );
    }
    return out;
  }, [matches]);

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <div className={styles.navGroup}>
          <button type="button" className={styles.navBtn} onClick={onPrev} aria-label="Mes anterior">
            ‹
          </button>
          <button type="button" className={styles.todayBtn} onClick={onToday}>
            Hoy
          </button>
          <button type="button" className={styles.navBtn} onClick={onNext} aria-label="Mes siguiente">
            ›
          </button>
        </div>
        <h2 className={styles.monthTitle}>
          {MONTH_LABELS[month - 1]} {year}
        </h2>
      </header>

      <div className={styles.grid}>
        {WEEKDAY_LABELS.map((label) => (
          <div key={label} className={styles.weekday}>
            {label}
          </div>
        ))}
        {grid.map((cell, i) => {
          const inMonth = cell.getMonth() === month - 1;
          const isToday = sameDay(cell, today);
          const key = `${cell.getFullYear()}-${String(cell.getMonth() + 1).padStart(2, "0")}-${String(cell.getDate()).padStart(2, "0")}`;
          const dayMatches = matchesByDay.get(key) ?? [];
          return (
            <div
              key={i}
              className={`${styles.cell} ${inMonth ? "" : styles.outOfMonth} ${isToday ? styles.today : ""}`}
            >
              <span className={styles.dayNumber}>{cell.getDate()}</span>
              <div className={styles.eventsList}>
                {dayMatches.map((m) => (
                  <MatchChip key={m.id} match={m} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MatchChip({ match }: { match: CalendarEvent }) {
  const time = new Date(match.starts_at).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  const hasData = match.result_count > 0;
  return (
    <Link
      href={`/partidos/${match.id}/editar`}
      className={styles.chip}
      title={`${time} · ${match.title}${match.location ? " · " + match.location : ""}`}
    >
      <span className={styles.chipTime}>{time}</span>
      <span className={styles.chipTitle}>{match.title}</span>
      {hasData && <span className={styles.chipDot} aria-label="Tiene datos vinculados" />}
    </Link>
  );
}
