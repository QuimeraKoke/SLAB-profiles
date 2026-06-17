"use client";

import React from "react";

import styles from "./ShowNoDataToggle.module.css";

interface Props {
  /** Whether no-data players are currently shown. */
  checked: boolean;
  onChange: (next: boolean) => void;
  /** How many players are hidden right now. Shown as a "(N)" hint next
   *  to the label while the toggle is off, so a coach knows the roster
   *  is being trimmed (and by how much). */
  hiddenCount: number;
  /** Override the default label for non-player row lists if ever needed. */
  label?: string;
}

/** Shared "Mostrar jugadores sin datos" checkbox used across the team
 *  report widgets that render a per-player row list. Off by default —
 *  the squad list reads cleaner without the silent "—" rows; toggling
 *  on reveals the full plantel. Mirrors the original inline toggle in
 *  TeamRosterMatrix so the control looks identical everywhere. */
export default function ShowNoDataToggle({
  checked,
  onChange,
  hiddenCount,
  label = "Mostrar jugadores sin datos",
}: Props) {
  return (
    <label className={styles.toggle}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {!checked && hiddenCount > 0 && (
          <span className={styles.toggleHint}> ({hiddenCount})</span>
        )}
      </span>
    </label>
  );
}
