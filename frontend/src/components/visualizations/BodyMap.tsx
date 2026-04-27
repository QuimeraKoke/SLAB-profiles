import React from "react";
import type { VisualizerProps } from "./types";
import styles from "./BodyMap.module.css";

/**
 * Placeholder body-map visualization. Renders a list of categorical zones
 * recorded over time so medical staff can still see what was logged before
 * the interactive anatomical figure ships.
 */
export default function BodyMap({ field, series }: VisualizerProps) {
  const recent = series.slice(-5).reverse();

  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <span className={styles.label}>{field.label}</span>
        <span className={styles.badge}>Body map (preview)</span>
      </header>
      {recent.length === 0 ? (
        <div className={styles.empty}>Sin registros aún.</div>
      ) : (
        <ul className={styles.list}>
          {recent.map((p, idx) => (
            <li key={idx} className={styles.item}>
              <span className={styles.zone}>{String(p.value ?? "—")}</span>
              <span className={styles.when}>
                {new Date(p.recorded_at).toLocaleDateString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
