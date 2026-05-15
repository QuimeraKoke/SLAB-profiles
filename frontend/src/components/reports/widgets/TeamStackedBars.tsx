"use client";

import React, { useMemo } from "react";

import type {
  TeamReportWidget,
  TeamStackedBarsPayload,
} from "@/lib/types";
import styles from "./TeamStackedBars.module.css";

interface Props {
  widget: TeamReportWidget;
}

/**
 * One horizontal stacked bar per player. Each row is sized proportionally
 * to the team's largest TOTAL so the relative differences between
 * players are obvious. The segments inside a bar are sized vs the row's
 * own total so the segment composition is faithful.
 */
export default function TeamStackedBars({ widget }: Props) {
  const data = widget.data as TeamStackedBarsPayload;

  const teamMaxTotal = useMemo(() => {
    let m = 0;
    for (const row of data.rows ?? []) {
      if (row.total > m) m = row.total;
    }
    return m > 0 ? m : 1;
  }, [data.rows]);

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <div>
          <h4 className={styles.title}>{widget.title}</h4>
          {widget.description && (
            <p className={styles.description}>{widget.description}</p>
          )}
        </div>
        <span className={styles.subtitleTag}>
          {data.aggregator === "sum"
            ? "Total"
            : data.aggregator === "avg"
              ? "Promedio"
              : data.aggregator === "max"
                ? "Máximo"
                : "Última"}
          {" · "}orden {data.order === "desc" ? "descendente" : "ascendente"}
        </span>
      </header>

      <div className={styles.legend} aria-hidden="true">
        {(data.fields ?? []).map((f) => (
          <span key={f.key} className={styles.legendItem}>
            <span
              className={styles.legendSwatch}
              style={{ background: f.color }}
            />
            {f.label}{f.unit ? ` (${f.unit})` : ""}
          </span>
        ))}
      </div>

      {data.empty || (data.rows ?? []).length === 0 ? (
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      ) : (
        <div className={styles.body}>
          {data.rows.map((row) => {
            const total = row.total || 0;
            const rowWidthPct = Math.max(2, (total / teamMaxTotal) * 100);
            return (
              <div key={row.player_id} className={styles.row}>
                <div className={styles.playerName} title={row.player_name}>
                  {row.player_name}
                </div>
                <div className={styles.barTrack}>
                  <div
                    className={styles.stack}
                    style={{ width: `${rowWidthPct}%` }}
                  >
                    {data.fields.map((f) => {
                      const value = row.values[f.key];
                      if (typeof value !== "number" || value <= 0) return null;
                      const segPct = (value / total) * 100;
                      return (
                        <div
                          key={f.key}
                          className={styles.segment}
                          style={{
                            width: `${segPct}%`,
                            background: f.color,
                          }}
                          title={`${f.label}: ${value}${f.unit ? " " + f.unit : ""}`}
                        >
                          <span className={styles.segmentValue}>
                            {formatNumber(value)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <span className={styles.totalLabel}>
                    {formatNumber(total)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}
