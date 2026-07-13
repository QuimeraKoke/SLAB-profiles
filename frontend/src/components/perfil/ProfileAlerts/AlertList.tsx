"use client";

import React from "react";
import type { Alert } from "@/lib/types";
import styles from "./AlertList.module.css";

interface Props {
  alerts: Alert[];
  onDismiss?: (alert: Alert) => void;
  /** "resolved" renders the read-only Historial (no dismiss button). */
  mode?: "active" | "resolved";
}

export default function AlertList({ alerts, onDismiss, mode = "active" }: Props) {
  const resolved = mode === "resolved";
  return (
    <section className={`${styles.section} ${resolved ? styles.sectionResolved : ""}`}>
      <h4 className={styles.title}>
        {resolved ? "Historial de alertas" : "Alertas activas"} · {alerts.length}
      </h4>
      {alerts.map((a) => (
        <div key={a.id} className={styles.row}>
          <span className={`${styles.severity} ${styles[a.severity] ?? ""}`} />
          <span className={styles.message}>
            {a.message}
            {a.trigger_count > 1 && (
              <span className={styles.count}>(× {a.trigger_count})</span>
            )}
          </span>
          {a.source_recorded_at && (
            <span
              className={styles.dateChip}
              title="Fecha del dato que originó la alerta"
            >
              dato del {formatDate(a.source_recorded_at)}
            </span>
          )}
          {!resolved && onDismiss && (
            <button
              type="button"
              className={styles.dismissBtn}
              onClick={() => onDismiss(a)}
            >
              Descartar
            </button>
          )}
        </div>
      ))}
    </section>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
    });
  } catch {
    return iso;
  }
}
