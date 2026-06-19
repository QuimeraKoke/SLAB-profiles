"use client";

import React, { useState } from "react";

import { getToken } from "@/lib/api";

import styles from "./DownloadPdfButton.module.css";

interface Props {
  /** Path relative to /api (e.g. `/reports/medico/team.docx?...`). */
  endpoint: string;
  /** Suggested filename — browser uses Content-Disposition if present,
   *  but this gives us a sensible fallback when the header is missing. */
  filename: string;
  /** Optional label override; defaults to "Descargar Word". */
  label?: string;
  disabled?: boolean;
}

/**
 * Triggers an editable Word (.docx) report download by fetching the
 * endpoint with the JWT bearer token (so we honor scoping) and feeding
 * the response to a temporary `<a download>`. The fetch happens
 * client-side because the API lives at a different origin and a plain
 * `<a href>` wouldn't carry the auth header. (Reports export as Word so
 * staff can edit and annotate them; the symbol name is kept for now.)
 */
export default function DownloadPdfButton({
  endpoint, filename, label, disabled,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "")
        ?? "http://localhost:8000/api";
      const token = getToken();
      const headers = new Headers();
      headers.set(
        "Accept",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      );
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const res = await fetch(`${apiUrl}${endpoint}`, { headers });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const blob = await res.blob();
      // Trigger download. The server's Content-Disposition usually
      // wins for the filename; we set `download=` as a fallback for
      // browsers that don't honor the header on cross-origin fetches.
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Word download failed:", err);
      setError("No se pudo generar el documento. Intentá nuevamente.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className={styles.wrapper}>
      <button
        type="button"
        className={styles.button}
        onClick={onClick}
        disabled={busy || disabled}
        title="Descargar el reporte como documento Word editable"
      >
        <span className={styles.icon}>📝</span>
        {busy ? "Generando…" : (label ?? "Descargar Word")}
      </button>
      {error && <span className={styles.error}>{error}</span>}
    </span>
  );
}
