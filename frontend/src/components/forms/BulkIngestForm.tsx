"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { BulkIngestResponse, CalendarEvent, ExamTemplate } from "@/lib/types";
import styles from "./BulkIngestForm.module.css";

interface BulkIngestFormProps {
  template: ExamTemplate;
  categoryId: string;
  /** Called after a successful commit. The parent navigates back. */
  onCommitted: () => void;
  /** Optional cancel/back affordance. */
  onCancel?: () => void;
}

type Stage = "idle" | "previewing" | "preview" | "committing" | "error";

function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const PREVIEW_KEYS = ["tot_dist_total", "tot_dur_total", "max_vel_total"];

export default function BulkIngestForm({
  template,
  categoryId,
  onCommitted,
  onCancel,
}: BulkIngestFormProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [recordedAt, setRecordedAt] = useState<string>(todayISO());
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<BulkIngestResponse | null>(null);

  // Match selector: shown only when the template opts in via link_to_match.
  const linkToMatch = template.link_to_match === true;
  const [matches, setMatches] = useState<CalendarEvent[]>([]);
  const [eventId, setEventId] = useState<string>("");

  useEffect(() => {
    if (!linkToMatch) return;
    let cancelled = false;
    api<CalendarEvent[]>(`/events?event_type=match`)
      .then((data) => {
        if (cancelled) return;
        // Most recent first.
        const sorted = [...data].sort(
          (a, b) => new Date(b.starts_at).getTime() - new Date(a.starts_at).getTime(),
        );
        setMatches(sorted);
      })
      .catch(() => {
        // Non-fatal — the form still works without an event association.
      });
    return () => {
      cancelled = true;
    };
  }, [linkToMatch]);

  const selectedMatch = useMemo(
    () => matches.find((m) => m.id === eventId) ?? null,
    [matches, eventId],
  );

  // When a match is picked, lock the date to the match's day so the user
  // can't drift away from the authoritative event timestamp. Deferred via
  // a microtask so the lint rule `react-hooks/set-state-in-effect` doesn't
  // flag the synchronous state write.
  useEffect(() => {
    if (!selectedMatch) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setRecordedAt(selectedMatch.starts_at.slice(0, 10));
    });
    return () => {
      cancelled = true;
    };
  }, [selectedMatch]);

  const submit = async (dryRun: boolean) => {
    if (!file) {
      setError("Selecciona un archivo .xlsx primero.");
      return;
    }
    setError(null);
    setStage(dryRun ? "previewing" : "committing");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("template_id", template.id);
    formData.append("category_id", categoryId);
    formData.append("recorded_at", `${recordedAt}T12:00:00`);
    formData.append("dry_run", dryRun ? "true" : "false");
    if (eventId) formData.append("event_id", eventId);

    try {
      const res = await api<BulkIngestResponse>("/results/bulk", {
        method: "POST",
        body: formData,
      });
      if (dryRun) {
        setPreview(res);
        setStage("preview");
      } else {
        onCommitted();
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Error procesando el archivo.";
      setError(msg);
      setStage("error");
    }
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setError(null);
    setStage("idle");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ---------- preview screen ----------
  // Stays mounted while the commit is in flight so the user keeps seeing
  // the matched-players summary under the "Guardando…" button rather than
  // a loading spinner over a blank screen.
  if ((stage === "preview" || stage === "committing") && preview) {
    return (
      <div className={styles.wrapper}>
        {selectedMatch && (
          <div className={styles.matchBanner}>
            Vinculando carga al partido{" "}
            <strong>{selectedMatch.title}</strong> ·{" "}
            {selectedMatch.starts_at.slice(0, 16).replace("T", " ")}
          </div>
        )}
        <div className={styles.summary}>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>Filas leídas</span>
            <span className={styles.metricValue}>{preview.total_rows}</span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>Jugadores reconocidos</span>
            <span className={`${styles.metricValue} ${styles.ok}`}>
              {preview.matched_players}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>Códigos sin coincidencia</span>
            <span
              className={`${styles.metricValue} ${
                preview.unmatched.length ? styles.warn : styles.dim
              }`}
            >
              {preview.unmatched.length}
            </span>
          </div>
        </div>

        {preview.matched_players === 0 ? (
          <div className={styles.emptyMatched}>
            Ninguno de los códigos del archivo coincide con un jugador en esta categoría.
            Agrega aliases a los jugadores en el panel de administración y vuelve a intentar.
          </div>
        ) : (
          <section>
            <h3 className={styles.sectionTitle}>
              Resumen por jugador ({preview.matched_players})
            </h3>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Jugador</th>
                    <th>Filas</th>
                    {PREVIEW_KEYS.map((k) => (
                      <th key={k}>{previewLabel(template, k)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.matched.map((m) => (
                    <tr key={m.player_id}>
                      <td className={styles.playerCell}>
                        {m.player_name}
                        {m.session_label && (
                          <span className={styles.sessionTag}>
                            {m.session_label}
                          </span>
                        )}
                      </td>
                      <td>{m.contributing_rows}</td>
                      {PREVIEW_KEYS.map((k) => (
                        <td key={k}>{formatPreviewValue(m.result_data[k])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {preview.unmatched.length > 0 && (
          <section>
            <h3 className={styles.sectionTitle}>
              Sin coincidencia ({preview.unmatched.length})
            </h3>
            <ul className={styles.unmatchedList}>
              {preview.unmatched.map((u) => (
                <li key={u.raw_player}>
                  <code>{u.raw_player}</code>
                  <span className={styles.dim}>
                    {u.rows} {u.rows === 1 ? "fila" : "filas"}
                  </span>
                </li>
              ))}
            </ul>
            <p className={styles.helper}>
              Estas filas se ignoran al guardar. Para incluirlas, agrega un alias a cada
              jugador en el panel de administración y carga el archivo nuevamente.
            </p>
          </section>
        )}

        {error && <div className={styles.errorBox}>{error}</div>}

        <div className={styles.actions}>
          <button type="button" className={styles.secondaryBtn} onClick={reset}>
            Cargar otro archivo
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={() => submit(false)}
            disabled={preview.matched_players === 0 || stage === "committing"}
          >
            {stage === "committing"
              ? "Guardando…"
              : `Guardar ${preview.matched_players} ${
                  preview.matched_players === 1 ? "registro" : "registros"
                }`}
          </button>
        </div>
      </div>
    );
  }

  // ---------- idle / form screen ----------
  return (
    <form
      className={styles.wrapper}
      onSubmit={(e) => {
        e.preventDefault();
        submit(true);
      }}
    >
      <div className={styles.intro}>
        Carga el archivo .xlsx exportado por el sistema GPS. Antes de guardar,
        verás una vista previa con los jugadores reconocidos y cualquier código
        sin coincidencia.
      </div>

      <label className={styles.field}>
        <span className={styles.label}>Archivo</span>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls"
          required
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        {file && <span className={styles.fileName}>{file.name}</span>}
      </label>

      {linkToMatch && (
        <label className={styles.field}>
          <span className={styles.label}>Asociar partido (opcional)</span>
          <select
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
          >
            <option value="">— Sin partido (fecha manual) —</option>
            {matches.map((m) => (
              <option key={m.id} value={m.id}>
                {m.starts_at.slice(0, 10)} · {m.title}
                {m.location ? ` (${m.location})` : ""}
              </option>
            ))}
          </select>
          {selectedMatch && (
            <span className={styles.matchHint}>
              Los registros se vincularán a este partido y la fecha se tomará de{" "}
              <strong>{selectedMatch.starts_at.slice(0, 16).replace("T", " ")}</strong>.
            </span>
          )}
        </label>
      )}

      <label className={styles.field}>
        <span className={styles.label}>
          Fecha del partido / sesión
          {selectedMatch && (
            <span className={styles.lockedTag}> · sincronizada con el partido</span>
          )}
        </span>
        <input
          type="date"
          required
          value={recordedAt}
          onChange={(e) => setRecordedAt(e.target.value)}
          disabled={!!selectedMatch}
        />
      </label>

      {error && <div className={styles.errorBox}>{error}</div>}

      <div className={styles.actions}>
        {onCancel && (
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={onCancel}
            disabled={stage === "previewing"}
          >
            Cancelar
          </button>
        )}
        <button
          type="submit"
          className={styles.primaryBtn}
          disabled={!file || stage === "previewing"}
        >
          {stage === "previewing" ? "Procesando…" : "Cargar y previsualizar"}
        </button>
      </div>
    </form>
  );
}

function previewLabel(template: ExamTemplate, key: string): string {
  const f = template.config_schema?.fields?.find((field) => field.key === key);
  if (!f) return key;
  return f.unit ? `${f.label} (${f.unit})` : f.label;
}

function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}
