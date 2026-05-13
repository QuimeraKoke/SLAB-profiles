"use client";

import React from "react";

import type {
  TeamLeaderboardPayload,
  TeamReportWidget,
} from "@/lib/types";

import styles from "./TeamLeaderboard.module.css";

interface Props {
  widget: TeamReportWidget;
}

const AGGREGATOR_LABELS: Record<TeamLeaderboardPayload["aggregator"], string> = {
  sum: "Total",
  avg: "Promedio",
  max: "Máximo",
  latest: "Última toma",
};

/** Top-N podium ranking. Rows are ordered server-side; this just paints
 *  the ranks. Top 3 get gold/silver/bronze tint for visual flair. */
export default function TeamLeaderboard({ widget }: Props) {
  const data = widget.data as TeamLeaderboardPayload;

  if (data.empty || (data.rows ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} data={data} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  const unit = data.field?.unit ? ` ${data.field.unit}` : "";

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <ol className={styles.list}>
        {data.rows.map((row) => (
          <li
            key={row.player_id}
            className={`${styles.row} ${podiumClass(row.rank, styles)}`}
          >
            <span className={styles.rank}>#{row.rank}</span>
            <span className={styles.name} title={row.player_name}>
              {row.player_name}
            </span>
            <span className={styles.value}>
              {formatNumber(row.value)}{unit}
            </span>
            <span className={styles.samples}>
              {row.samples} {row.samples === 1 ? "toma" : "tomas"}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function podiumClass(rank: number, styles: Record<string, string>): string {
  if (rank === 1) return styles.rowGold;
  if (rank === 2) return styles.rowSilver;
  if (rank === 3) return styles.rowBronze;
  return "";
}

function Header({
  widget, data,
}: { widget: TeamReportWidget; data: TeamLeaderboardPayload }) {
  const aggLabel = AGGREGATOR_LABELS[data.aggregator] ?? data.aggregator;
  const fieldLabel = data.field
    ? data.field.unit
      ? `${data.field.label} (${data.field.unit})`
      : data.field.label
    : "";
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
      <span className={styles.subtitleTag}>
        {aggLabel} · {fieldLabel}
      </span>
    </header>
  );
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}
