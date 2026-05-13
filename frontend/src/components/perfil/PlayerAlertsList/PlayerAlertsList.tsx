"use client";

import React from "react";
import { AlertTriangle, Bell, Info } from "lucide-react";

import type { AlertItem } from "@/lib/types";
import styles from "./PlayerAlertsList.module.css";

interface Props {
  alerts: AlertItem[];
  /** Shown when the list is empty. Defaults to a friendly message. */
  emptyMessage?: string;
  /** Maximum rows to display. Extra rows collapse into a "+N más" tail. */
  limit?: number;
}

/**
 * Compact list of active alerts. Used by both the per-player widget
 * (department-scoped via the resolver) and the profile summary panel
 * (no filter — every active alert the player has).
 */
export default function PlayerAlertsList({
  alerts,
  emptyMessage = "Sin alertas activas",
  limit,
}: Props) {
  if (alerts.length === 0) {
    return <div className={styles.empty}>{emptyMessage}</div>;
  }
  const cap = typeof limit === "number" ? Math.max(1, limit) : alerts.length;
  const visible = alerts.slice(0, cap);
  const overflow = alerts.length - visible.length;
  return (
    <ul className={styles.list}>
      {visible.map((a) => (
        <li key={a.id} className={styles.row}>
          <span
            className={`${styles.severityDot} ${severityClass(a.severity)}`}
            aria-hidden="true"
          />
          <div className={styles.body}>
            <div className={styles.message}>{a.message}</div>
            <div className={styles.meta}>
              {a.template_name && (
                <span className={styles.tag}>{a.template_name}</span>
              )}
              <span className={styles.timestamp}>{formatDate(a.fired_at)}</span>
            </div>
          </div>
          <SourceIcon source={a.source_type} severity={a.severity} />
        </li>
      ))}
      {overflow > 0 && (
        <li className={styles.overflow}>+{overflow} más</li>
      )}
    </ul>
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

function SourceIcon({ source, severity }: { source: string; severity: string }) {
  const color =
    severity === "critical" ? "#dc2626" : severity === "warning" ? "#f59e0b" : "#6b7280";
  if (source === "goal" || source === "goal_warning") {
    return <Bell size={14} color={color} aria-label="Objetivo" />;
  }
  if (source === "threshold") {
    return <AlertTriangle size={14} color={color} aria-label="Umbral / banda" />;
  }
  return <Info size={14} color={color} />;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}
