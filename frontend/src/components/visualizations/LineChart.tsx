"use client";

import React from "react";
import {
  CartesianGrid,
  Line,
  LineChart as RechartsLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { VisualizerProps } from "./types";
import styles from "./LineChart.module.css";

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "2-digit" });
}

export default function LineChart({ field, series }: VisualizerProps) {
  const data = series
    .map((p) => ({
      recorded_at: p.recorded_at,
      label: shortDate(p.recorded_at),
      value: typeof p.value === "number" ? p.value : null,
    }))
    .filter((p) => p.value !== null);

  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <span className={styles.label}>{field.label}</span>
        {field.unit && <span className={styles.unit}>{field.unit}</span>}
      </header>

      {data.length === 0 ? (
        <div className={styles.empty}>Sin datos numéricos para graficar.</div>
      ) : (
        <div className={styles.chart}>
          <ResponsiveContainer width="100%" height="100%">
            <RechartsLineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#6b7280" }} />
              <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} domain={["auto", "auto"]} width={40} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  padding: "6px 10px",
                }}
                formatter={(value: unknown) => [
                  typeof value === "number" ? value.toFixed(2) : String(value),
                  field.label,
                ]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#6d28d9"
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            </RechartsLineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
