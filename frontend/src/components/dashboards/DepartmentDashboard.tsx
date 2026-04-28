"use client";

import React from "react";

import type { DashboardSection } from "@/lib/types";
import SectionGroup from "./SectionGroup";
import styles from "./DepartmentDashboard.module.css";

interface DepartmentDashboardProps {
  sections: DashboardSection[];
}

export default function DepartmentDashboard({ sections }: DepartmentDashboardProps) {
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
        <SectionGroup key={section.id} section={section} />
      ))}
    </div>
  );
}
