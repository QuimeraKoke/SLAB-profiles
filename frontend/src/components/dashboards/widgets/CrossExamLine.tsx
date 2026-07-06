"use client";

import React, { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CrossExamLinePayload, CrossExamMatchInfo, DashboardWidget } from "@/lib/types";
import { ChartWindowNav, fullRangeDomain, useChartWindow, windowRangeLabel } from "./ChartWindow";
import { MovingAvgControl, trailingMean, useMovingAverage } from "./MovingAverage";
import styles from "./Widget.module.css";

interface CrossExamLineProps {
  widget: DashboardWidget;
}

const DEFAULT_PALETTE = ["#3b82f6", "#f97316", "#10b981", "#a855f7", "#06b6d4"];

/**
 * Cross-exam line chart: one line per data source, each possibly from a
 * DIFFERENT exam template (e.g. CK from Médico + match distance from GPS).
 *
 * Because cross-template series rarely share a scale, the widget supports a
 * second y-axis: `display_config.right_axis_keys` lists the `field_key`s
 * plotted against the right axis. Everything else stays on the left.
 * Axis titles default to each side's unit (override with `y_axis_title` /
 * `right_y_axis_title`).
 *
 * Rows are merged per CALENDAR DAY (not per timestamp) so series sampled at
 * different hours — or date-shifted server-side via the source's
 * `date_shift_days` — share one x-tick. When a row's day is a match day
 * (`data.matches`), the tooltip names the rival; shifted values also show
 * their real sample date.
 */
export default function CrossExamLine({ widget }: CrossExamLineProps) {
  const data = widget.data as CrossExamLinePayload;

  const config = (widget.display_config ?? {}) as {
    x_axis_title?: string;
    y_axis_title?: string;
    right_y_axis_title?: string;
    right_axis_keys?: string[];
  };
  const rightKeys = new Set(config.right_axis_keys ?? []);

  // Synthetic per-series dataKey — field_keys can repeat across templates.
  const seriesMeta = useMemo(
    () =>
      (data.series ?? []).map((s, i) => ({
        ...s,
        dataKey: `${s.field_key}::${i}`,
        axis: rightKeys.has(s.field_key) ? "right" : "left",
        strokeColor: s.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length],
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data.series, config.right_axis_keys],
  );
  const hasRight = seriesMeta.some((s) => s.axis === "right");

  const ma = useMovingAverage();

  // Pivot per-series points into day-indexed rows. Keying on the calendar
  // day (not the full timestamp) is what lets a 12:00 CK sample and an
  // 18:00 match GPS export land on the SAME x-tick.
  const chartData = useMemo(() => {
    const dateMap = new Map<string, Record<string, string | number | null>>();
    for (const s of seriesMeta) {
      for (const point of s.points) {
        const day = point.recorded_at.slice(0, 10);
        const existing = dateMap.get(day) ?? {
          day,
          recorded_at: point.recorded_at,
          label: formatShortDate(point.recorded_at),
        };
        existing[s.dataKey] = point.value;
        if (point.actual_recorded_at) {
          existing[`${s.dataKey}::actual`] = point.actual_recorded_at;
        }
        dateMap.set(day, existing);
      }
    }
    const rows = [...dateMap.values()].sort((a, b) =>
      String(a.day).localeCompare(String(b.day)),
    );
    // Moving average per series, over the FULL history (not the visible
    // window) so paging back never changes already-drawn averages. Keys are
    // only attached while the toggle is on — the tooltip keys off them.
    if (ma.enabled) {
      for (const s of seriesMeta) {
        const avg = trailingMean(
          rows.map((r) => r[s.dataKey] as number | null | undefined),
          ma.windowSize,
        );
        rows.forEach((r, i) => {
          r[`${s.dataKey}::ma`] = avg[i];
        });
      }
    }
    return rows;
  }, [seriesMeta, ma.enabled, ma.windowSize]);

  const window = useChartWindow(chartData);

  // Fixed per-side axis over the FULL history — the frame stays put while
  // the window slides.
  const yDomains = useMemo(() => {
    const bySide = { left: [] as (number | null)[], right: [] as (number | null)[] };
    for (const s of seriesMeta) {
      const bucket = bySide[s.axis as "left" | "right"];
      for (const pt of s.points) bucket.push(pt.value);
    }
    return {
      left: fullRangeDomain(bySide.left),
      right: fullRangeDomain(bySide.right),
    };
  }, [seriesMeta]);

  const axisUnit = (side: "left" | "right") => {
    const units = [...new Set(seriesMeta.filter((s) => s.axis === side).map((s) => s.unit))];
    return units.length === 1 ? units[0] : "";
  };
  const leftTitle = config.y_axis_title ?? axisUnit("left");
  const rightTitle = config.right_y_axis_title ?? axisUnit("right");

  if (seriesMeta.length === 0 || chartData.length === 0) {
    return (
      <div className={styles.widget}>
        <header className={styles.header}>
          <h4 className={styles.title}>{widget.title}</h4>
        </header>
        <div className={styles.empty}>Sin datos registrados.</div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
      </header>
      {widget.description && <p className={styles.description}>{widget.description}</p>}

      <div className={styles.compareBar}>
        <MovingAvgControl ma={ma} />
      </div>

      <ChartWindowNav window={window} label={windowRangeLabel(window.visible)} />
      <div className={styles.chartArea} style={{ height: widget.chart_height ?? 420 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={window.data} margin={{ top: 8, right: hasRight ? 8 : 16, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            {/* Numeric idx axis: the viewport (domain) pans smoothly over
                the full dataset. Explicit height keeps the title INSIDE
                the axis band, clear of the legend row. */}
            <XAxis
              dataKey="idx"
              type="number"
              domain={window.xDomain}
              ticks={window.ticks}
              tickFormatter={window.formatTick}
              allowDataOverflow
              tick={{ fontSize: 11, fill: "#6b7280" }}
              stroke="#d1d5db"
              height={46}
              label={{
                value: config.x_axis_title ?? "Fecha",
                position: "insideBottom",
                offset: 0,
                style: { fill: "#6b7280", fontSize: 11, fontWeight: 600 },
              }}
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 11, fill: "#6b7280" }}
              stroke="#d1d5db"
              width={56}
              domain={yDomains.left ?? ["auto", "auto"]}
              label={
                leftTitle
                  ? {
                      value: leftTitle,
                      angle: -90,
                      position: "insideLeft",
                      style: { textAnchor: "middle", fill: "#6b7280", fontSize: 11, fontWeight: 600 },
                    }
                  : undefined
              }
            />
            {hasRight && (
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 11, fill: "#6b7280" }}
                stroke="#d1d5db"
                width={56}
                domain={yDomains.right ?? ["auto", "auto"]}
                label={
                  rightTitle
                    ? {
                        value: rightTitle,
                        angle: 90,
                        position: "insideRight",
                        style: { textAnchor: "middle", fill: "#6b7280", fontSize: 11, fontWeight: 600 },
                      }
                    : undefined
                }
              />
            )}
            <Tooltip
              content={<CrossExamTooltip series={seriesMeta} matches={data.matches} />}
              cursor={{ stroke: "#9ca3af", strokeDasharray: "3 3" }}
            />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} iconType="circle" iconSize={8} />
            {ma.enabled &&
              seriesMeta.map((s) => (
                <Line
                  key={`${s.dataKey}::ma`}
                  yAxisId={s.axis}
                  type="monotone"
                  dataKey={`${s.dataKey}::ma`}
                  name={`${s.label} (media móvil)`}
                  stroke={s.strokeColor}
                  strokeOpacity={0.5}
                  strokeWidth={1.6}
                  strokeDasharray="4 3"
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
              ))}
            {seriesMeta.map((s) => (
              <Line
                key={s.dataKey}
                yAxisId={s.axis}
                type="monotone"
                dataKey={s.dataKey}
                name={
                  s.label +
                  (hasRight ? (s.axis === "right" ? " (der.)" : " (izq.)") : "") +
                  shiftTag(s.date_shift_days)
                }
                stroke={s.strokeColor}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ payload?: Record<string, string | number | null> }>;
  series: Array<{ dataKey: string; label: string; unit: string }>;
  matches?: Record<string, CrossExamMatchInfo>;
}

function CrossExamTooltip({ active, payload, series, matches }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point || typeof point.recorded_at !== "string") return null;
  const match = typeof point.day === "string" ? matches?.[point.day] : undefined;
  return (
    <div className={styles.chartTooltip}>
      <span className={styles.chartTooltipDate}>{formatLongDate(point.recorded_at)}</span>
      {match && (
        <span className={styles.chartTooltipValue}>
          {match.opponent
            ? `Partido vs ${match.opponent}${
                match.home === true ? " (local)" : match.home === false ? " (visita)" : ""
              }`
            : `Partido: ${match.title}`}
        </span>
      )}
      {series.map((s) => {
        const value = point[s.dataKey];
        if (typeof value !== "number") return null;
        const actual = point[`${s.dataKey}::actual`];
        const avg = point[`${s.dataKey}::ma`];
        return (
          <span key={s.dataKey} className={styles.chartTooltipValue}>
            {s.label}: {value.toFixed(1)}
            {s.unit ? ` ${s.unit}` : ""}
            {typeof avg === "number" ? ` · MM ${avg.toFixed(1)}` : ""}
            {typeof actual === "string" ? ` · muestra ${formatShortDate(actual)}` : ""}
          </span>
        );
      })}
    </div>
  );
}

/** Legend suffix making a server-side date shift visible, e.g. " · −2d". */
function shiftTag(days: number | undefined): string {
  if (!days) return "";
  return ` · ${days > 0 ? "+" : "−"}${Math.abs(days)}d`;
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}`;
}

function formatLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
