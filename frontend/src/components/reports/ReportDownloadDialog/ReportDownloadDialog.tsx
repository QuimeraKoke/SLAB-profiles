"use client";

/**
 * "Descargar informe": one button, one dialog, every report.
 *
 * Reports used to download in one click with no say over the time span —
 * the profile's sent no dates at all (full history, dozens of pages). Here
 * the user picks:
 *  - the PERIOD (unless the page already fixes it — the team dashboard
 *    passes its own selector, `fixedPeriod`), defaulting to 30 days;
 *  - the FORMAT: Ejecutivo (1–2 pages, the default), Completo (every view
 *    with its data tables), and Excel when the caller supports it.
 */

import React, { useState } from "react";

import DateRangeControl, { lastDaysRange } from "@/components/common/DateRangeControl";
import type { DateRangeValue } from "@/components/common/DateRangeControl";
import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import { downloadFromApi } from "@/lib/download";

import styles from "./ReportDownloadDialog.module.css";

export type ReportFormat = "ejecutivo" | "completo";
type Choice = ReportFormat | "excel";

interface Props {
  /** Dialog title, e.g. "Informe de Físico". */
  title: string;
  buttonLabel?: string;
  /** API path for a Word format and period. */
  endpoint: (p: { dateFrom: string; dateTo: string; formato: ReportFormat }) => string;
  filename: (formato: ReportFormat) => string;
  /** The page's own period (team dashboard): shown, not chosen. */
  fixedPeriod?: { label: string; dateFrom: string; dateTo: string };
  defaultDays?: number;
  /** Optional data export for the same period. */
  excel?: (dateFrom: string, dateTo: string) => Promise<void>;
  disabled?: boolean;
}

const FORMATS: { value: Choice; label: string; hint: string }[] = [
  { value: "ejecutivo", label: "Ejecutivo", hint: "1–2 páginas: lo esencial, indicadores frente al período anterior, disponibilidad, alertas y gráficos clave." },
  { value: "completo", label: "Completo", hint: "Todas las vistas del panel, cada una con su gráfico y su tabla de datos." },
  { value: "excel", label: "Excel (datos)", hint: "Los datos de cada vista del panel, una hoja por gráfico." },
];

export default function ReportDownloadDialog({
  title, buttonLabel = "Descargar informe", endpoint, filename, fixedPeriod,
  defaultDays = 30, excel, disabled,
}: Props) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [range, setRange] = useState<DateRangeValue>(() => lastDaysRange(defaultDays));
  const [choice, setChoice] = useState<Choice>("ejecutivo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dateFrom = fixedPeriod?.dateFrom ?? range.date.from;
  const dateTo = fixedPeriod?.dateTo ?? range.date.to;
  const opciones = FORMATS.filter((f) => f.value !== "excel" || excel);

  async function descargar(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (choice === "excel") {
        await excel!(dateFrom, dateTo);
      } else {
        await downloadFromApi(endpoint({ dateFrom, dateTo, formato: choice }), filename(choice));
      }
      toast.success("Informe descargado.");
      setOpen(false);
    } catch (err) {
      console.error("Report download failed:", err);
      setError("No se pudo generar el informe. Intentá nuevamente.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className={styles.trigger} onClick={() => { setError(null); setOpen(true); }}
        disabled={disabled} aria-haspopup="dialog">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={styles.icon}>
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        {buttonLabel}
      </button>
      <Modal open={open} title={title} onClose={() => !busy && setOpen(false)}>
        <form className={styles.form} onSubmit={descargar}>
          <fieldset className={styles.group}>
            {/* The date control labels itself; the legend stays for screen readers. */}
            <legend className={fixedPeriod ? styles.legend : styles.srOnly}>Período</legend>
            {fixedPeriod ? (
              <p className={styles.fixed}>
                {fixedPeriod.label}
                <span className={styles.muted}> · el seleccionado en esta página</span>
              </p>
            ) : (
              <DateRangeControl value={range} onChange={setRange} />
            )}
            <p className={styles.muted}>Los indicadores se comparan con el período anterior de igual duración.</p>
          </fieldset>

          <fieldset className={styles.group}>
            <legend className={styles.legend}>Formato</legend>
            {opciones.map((f) => (
              <label key={f.value} className={`${styles.option} ${choice === f.value ? styles.selected : ""}`}>
                <input type="radio" name="formato" value={f.value} checked={choice === f.value}
                  onChange={() => setChoice(f.value)} />
                <span>
                  <span className={styles.optionLabel}>{f.label}</span>
                  <span className={styles.optionHint}>{f.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          {error && <p role="alert" className={styles.error}>{error}</p>}

          <div className={styles.actions}>
            <button type="button" className={styles.secondary} onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" className={styles.primary} disabled={busy || !dateFrom || !dateTo}>
              {busy ? "Generando…" : "Descargar"}
            </button>
          </div>
          {busy && choice !== "excel" && (
            <p className={styles.muted} aria-live="polite">
              El análisis se genera con IA la primera vez: puede tomar hasta un minuto.
            </p>
          )}
        </form>
      </Modal>
    </>
  );
}
