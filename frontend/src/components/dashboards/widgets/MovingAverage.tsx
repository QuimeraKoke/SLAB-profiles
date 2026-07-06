"use client";

import React, { useState } from "react";

import styles from "./Widget.module.css";

/** Window options offered by the control, in observations (not days). */
const WINDOW_OPTIONS = [3, 5, 7, 10];
export const DEFAULT_MA_WINDOW = 5;

/**
 * Trailing moving average over the last `windowSize` OBSERVATIONS (non-null
 * values), aligned with the input: null/missing slots stay null so the
 * overlay only paints where the base series has a point. Early points
 * average whatever history exists (a 5-point MA over the 2nd point is a
 * 2-point mean) — charts shouldn't open with a bald left edge.
 */
export function trailingMean(
  values: ReadonlyArray<number | null | undefined>,
  windowSize: number,
): (number | null)[] {
  const seen: number[] = [];
  return values.map((v) => {
    if (typeof v !== "number") return null;
    seen.push(v);
    const slice = seen.slice(-windowSize);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

export interface MovingAvgState {
  enabled: boolean;
  windowSize: number;
  setEnabled: (on: boolean) => void;
  setWindowSize: (n: number) => void;
}

export function useMovingAverage(): MovingAvgState {
  const [enabled, setEnabled] = useState(false);
  const [windowSize, setWindowSize] = useState(DEFAULT_MA_WINDOW);
  return { enabled, windowSize, setEnabled, setWindowSize };
}

/** Checkbox (+ window picker once active) shared by the time-line charts.
 *  The select sits OUTSIDE the label — nested, every click on it would
 *  toggle the checkbox. */
export function MovingAvgControl({ ma }: { ma: MovingAvgState }) {
  return (
    <span className={styles.maControl}>
      <label className={styles.maCheckbox}>
        <input
          type="checkbox"
          checked={ma.enabled}
          onChange={(e) => ma.setEnabled(e.target.checked)}
        />
        <span>Media móvil</span>
      </label>
      {ma.enabled && (
        <select
          className={styles.maWindowSelect}
          value={ma.windowSize}
          aria-label="Ventana de la media móvil"
          onChange={(e) => ma.setWindowSize(Number(e.target.value))}
        >
          {WINDOW_OPTIONS.map((n) => (
            <option key={n} value={n}>
              últ. {n}
            </option>
          ))}
        </select>
      )}
    </span>
  );
}
