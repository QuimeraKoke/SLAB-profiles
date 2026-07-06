"use client";

import React, { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import styles from "./ChartWindow.module.css";

/** Default points visible per chart window. */
export const CHART_WINDOW_SIZE = 12;

/** Pan duration scaling: ms per point of distance, clamped to a range so a
 *  one-month hop feels deliberate and a "Reciente" jump never drags on. */
const PAN_MS_PER_POINT = 130;
const PAN_MIN_MS = 450;
const PAN_MAX_MS = 1400;

export interface ChartWindow<T> {
  /** ALL points, chronological, each tagged with its `idx` — feed this to
   *  the chart and let `xDomain` decide what's on screen. */
  data: (T & { idx: number })[];
  /** The slice nearest the current viewport (for labels / category charts). */
  visible: (T & { idx: number })[];
  /** Continuous viewport for a numeric x-axis — animates at 60 fps. */
  xDomain: [number, number];
  /** Integer indices inside the viewport, for the x-axis `ticks` prop. */
  ticks: number[];
  /** Maps an idx tick back to its point's short date label. */
  formatTick: (i: number) => string;
  total: number;
  /** 1-based index range of the visible slice, for the "n–m de N" meta. */
  from: number;
  to: number;
  canOlder: boolean;
  canNewer: boolean;
  older: () => void;
  newer: () => void;
  latest: () => void;
}

/**
 * Client-side time window over a chronological (oldest → newest) series.
 * Starts anchored at the newest points; chevrons PAN the viewport backward/
 * forward by ONE CALENDAR MONTH (consecutive views overlap, so the reader
 * keeps their bearings). The pan is a continuous ease-in-out animation of
 * `xDomain` over the full dataset — a camera move, not a page swap — so
 * charts must plot `data` on a numeric `idx` axis bounded by `xDomain`.
 * Points without a `recorded_at` field fall back to half-page steps.
 *
 * `resetKey` re-anchors to the latest window when the underlying series
 * changes identity (e.g. the user picks another variable in the selector).
 */
export function useChartWindow<T extends object>(
  points: T[],
  pageSize: number = CHART_WINDOW_SIZE,
  resetKey: unknown = null,
): ChartWindow<T> {
  // Offset = number of points hidden at the newest end (0 = latest window).
  // `pos` is the rendered offset — a FLOAT during a pan; `target` is where
  // the viewport is headed. A rAF effect eases pos toward target.
  const [pos, setPos] = useState(0);
  const [target, setTarget] = useState(0);

  // Re-anchor when the series identity changes — the official
  // "adjust state during render" pattern (no effect, no extra paint).
  const [prevKey, setPrevKey] = useState(resetKey);
  if (prevKey !== resetKey) {
    setPrevKey(resetKey);
    setPos(0);
    setTarget(0);
  }

  const data = useMemo(
    () => points.map((p, i) => ({ ...p, idx: i })),
    [points],
  );

  const total = points.length;
  const maxOffset = Math.max(0, total - pageSize);
  const clamped = Math.min(pos, maxOffset);
  const clampedTarget = Math.min(target, maxOffset);

  const dateAt = (i: number): number | null => {
    const p = points[i] as { recorded_at?: unknown } | undefined;
    if (!p || typeof p.recorded_at !== "string") return null;
    const t = new Date(p.recorded_at).getTime();
    return Number.isNaN(t) ? null : t;
  };

  /** Offset that puts the window's newest edge one calendar month from
   *  where `from` has it. dir 1 = older, -1 = newer. Falls back to
   *  half-page steps when points carry no dates; always moves ≥ 1 point. */
  const slideTarget = (from: number, dir: 1 | -1): number => {
    const anchorMs = dateAt(total - 1 - from);
    let next: number;
    if (anchorMs == null) {
      next = from + dir * Math.max(1, Math.floor(pageSize / 2));
    } else {
      const anchor = new Date(anchorMs);
      anchor.setMonth(anchor.getMonth() - dir);
      const targetMs = anchor.getTime();
      // Newest point still at-or-before the shifted anchor date.
      let idx = -1;
      for (let i = total - 1; i >= 0; i--) {
        const t = dateAt(i);
        if (t !== null && t <= targetMs) {
          idx = i;
          break;
        }
      }
      next = idx >= 0 ? total - 1 - idx : dir === 1 ? maxOffset : 0;
    }
    return dir === 1 ? Math.max(next, from + 1) : Math.min(next, from - 1);
  };

  // Ease the rendered position toward the target with rAF — a continuous
  // 60 fps camera pan. The effect fires when the target moves; it captures
  // the position at that moment as the start of the tween, so a re-target
  // mid-flight starts from wherever the viewport currently is.
  useEffect(() => {
    const from = clamped;
    const to = clampedTarget;
    if (from === to) return;
    const duration = Math.min(
      PAN_MAX_MS,
      Math.max(PAN_MIN_MS, Math.abs(to - from) * PAN_MS_PER_POINT),
    );
    const t0 = performance.now();
    const easeInOutCubic = (t: number) =>
      t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    let raf = requestAnimationFrame(function step(now: number) {
      const p = Math.min(1, (now - t0) / duration);
      setPos(from + (to - from) * easeInOutCubic(p));
      if (p < 1) raf = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(raf);
    // `clamped` is deliberately read-at-fire-time, not a dependency —
    // depending on it would restart the tween every animation frame.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clampedTarget, maxOffset]);

  const span = Math.min(pageSize, total);
  // Float start index of the viewport over `data`.
  const startFloat = Math.max(0, total - span - clamped);
  const roundedStart = Math.round(startFloat);
  const visible = data.slice(roundedStart, roundedStart + span);

  const ticks = useMemo(() => {
    const out: number[] = [];
    for (let i = Math.ceil(startFloat - 1e-6); i <= startFloat + span - 1 + 1e-6; i++) {
      if (i >= 0 && i < total) out.push(i);
    }
    return out;
  }, [startFloat, span, total]);

  return {
    data,
    visible,
    // ±0.5 mimics the half-band padding a category axis gives its points.
    xDomain: [startFloat - 0.5, startFloat + span - 0.5],
    ticks,
    formatTick: (i: number) => {
      const row = data[Math.round(i)] as { label?: unknown } | undefined;
      return row && typeof row.label === "string" ? row.label : "";
    },
    total,
    from: total === 0 ? 0 : roundedStart + 1,
    to: roundedStart + visible.length,
    // Availability tracks the TARGET, so rapid clicks keep sliding further
    // instead of waiting for the animation to settle.
    canOlder: clampedTarget < maxOffset,
    canNewer: clampedTarget > 0,
    older: () => setTarget(Math.min(slideTarget(clampedTarget, 1), maxOffset)),
    newer: () => setTarget(Math.max(slideTarget(clampedTarget, -1), 0)),
    latest: () => setTarget(0),
  };
}

/**
 * Fixed y-axis domain covering a series' FULL history (±5% padding), so the
 * axis doesn't rescale while the window slides — the frame of reference
 * stays put and only the data rolls through it. Bounds snap outward to a
 * round step so the evenly-spaced ticks recharts derives from an explicit
 * domain stay readable (3000/7000/… instead of 3956.6/7956.6/…).
 */
export function fullRangeDomain(
  values: ReadonlyArray<number | null | undefined>,
): [number, number] | undefined {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (typeof v !== "number" || Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === Infinity) return undefined;
  const span = max - min || Math.abs(max) || 1;
  const pad = span * 0.05;
  const step = Math.pow(10, Math.floor(Math.log10(span / 4)));
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  const lo = Math.floor((min - pad) / step) * step;
  const hi = Math.ceil((max + pad) / step) * step;
  return [Number(lo.toFixed(decimals)), Number(hi.toFixed(decimals))];
}

/**
 * The chevron navigator rendered above a windowed chart. Hidden entirely
 * when the series fits in one window — no dead controls.
 */
export function ChartWindowNav({
  window: w,
  label,
}: {
  window: ChartWindow<unknown>;
  label: string; // human date range of the visible slice, e.g. "12 abr – 30 jun"
}) {
  if (w.total === 0 || (!w.canOlder && !w.canNewer)) return null;
  return (
    <div className={styles.nav}>
      <button
        type="button"
        className={styles.navBtn}
        onClick={w.older}
        disabled={!w.canOlder}
        aria-label="Valores anteriores"
      >
        <ChevronLeft size={14} aria-hidden="true" />
      </button>
      <span className={styles.navLabel}>
        {label}
        <span className={styles.navMeta}>
          {w.from}–{w.to} de {w.total}
        </span>
      </span>
      <button
        type="button"
        className={styles.navBtn}
        onClick={w.newer}
        disabled={!w.canNewer}
        aria-label="Valores siguientes"
      >
        <ChevronRight size={14} aria-hidden="true" />
      </button>
      {w.canNewer && (
        <button type="button" className={styles.latestBtn} onClick={w.latest}>
          Reciente
        </button>
      )}
    </div>
  );
}

/** "12 abr – 30 jun" for the first/last visible points' recorded_at. */
export function windowRangeLabel(visible: ReadonlyArray<object>): string {
  if (visible.length === 0) return "";
  const first = (visible[0] as { recorded_at?: unknown }).recorded_at;
  const last = (visible[visible.length - 1] as { recorded_at?: unknown }).recorded_at;
  if (typeof first !== "string" || typeof last !== "string") return "";
  return `${fmtDay(first)} – ${fmtDay(last)}`;
}

function fmtDay(iso: string): string {
  return new Date(iso).toLocaleDateString("es-CL", { day: "numeric", month: "short" });
}
