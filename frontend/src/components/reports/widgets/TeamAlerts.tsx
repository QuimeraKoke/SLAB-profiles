"use client";

import React, { useState } from "react";

import PlayerAlertsList from "@/components/perfil/PlayerAlertsList/PlayerAlertsList";
import type {
  TeamAlertsPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamAlerts.module.css";

interface Props {
  widget: TeamReportWidget;
}

const SEVERITY_LABEL: Record<string, string> = {
  critical: "Crítica",
  warning: "Advertencia",
  info: "Info",
};

/**
 * Team-side alert ranking: players sorted by critical-count, then total
 * count. Each card shows the player's department-scoped active alerts.
 */
export default function TeamAlerts({ widget }: Props) {
  const data = widget.data as TeamAlertsPayload;
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const players = data.players ?? [];

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <div>
          <h4 className={styles.title}>{widget.title}</h4>
          {widget.description && (
            <p className={styles.description}>{widget.description}</p>
          )}
          {data.department_name && (
            <span className={styles.meta}>
              Departamento · {data.department_name}
            </span>
          )}
        </div>
        {!data.empty && (
          <span className={styles.totalTag}>
            {data.total_alerts} alerta{data.total_alerts === 1 ? "" : "s"} activa{data.total_alerts === 1 ? "" : "s"}
          </span>
        )}
      </header>

      {data.empty || players.length === 0 ? (
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin alertas activas en este departamento 🎉"}
        </div>
      ) : (
        <ul className={styles.playerList}>
          {players.map((p) => {
            const isOpen = expanded[p.player_id] ?? true;
            return (
              <li key={p.player_id} className={styles.playerCard}>
                <button
                  type="button"
                  className={styles.playerHeader}
                  onClick={() =>
                    setExpanded((cur) => ({ ...cur, [p.player_id]: !isOpen }))
                  }
                  aria-expanded={isOpen}
                >
                  <span
                    className={`${styles.severityRail} ${severityClass(p.max_severity)}`}
                    aria-hidden="true"
                  />
                  <span className={styles.playerName}>{p.player_name}</span>
                  <span className={styles.countCluster}>
                    {p.critical_count > 0 && (
                      <span className={`${styles.countPill} ${styles.countCritical}`}>
                        {p.critical_count} {SEVERITY_LABEL.critical.toLowerCase()}
                      </span>
                    )}
                    <span className={styles.countPill}>
                      {p.alert_count} total
                    </span>
                    <span className={styles.chevron} aria-hidden="true">
                      {isOpen ? "▾" : "▸"}
                    </span>
                  </span>
                </button>
                {isOpen && (
                  <div className={styles.playerBody}>
                    <PlayerAlertsList alerts={p.alerts} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function severityClass(severity: string): string {
  switch (severity) {
    case "critical":
      return styles.severityCritical;
    case "warning":
      return styles.severityWarning;
    default:
      return styles.severityInfo;
  }
}
