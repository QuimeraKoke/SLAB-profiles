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

import type { DashboardWidget, MultiLinePayload } from "@/lib/types";
import { ChartWindowNav, fullRangeDomain, useChartWindow, windowRangeLabel } from "./ChartWindow";
import { MovingAvgControl, trailingMean, useMovingAverage } from "./MovingAverage";
import styles from "./Widget.module.css";

interface MultiLineProps {
  widget: DashboardWidget;
}

const DEFAULT_PALETTE = [
  "#3b82f6", // blue
  "#f97316", // orange
  "#10b981", // green
  "#f59e0b", // amber
  "#a855f7", // purple
  "#06b6d4", // cyan
  "#ec4899", // pink
];

export default function MultiLine({ widget }: MultiLineProps) {
  const data = widget.data as MultiLinePayload;

  const config = (widget.display_config ?? {}) as {
    x_axis_title?: string;
    y_axis_title?: string;
  };
  const xAxisTitle = config.x_axis_title ?? "Fecha";
  // If every series shares a unit, use it as the Y-axis title. Otherwise blank
  // (mixed units = no single label that makes sense).
  const sharedUnit = data.series.length > 0 && data.series.every((s) => s.unit === data.series[0].unit)
    ? data.series[0].unit
    : "";
  const yAxisTitle = config.y_axis_title ?? sharedUnit;

  const ma = useMovingAverage();

  // Pivot the per-series points into a date-indexed array Recharts can chart.
  // Result shape: [{ label: "07-09", recorded_at: "...", masa_muscular: 36.18, masa_adiposa: 11.41, ... }, ...]
  const chartData = useMemo(() => {
    const dateMap = new Map<string, Record<string, string | number | null>>();
    for (const series of data.series) {
      for (const point of series.points) {
        const existing = dateMap.get(point.recorded_at) ?? {
          recorded_at: point.recorded_at,
          label: formatShortDate(point.recorded_at),
        };
        existing[series.key] = point.value;
        dateMap.set(point.recorded_at, existing);
      }
    }
    const rows = [...dateMap.values()].sort(
      (a, b) =>
        new Date(a.recorded_at as string).getTime() -
        new Date(b.recorded_at as string).getTime(),
    );
    // Moving average per series over the FULL history (not the visible
    // window). Keys only exist while the toggle is on — the tooltip keys
    // off their presence.
    if (ma.enabled) {
      for (const series of data.series) {
        const avg = trailingMean(
          rows.map((r) => r[series.key] as number | null | undefined),
          ma.windowSize,
        );
        rows.forEach((r, i) => {
          r[`${series.key}::ma`] = avg[i];
        });
      }
    }
    return rows;
  }, [data.series, ma.enabled, ma.windowSize]);

  // Per-chart time window (latest first, chevrons to page through history).
  const window = useChartWindow(chartData);

  // Fixed axis over the FULL history — the frame stays put while sliding.
  const yDomain = useMemo(
    () => fullRangeDomain(data.series.flatMap((s) => s.points.map((p) => p.value))),
    [data.series],
  );

  if (data.series.length === 0 || chartData.length === 0) {
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
          <LineChart data={window.data} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
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
                value: xAxisTitle,
                position: "insideBottom",
                offset: 0,
                style: { fill: "#6b7280", fontSize: 11, fontWeight: 600 },
              }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#6b7280" }}
              stroke="#d1d5db"
              width={56}
              domain={yDomain ?? ["auto", "auto"]}
              label={
                yAxisTitle
                  ? {
                      value: yAxisTitle,
                      angle: -90,
                      position: "insideLeft",
                      style: {
                        textAnchor: "middle",
                        fill: "#6b7280",
                        fontSize: 11,
                        fontWeight: 600,
                      },
                    }
                  : undefined
              }
            />
            <Tooltip content={<MultiLineTooltip series={data.series} />} cursor={{ stroke: "#9ca3af", strokeDasharray: "3 3" }} />
            <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} iconType="circle" iconSize={8} />
            {ma.enabled &&
              data.series.map((series, i) => (
                <Line
                  key={`${series.key}::ma`}
                  type="monotone"
                  dataKey={`${series.key}::ma`}
                  name={`${series.label} (media móvil)`}
                  stroke={series.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
                  strokeOpacity={0.5}
                  strokeWidth={1.6}
                  strokeDasharray="4 3"
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
              ))}
            {data.series.map((series, i) => (
              <Line
                key={series.key}
                type="monotone"
                dataKey={series.key}
                name={series.label}
                stroke={series.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
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
  series: MultiLinePayload["series"];
}

function MultiLineTooltip({ active, payload, series }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point || typeof point.recorded_at !== "string") return null;

  return (
    <div className={styles.chartTooltip}>
      <span className={styles.chartTooltipDate}>
        {formatLongDate(point.recorded_at as string)}
      </span>
      {series.map((s) => {
        const value = point[s.key];
        if (typeof value !== "number") return null;
        const avg = point[`${s.key}::ma`];
        return (
          <span key={s.key} className={styles.chartTooltipValue}>
            {s.label}: {value.toFixed(1)}
            {s.unit ? ` ${s.unit}` : ""}
            {typeof avg === "number" ? ` · MM ${avg.toFixed(1)}` : ""}
          </span>
        );
      })}
    </div>
  );
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
