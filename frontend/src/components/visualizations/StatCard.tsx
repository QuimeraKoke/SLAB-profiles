import React from "react";
import type { VisualizerProps } from "./types";
import styles from "./StatCard.module.css";

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

export default function StatCard({ field, series }: VisualizerProps) {
  const last = series.length > 0 ? series[series.length - 1] : null;
  const previous = series.length > 1 ? series[series.length - 2] : null;

  let delta: number | null = null;
  if (
    last &&
    previous &&
    typeof last.value === "number" &&
    typeof previous.value === "number"
  ) {
    delta = last.value - previous.value;
  }

  return (
    <div className={styles.card}>
      <span className={styles.label}>{field.label}</span>
      <div className={styles.valueRow}>
        <span className={styles.value}>{formatValue(last?.value)}</span>
        {field.unit && <span className={styles.unit}>{field.unit}</span>}
      </div>
      <div className={styles.meta}>
        {delta !== null && (
          <span className={delta >= 0 ? styles.up : styles.down}>
            {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(2)}
            {field.unit ? ` ${field.unit}` : ""}
          </span>
        )}
        <span className={styles.count}>
          {series.length} {series.length === 1 ? "registro" : "registros"}
        </span>
      </div>
    </div>
  );
}
