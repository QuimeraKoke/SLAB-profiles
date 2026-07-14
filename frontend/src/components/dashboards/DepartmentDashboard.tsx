"use client";

import React from "react";

import type { DashboardSection } from "@/lib/types";
import SectionGroup from "./SectionGroup";
import styles from "./DepartmentDashboard.module.css";

interface DepartmentDashboardProps {
  sections: DashboardSection[];
  /** Player whose profile hosts this dashboard — enables per-player
   *  widget features like the position-comparison toggle. */
  playerId?: string;
  /** §5b — panel-builder edit mode + refetch trigger. */
  editMode?: boolean;
  onChanged?: () => void;
}

export default function DepartmentDashboard({ sections, playerId, editMode = false, onChanged }: DepartmentDashboardProps) {
  if (sections.length === 0) {
    return (
      <div className={styles.empty}>
        Este layout no tiene secciones todavía. Configúralo desde el panel de administración.
      </div>
    );
  }

  return (
    <div className={styles.dashboard}>
      {sections.map((section) => (
        <SectionGroup
          key={section.id}
          section={section}
          playerId={playerId}
          editMode={editMode}
          onChanged={onChanged}
        />
      ))}
    </div>
  );
}
