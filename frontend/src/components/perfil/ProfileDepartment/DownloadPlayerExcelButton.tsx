"use client";

import React, { useState } from "react";

import {
  buildPlayerFilename,
  buildPlayerWorkbook,
} from "@/lib/export/playerReport";
import type { DashboardSection, Department } from "@/lib/types";

import styles from "./DownloadPlayerExcelButton.module.css";

interface Props {
  playerName: string;
  department: Department;
  sections: DashboardSection[];
  dateFrom: string;
  dateTo: string;
  disabled?: boolean;
}

/** "Descargar Excel" for the per-player department view. Same dynamic
 *  import strategy as the team-report button — keeps SheetJS out of
 *  the initial bundle. */
export default function DownloadPlayerExcelButton({
  playerName,
  department,
  sections,
  dateFrom,
  dateTo,
  disabled,
}: Props) {
  const [busy, setBusy] = useState(false);

  async function onClick() {
    if (busy) return;
    setBusy(true);
    try {
      const XLSX = await import("xlsx");
      const generatedAt = new Date();
      const wb = buildPlayerWorkbook(XLSX, sections, {
        playerName,
        department,
        dateFrom,
        dateTo,
        generatedAt,
      });
      XLSX.writeFile(
        wb,
        buildPlayerFilename(playerName, department.slug, generatedAt),
      );
    } catch (err) {
      console.error("Player Excel export failed:", err);
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
      title={hasWidgets ? "Descargar los widgets de este departamento en un archivo Excel" : "No hay datos para exportar"}
    >
      <span className={styles.icon}>📥</span>
      {busy ? "Generando…" : "Descargar Excel"}
    </button>
  );
}
