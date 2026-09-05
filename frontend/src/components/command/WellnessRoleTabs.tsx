"use client";

import React, { useRef } from "react";

import styles from "./WellnessRoleTabs.module.css";

export type WellnessRole = "checkin" | "checkout";

export const ROLE_LABEL: Record<WellnessRole, string> = {
  checkin: "Check-IN",
  checkout: "Check-OUT",
};

/**
 * Segmented control for the two wellness forms.
 *
 * Only the Formativo fills a post-session Check-OUT (RPE, carga interna,
 * molestias); Primer Equipo fills the Check-IN alone. So the backend reports
 * `wellness_roles` per category and this renders **nothing** when there is only
 * one — a lone tab labelled "Check-IN" is noise, not information.
 *
 * ARIA: a `role="tablist"` with arrow-key cycling, same contract as
 * `ProfileTabs`. It stays a separate component because that one is a
 * page-level bar (white card, 24px bottom margin) and this sits inside a KPI
 * card head.
 */
export default function WellnessRoleTabs({
  roles,
  active,
  onChange,
  label = "Formulario de wellness",
}: {
  roles: WellnessRole[];
  active: WellnessRole;
  onChange: (role: WellnessRole) => void;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  if (roles.length < 2) return null;

  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    const idx = roles.indexOf(active);
    if (idx < 0) return;
    let next: number | null = null;
    if (e.key === "ArrowRight") next = (idx + 1) % roles.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + roles.length) % roles.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = roles.length - 1;
    else return;
    e.preventDefault();
    onChange(roles[next]);
    ref.current
      ?.querySelector<HTMLButtonElement>(`#wtab-${roles[next]}`)
      ?.focus();
  };

  return (
    <div ref={ref} role="tablist" aria-label={label} className={styles.tabs}>
      {roles.map((r) => (
        <button
          key={r}
          id={`wtab-${r}`}
          type="button"
          role="tab"
          aria-selected={r === active}
          tabIndex={r === active ? 0 : -1}
          onClick={() => onChange(r)}
          onKeyDown={onKeyDown}
          className={`${styles.tab} ${r === active ? styles.active : ""}`}
        >
          {ROLE_LABEL[r]}
        </button>
      ))}
    </div>
  );
}
