"use client";

import React from "react";

import type {
  TeamActiveRecordsPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamActiveRecords.module.css";

interface Props {
  widget: TeamReportWidget;
}

export default function TeamActiveRecords({ widget }: Props) {
  const data = widget.data as TeamActiveRecordsPayload;

  if (data.empty || (data.rows ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} data={data} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : `Nadie en el plantel tiene un registro activo al ${formatDate(data.as_of)}.`}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Jugador</th>
              {(data.columns ?? []).map((c) => (
                <th key={c.key}>
                  {c.label}
                  {c.unit && <span className={styles.unit}> ({c.unit})</span>}
                </th>
              ))}
              <th>Inicio</th>
              <th>Hasta</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.player_id}>
                <td className={styles.playerCell} title={row.player_name}>
                  {row.player_name}
                </td>
                {(data.columns ?? []).map((c) => {
                  const v = row.values?.[c.key];
                  return (
                    <td key={c.key} className={styles.cell}>
                      {v === null || v === undefined || v === "" ? "—" : String(v)}
                    </td>
                  );
                })}
                <td className={styles.dateCell}>{formatDate(row.started_at)}</td>
                <td className={styles.dateCell}>
                  {row.ends_at ? formatDate(row.ends_at) : (
                    <span className={styles.openEnded}>en curso</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Header({
  widget,
  data,
}: {
  widget: TeamReportWidget;
  data: TeamActiveRecordsPayload;
}) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
      <div className={styles.headlineWrap}>
        <span className={styles.headlineNumber}>
          {data.active_count}
          <span className={styles.headlineDenominator}>/{data.total}</span>
        </span>
        <span className={styles.headlineLabel}>
          activos al {formatDate(data.as_of)}
        </span>
      </div>
    </header>
  );
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
