"use client";

import React from "react";

import type { ComparisonTablePayload, DashboardWidget } from "@/lib/types";
import styles from "./Widget.module.css";

interface ComparisonTableProps {
  widget: DashboardWidget;
}

export default function ComparisonTable({ widget }: ComparisonTableProps) {
  const data = widget.data as ComparisonTablePayload;
  if (data.columns.length === 0) {
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

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.varCol}>Variable</th>
              {data.columns.map((c) => (
                <th key={c.result_id}>{formatDate(c.recorded_at)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td className={styles.varCol}>
                  {row.label}
                  {row.unit && <span className={styles.unit}> ({row.unit})</span>}
                </td>
                {row.values.map((value, i) => (
                  <td key={i}>
                    <div className={styles.valueCell}>
                      <span>{formatValue(value)}</span>
                      {row.deltas[i] !== null && row.deltas[i] !== 0 && (
                        <span
                          className={
                            (row.deltas[i] as number) > 0 ? styles.up : styles.down
                          }
                        >
                          {(row.deltas[i] as number) > 0 ? "▲" : "▼"}{" "}
                          {Math.abs(row.deltas[i] as number).toFixed(1)}
                        </span>
                      )}
                      {row.deltas[i] === 0 && (
                        <span className={styles.flat}>—∅</span>
                      )}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return date
    .toLocaleDateString(undefined, {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    })
    .replace(/\//g, "-");
}

function formatValue(value: number | string | boolean | null): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toFixed(1);
  if (typeof value === "boolean") return value ? "Sí" : "No";
  return String(value);
}
