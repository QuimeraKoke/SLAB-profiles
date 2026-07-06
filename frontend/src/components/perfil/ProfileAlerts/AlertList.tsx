"use client";

import React from "react";
import type { Alert } from "@/lib/types";
import styles from "./AlertList.module.css";

interface Props {
  alerts: Alert[];
  onDismiss: (alert: Alert) => void;
}

export default function AlertList({ alerts, onDismiss }: Props) {
  return (
    <section className={styles.section}>
      <h4 className={styles.title}>
        Alertas activas · {alerts.length}
      </h4>
      {alerts.map((a) => (
        <div key={a.id} className={styles.row}>
          <span className={`${styles.severity} ${styles[a.severity] ?? ""}`} />
          <span className={styles.message}>
            {a.message}
            {a.trigger_count > 1 && (
              <span style={{ marginLeft: 6, color: "#9a3412", fontWeight: 600 }}>
                (× {a.trigger_count})
              </span>
            )}
          </span>
          <button
            type="button"
            className={styles.dismissBtn}
            onClick={() => onDismiss(a)}
          >
            Descartar
          </button>
        </div>
      ))}
    </section>
  );
}
