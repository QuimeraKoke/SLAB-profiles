"use client";

import React from "react";

import type {
  ActivityLogEntry,
  TeamActivityLogEntry,
} from "@/lib/types";
import styles from "./ActivityLogList.module.css";

type Entry = ActivityLogEntry | TeamActivityLogEntry;

interface Props {
  entries: Entry[];
  /** When true, each row prepends the player name (team variant).
   *  Per-player widgets pass false — the player is already in context. */
  showPlayer?: boolean;
  emptyMessage?: string;
}

/**
 * Shared timeline list. Consumed by the per-player `activity_log`
 * widget AND the team `team_activity_log` widget. The team variant
 * passes `showPlayer={true}`; the per-player variant omits it.
 *
 * Each entry's `fields` array is rendered verbatim — no compile-time
 * field-name knowledge, so adding a new schema (e.g. swapping
 * Molestias' fields) doesn't need a frontend change.
 */
export default function ActivityLogList({
  entries,
  showPlayer = false,
  emptyMessage = "Sin registros recientes",
}: Props) {
  if (entries.length === 0) {
    return <div className={styles.empty}>{emptyMessage}</div>;
  }

  return (
    <ol className={styles.list}>
      {entries.map((entry) => (
        <li key={entry.id} className={styles.row}>
          <div className={styles.meta}>
            <span className={styles.date}>{formatDate(entry.recorded_at)}</span>
            {showPlayer && "player_name" in entry && (
              <span className={styles.player}>{entry.player_name}</span>
            )}
            <span className={styles.template}>{entry.template_name}</span>
          </div>
          <div className={styles.fields}>
            {entry.fields.map((f) => {
              const rendered = formatFieldValue(f.value);
              if (rendered === null) return null;
              return (
                <div key={f.key} className={styles.field}>
                  <span className={styles.fieldLabel}>{f.label}</span>
                  <span className={styles.fieldValue}>
                    {rendered}{f.unit ? ` ${f.unit}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </li>
      ))}
    </ol>
  );
}

function formatFieldValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "Sí" : "No";
  return String(value);
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
