"use client";

import React, { useState } from "react";

import DynamicUploader from "@/components/forms/DynamicUploader";
import type { ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./DashboardEntryPanel.module.css";

interface DashboardEntryPanelProps {
  templates: ExamTemplate[];
  playerId: string;
  onResultSaved: (result: ExamResult) => void;
}

export default function DashboardEntryPanel({
  templates,
  playerId,
  onResultSaved,
}: DashboardEntryPanelProps) {
  const [activeTemplateId, setActiveTemplateId] = useState<string | null>(null);

  if (templates.length === 0) return null;

  const activeTemplate = templates.find((t) => t.id === activeTemplateId);

  if (activeTemplate) {
    return (
      <div className={styles.panel}>
        <DynamicUploader
          template={activeTemplate}
          playerId={playerId}
          onSaved={(r) => {
            onResultSaved(r);
            setActiveTemplateId(null);
          }}
          onCancel={() => setActiveTemplateId(null)}
        />
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <div className={styles.label}>Registrar nueva entrada</div>
      <div className={styles.buttonRow}>
        {templates.map((t) => (
          <button
            key={t.id}
            type="button"
            className={styles.entryBtn}
            onClick={() => setActiveTemplateId(t.id)}
          >
            + {t.name}
          </button>
        ))}
      </div>
    </div>
  );
}
