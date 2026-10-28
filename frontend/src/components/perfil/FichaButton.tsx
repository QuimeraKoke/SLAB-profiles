"use client";

import React, { useState } from "react";
import { FileImage } from "lucide-react";

import { getToken } from "@/lib/api";
import styles from "@/components/reports/DownloadPdfButton.module.css";

/** Departments with a ficha — mirrors `dashboards.pdf.ficha.SPECS`. The
 *  notes-only ones (Kinesiología, Masoterapia, Podología) have none. */
export const FICHA_DEPARTMENTS = new Set(["fisico", "nutricional", "psicosocial", "medico", "tactico"]);

/**
 * Downloads the player's "ficha integral" — the one-page infographic (PDF):
 * per department, or general when `department` is omitted (Resumen).
 * Fetched with the bearer token, like the Word reports: the API is on
 * another origin and a plain link wouldn't carry it.
 */
export default function FichaButton({ playerId, playerName, department }: {
  playerId: string;
  playerName: string;
  department?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (department && !FICHA_DEPARTMENTS.has(department)) return null;

  async function onClick() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";
      const headers = new Headers({ Accept: "application/pdf" });
      const token = getToken();
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const qs = department ? `?department=${encodeURIComponent(department)}` : "";
      const res = await fetch(`${apiUrl}/players/${playerId}/ficha.pdf${qs}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `ficha-${department ?? "integral"}-${playerName}.pdf`.replace(/\s+/g, "_");
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("No se pudo generar la ficha. Intentá nuevamente.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className={styles.wrapper}>
      <button type="button" className={styles.button} onClick={onClick} disabled={busy}
        title="Descargar la ficha del jugador (infografía en PDF)">
        <FileImage size={14} aria-hidden="true" />
        {busy ? "Generando…" : department ? "Ficha (PDF)" : "Ficha integral (PDF)"}
      </button>
      {error && <span className={styles.error} role="alert">{error}</span>}
    </span>
  );
}
