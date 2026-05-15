"use client";

import React from "react";

import ActivityLogList from "@/components/dashboards/activity/ActivityLogList";
import type {
  TeamActivityLogPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamActivityLog.module.css";

interface Props {
  widget: TeamReportWidget;
}

/** Team-wide activity log. Reuses the same list component as the
 *  per-player variant, with `showPlayer={true}` so each row prepends
 *  the player name. */
export default function TeamActivityLog({ widget }: Props) {
  const data = widget.data as TeamActivityLogPayload;
  const entries = data.entries ?? [];
  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <div>
          <h4 className={styles.title}>{widget.title}</h4>
          {widget.description && (
            <p className={styles.description}>{widget.description}</p>
          )}
        </div>
        {entries.length > 0 && (
          <span className={styles.countTag}>
            {entries.length} registro{entries.length === 1 ? "" : "s"}
          </span>
        )}
      </header>
      <ActivityLogList
        entries={entries}
        showPlayer
        emptyMessage={
          data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin registros recientes para esta categoría."
        }
      />
    </div>
  );
}
