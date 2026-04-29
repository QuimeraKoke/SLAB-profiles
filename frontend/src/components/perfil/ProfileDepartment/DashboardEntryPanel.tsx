"use client";

import React from "react";
import Link from "next/link";

import type { ExamTemplate } from "@/lib/types";
import styles from "./DashboardEntryPanel.module.css";

interface DashboardEntryPanelProps {
  templates: ExamTemplate[];
  playerId: string;
  departmentSlug: string;
}

export default function DashboardEntryPanel({
  templates,
  playerId,
  departmentSlug,
}: DashboardEntryPanelProps) {
  if (templates.length === 0) return null;

  return (
    <div className={styles.panel}>
      <div className={styles.label}>Registrar nueva entrada</div>
      <div className={styles.buttonRow}>
        {templates.map((t) => (
          <Link
            key={t.id}
            href={`/perfil/${playerId}/registrar/${t.id}?tab=${encodeURIComponent(departmentSlug)}`}
            className={styles.entryBtn}
          >
            + {t.name}
          </Link>
        ))}
      </div>
    </div>
  );
}
