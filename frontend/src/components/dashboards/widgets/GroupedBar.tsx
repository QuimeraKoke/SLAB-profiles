"use client";

import React, { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DashboardWidget, GroupedBarPayload } from "@/lib/types";
import styles from "./Widget.module.css";

interface GroupedBarProps {
  widget: DashboardWidget;
}

const DEFAULT_PALETTE = ["#f97316", "#3b82f6", "#10b981", "#f59e0b", "#a855f7"];

export default function GroupedBar({ widget }: GroupedBarProps) {
  const data = widget.data as GroupedBarPayload;

  const config = (widget.display_config ?? {}) as {
    x_axis_title?: string;
    y_axis_title?: string;
  };
  const xAxisTitle = config.x_axis_title ?? "Fecha";
  const sharedUnit = data.fields.length > 0 && data.fields.every((f) => f.unit === data.fields[0].unit)
    ? data.fields[0].unit
    : "";
  const yAxisTitle = config.y_axis_title ?? sharedUnit;

  const chartData = useMemo(
    () =>
      data.groups.map((g) => {
        const row: Record<string, string | number | null> = { label: formatShortDate(g.recorded_at) };
        for (const bar of g.bars) {
          row[bar.key] = bar.value;
        }
        return row;
      }),
    [data.groups],
  );

  const unitsByLabel = useMemo(
    () => new Map(data.fields.map((f) => [f.label, f.unit])),
    [data.fields],
  );

  if (data.groups.length === 0 || data.fields.length === 0) {
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

      <div className={styles.chartArea} style={{ height: widget.chart_height ?? 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 64 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: "#6b7280" }}
              stroke="#d1d5db"
              label={{
                value: xAxisTitle,
                position: "insideBottom",
                offset: -12,
                style: { fill: "#6b7280", fontSize: 11, fontWeight: 600 },
              }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#6b7280" }}
              stroke="#d1d5db"
              width={56}
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
            <Tooltip
              cursor={{ fill: "rgba(0, 0, 0, 0.04)" }}
              contentStyle={{
                background: "#111827",
                border: "none",
                borderRadius: 4,
                color: "#fff",
                fontSize: 12,
              }}
              formatter={(value, name) => {
                if (typeof value !== "number") return [String(value), name];
                const unit = unitsByLabel.get(String(name));
                return [`${value.toFixed(1)}${unit ? ` ${unit}` : ""}`, name];
              }}
            />
            <Legend
              verticalAlign="bottom"
              wrapperStyle={{ fontSize: 11, paddingTop: 20 }}
              iconType="circle"
              iconSize={8}
            />
            {data.fields.map((field, i) => (
              <Bar
                key={field.key}
                dataKey={field.key}
                name={field.label}
                fill={field.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}`;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
