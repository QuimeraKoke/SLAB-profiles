"use client";

import React, { useState } from "react";

import {
  buildFilename,
  buildWorkbook,
  type ExportMeta,
} from "@/lib/export/teamReport";
import type { TeamReportSection } from "@/lib/types";

import styles from "./DownloadExcelButton.module.css";

interface Props {
  deptSlug: string;
  sections: TeamReportSection[];
  meta: Omit<ExportMeta, "generatedAt">;
  disabled?: boolean;
}

/** "Descargar Excel" — dynamically imports SheetJS on click so the
 *  ~500 KB library only loads when the user actually wants the file.
 *  No-op when there are no widgets (button stays disabled). */
export default function DownloadExcelButton({
  deptSlug, sections, meta, disabled,
}: Props) {
  const [busy, setBusy] = useState(false);

  async function onClick() {
    if (busy) return;
    setBusy(true);
    try {
      // Dynamic import — keeps xlsx out of the initial bundle.
      const XLSX = await import("xlsx");
      const generatedAt = new Date();
      const wb = buildWorkbook(XLSX, sections, { ...meta, generatedAt });
      XLSX.writeFile(wb, buildFilename(deptSlug, generatedAt));
    } catch (err) {
      // Surface the error in dev; for the user a silent failure is fine
      // (the click just won't produce a file — easy to retry).
      console.error("Excel export failed:", err);
    } finally {
      setBusy(false);
    }
  }

  const hasWidgets = sections.some((s) => s.widgets.length > 0);

  return (
    <button
      type="button"
      className={styles.button}
      onClick={onClick}
      disabled={busy || disabled || !hasWidgets}
      title={hasWidgets ? "Descargar todos los widgets en un archivo Excel" : "No hay datos para exportar"}
    >
      <span className={styles.icon}>📥</span>
      {busy ? "Generando…" : "Descargar Excel"}
    </button>
  );
}
