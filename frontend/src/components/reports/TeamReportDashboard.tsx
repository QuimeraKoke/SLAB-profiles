"use client";

import React from "react";

import type { TeamReportSection as TeamReportSectionType } from "@/lib/types";
import TeamReportSection from "./TeamReportSection";
import styles from "./TeamReportDashboard.module.css";

interface Props {
  sections: TeamReportSectionType[];
  /** Panel-builder edit mode (§2.c) — threads to per-widget arrange controls. */
  editMode?: boolean;
  /** Refetch trigger after a successful arrange mutation. */
  onChanged?: () => void;
  /** Open the edit modal for a widget (§5). */
  onEditWidget?: (widgetId: string) => void;
}

export default function TeamReportDashboard({ sections, editMode = false, onChanged, onEditWidget }: Props) {
  if (sections.length === 0) {
    return (
      <div className={styles.empty}>
        Este reporte no tiene secciones todavía. Agregá tu primer widget con
        “Agregar widget”, o configuralo desde administración.
      </div>
    );
  }

  return (
    <div className={styles.dashboard}>
      {sections.map((section) => (
        <TeamReportSection
          key={section.id}
          section={section}
          editMode={editMode}
          onChanged={onChanged}
          onEditWidget={onEditWidget}
        />
      ))}
    </div>
  );
}
