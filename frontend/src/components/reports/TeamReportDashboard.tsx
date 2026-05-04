"use client";

import React from "react";

import type { TeamReportSection as TeamReportSectionType } from "@/lib/types";
import TeamReportSection from "./TeamReportSection";
import styles from "./TeamReportDashboard.module.css";

interface Props {
  sections: TeamReportSectionType[];
}

export default function TeamReportDashboard({ sections }: Props) {
  if (sections.length === 0) {
    return (
      <div className={styles.empty}>
        Este reporte no tiene secciones todavía. Configúralo desde el panel de
        administración (Dashboards → Team Report Layouts).
      </div>
    );
  }

  return (
    <div className={styles.dashboard}>
      {sections.map((section) => (
        <TeamReportSection key={section.id} section={section} />
      ))}
    </div>
  );
}
