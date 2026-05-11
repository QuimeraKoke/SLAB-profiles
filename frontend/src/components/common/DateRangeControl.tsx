"use client";

import React from "react";

import styles from "./DateRangeControl.module.css";

/** Maximum span (in days) the date range can cover. Enforced both here
 *  and in the backend so a bypassed UI can't pull years of data. */
export const DATE_WINDOW_MAX_DAYS = 90;

export type DatePreset = "30" | "60" | "90" | "custom";

export interface DateRange {
  /** ISO date "YYYY-MM-DD". Empty string when not set. */
  from: string;
  to: string;
}

export interface DateRangeValue {
  preset: DatePreset;
  date: DateRange;
}

interface Props {
  value: DateRangeValue;
  onChange: (next: DateRangeValue) => void;
  /** Layout density. "compact" trims the labels (used inside dense
   *  toolbars like the team-report filters). Default = "default". */
  variant?: "default" | "compact";
}

/** Period dropdown + optional custom from/to date inputs. Enforces the
 *  90-day cap on the client (the server re-enforces it independently). */
export default function DateRangeControl({ value, onChange, variant = "default" }: Props) {
  const { preset, date } = value;

  function applyPreset(next: DatePreset) {
    if (next === "custom") {
      onChange({ preset: "custom", date });
      return;
    }
    const days = parseInt(next, 10);
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - days);
    onChange({ preset: next, date: { from: iso(from), to: iso(to) } });
  }

  function applyCustom(field: "from" | "to", raw: string) {
    const nextDate = { ...date, [field]: raw };
    if (nextDate.from && nextDate.to) {
      const fromMs = new Date(nextDate.from).getTime();
      const toMs = new Date(nextDate.to).getTime();
      const spanDays = (toMs - fromMs) / (1000 * 60 * 60 * 24);
      if (spanDays > DATE_WINDOW_MAX_DAYS) {
        // Pin the opposite side so the window equals the cap. Friendlier
        // than rejecting input — the user always sees a valid range.
        if (field === "from") {
          const newTo = new Date(fromMs + DATE_WINDOW_MAX_DAYS * 86400000);
          nextDate.to = iso(newTo);
        } else {
          const newFrom = new Date(toMs - DATE_WINDOW_MAX_DAYS * 86400000);
          nextDate.from = iso(newFrom);
        }
      }
      if (new Date(nextDate.to).getTime() < new Date(nextDate.from).getTime()) {
        // Swap rather than reject — friendlier than a validation error.
        const tmp = nextDate.from;
        nextDate.from = nextDate.to;
        nextDate.to = tmp;
      }
    }
    onChange({ preset: "custom", date: nextDate });
  }

  const widthClass = variant === "compact" ? styles.compact : "";

  return (
    <div className={`${styles.group} ${widthClass}`}>
      <label className={styles.field}>
        <span className={styles.label}>Período</span>
        <select
          value={preset}
          onChange={(e) => applyPreset(e.target.value as DatePreset)}
        >
          <option value="30">Últimos 30 días</option>
          <option value="60">Últimos 60 días</option>
          <option value="90">Últimos 90 días</option>
          <option value="custom">Personalizado</option>
        </select>
      </label>
      {preset === "custom" && (
        <>
          <label className={styles.field}>
            <span className={styles.label}>Desde</span>
            <input
              type="date"
              value={date.from}
              onChange={(e) => applyCustom("from", e.target.value)}
            />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>Hasta</span>
            <input
              type="date"
              value={date.to}
              onChange={(e) => applyCustom("to", e.target.value)}
            />
          </label>
        </>
      )}
    </div>
  );
}

/** Default value matching "Últimos 30 días". Exported so callers can
 *  initialize state without duplicating the date math. */
export function defaultDateRange(): DateRangeValue {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 30);
  return {
    preset: "30",
    date: { from: iso(from), to: iso(to) },
  };
}

function iso(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
