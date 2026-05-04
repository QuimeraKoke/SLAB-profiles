"use client";

import React from "react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

import type { DashboardWidget, DonutPerResultPayload } from "@/lib/types";
import styles from "./Widget.module.css";

interface DonutPerResultProps {
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

const DONUT_DEFAULT_HEIGHT = 180;

export default function DonutPerResult({ widget }: DonutPerResultProps) {
  const data = widget.data as DonutPerResultPayload;
  const chartHeight = widget.chart_height ?? DONUT_DEFAULT_HEIGHT;
  const heightScale = chartHeight / DONUT_DEFAULT_HEIGHT;
  const innerRadius = Math.round(42 * heightScale);
  const outerRadius = Math.round(70 * heightScale);
  if (data.donuts.length === 0) {
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

      <div className={styles.donutGrid}>
        {data.donuts.map((donut) => (
          <div key={donut.result_id} className={styles.donutItem}>
            <div className={styles.donutDate}>{formatDate(donut.recorded_at)}</div>
            <div className={styles.donutChart}>
              <ResponsiveContainer width="100%" height={chartHeight}>
                <PieChart>
                  <Pie
                    data={donut.slices}
                    dataKey="value"
                    nameKey="label"
                    cx="50%"
                    cy="50%"
                    innerRadius={innerRadius}
                    outerRadius={outerRadius}
                    paddingAngle={1}
                    isAnimationActive={false}
                  >
                    {donut.slices.map((slice, i) => (
                      <Cell
                        key={slice.key}
                        fill={slice.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]}
                      />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className={styles.donutLegend}>
              {donut.slices.map((slice, i) => (
                <li key={slice.key} className={styles.donutLegendItem}>
                  <span
                    className={styles.donutDot}
                    style={{
                      backgroundColor:
                        slice.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length],
                    }}
                  />
                  <span className={styles.donutLegendLabel}>{slice.label}</span>
                  <span className={styles.donutLegendValue}>
                    {slice.percentage.toFixed(1)}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
