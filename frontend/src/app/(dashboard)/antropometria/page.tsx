"use client";

import React, { useRef, useState } from "react";
import {
  UploadCloud, FileSpreadsheet, RotateCcw, Download,
  CheckCircle2, AlertTriangle,
} from "lucide-react";

import { api, ApiError, getToken } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { useToast } from "@/components/ui/Toast/Toast";
import styles from "./page.module.css";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

interface PlayerRow {
  excel_name: string;
  player: string;
  player_id: string;
  category: string | null;
  new: number;
  dates: string[];
}
interface PentaUploadResult {
  club: string;
  template: string;
  sheet: string;
  rows_read: number;
  created: number;
  skipped_existing: number;
  skipped_duplicate_in_file: number;
  skipped_incomplete: number;
  skipped_undated: number;
  players: PlayerRow[];
  unmatched: { name: string; rows: number }[];
  alerts_fired: number;
  committed: boolean;
  dry_run: boolean;
}

type Stage = "idle" | "previewing" | "preview" | "committing";

export default function AntropometriaPage() {
  const { categoryId, categories } = useCategoryContext();
  // The context exposes ids only; the name is just for the "plantilla para X"
  // chip on the template download.
  const categoryName =
    categories.find((c) => c.id === categoryId)?.name ?? null;
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PentaUploadResult | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);

  async function send(dryRun: boolean) {
    if (!file) {
      setError("Selecciona un archivo .xlsx primero.");
      return;
    }
    setError(null);
    setStage(dryRun ? "previewing" : "committing");

    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", dryRun ? "true" : "false");
    try {
      const res = await api<PentaUploadResult>("/pentacompartimental/upload", {
        method: "POST",
        body: form,
      });
      if (dryRun) {
        setPreview(res);
        setStage("preview");
      } else {
        toast.success(
          `${res.created} evaluación${res.created === 1 ? "" : "es"} antropométrica${
            res.created === 1 ? "" : "s"
          } cargada${res.created === 1 ? "" : "s"}.`,
        );
        reset();
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Error procesando el archivo.",
      );
      setStage("idle");
    }
  }

  function reset() {
    setFile(null);
    setPreview(null);
    setError(null);
    setStage("idle");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  /** Template download needs the auth header, so it can't be a plain <a href>. */
  async function downloadTemplate() {
    try {
      const qs = categoryId ? `?category_id=${categoryId}` : "";
      const res = await fetch(`${API_URL}/pentacompartimental/template.xlsx${qs}`, {
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "plantilla_5componentes.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("No se pudo descargar la plantilla.");
    }
  }

  const busy = stage === "previewing" || stage === "committing";
  const nothingToDo = preview != null && preview.created === 0;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.h1}>Cargar antropometría</h1>
          <p className={styles.sub}>
            Sube el informe de 5 componentes (hoja{" "}
            <strong>Modelo 5 componentes</strong>). Cada fila es una evaluación
            con su fecha, así que un archivo puede traer varias fechas por
            jugador. Las 5 masas e índices se recalculan en SLAB — solo se leen
            las 27 medidas ISAK.
          </p>
        </div>
        {categoryName && (
          <span className={styles.catChip}>
            Plantilla para <strong>{categoryName}</strong>
          </span>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {stage !== "preview" && (
        <div className={styles.dropzone}>
          <input
            ref={fileInputRef}
            id="penta-file"
            type="file"
            accept=".xlsx"
            className={styles.fileInput}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setError(null);
            }}
          />
          <label htmlFor="penta-file" className={styles.fileLabel}>
            <UploadCloud size={30} aria-hidden="true" />
            {file ? "Cambiar archivo" : "Elegir archivo .xlsx"}
          </label>
          {file && (
            <span className={styles.fileChosen}>
              <FileSpreadsheet size={14} aria-hidden="true" />
              {file.name}
            </span>
          )}
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={!file || busy}
              onClick={() => send(true)}
            >
              {stage === "previewing" ? "Analizando…" : "Previsualizar"}
            </button>
            <button
              type="button"
              className={styles.ghostBtn}
              onClick={downloadTemplate}
            >
              <Download size={14} aria-hidden="true" />
              Descargar plantilla
            </button>
          </div>
          <p className={styles.hint}>
            No se sobrescribe nada: una evaluación que ya existe para el mismo
            jugador y fecha se omite, así que volver a subir el mismo informe no
            duplica datos.
          </p>
        </div>
      )}

      {preview && (
        <div className={styles.previewWrap}>
          <div className={styles.summary}>
            <Metric label="Filas leídas" value={preview.rows_read} />
            <Metric
              label="Nuevas a crear"
              value={preview.created}
              tone={preview.created > 0 ? "ok" : "dim"}
            />
            <Metric
              label="Ya existían"
              value={preview.skipped_existing}
              tone="dim"
            />
            <Metric label="Jugadores" value={preview.players.length} />
            {preview.unmatched.length > 0 && (
              <Metric
                label="Sin match"
                value={preview.unmatched.length}
                tone="warn"
              />
            )}
          </div>

          {(preview.skipped_incomplete > 0 || preview.skipped_undated > 0) && (
            <p className={styles.hint}>
              Se omitieron{" "}
              {preview.skipped_incomplete > 0 && (
                <>
                  <strong>{preview.skipped_incomplete}</strong> fila(s) sin peso
                  o talla
                </>
              )}
              {preview.skipped_incomplete > 0 && preview.skipped_undated > 0 && " y "}
              {preview.skipped_undated > 0 && (
                <>
                  <strong>{preview.skipped_undated}</strong> fila(s) sin fecha
                  legible
                </>
              )}
              .
            </p>
          )}

          {preview.unmatched.length > 0 && (
            <div>
              <h2 className={styles.sectionTitle}>
                <AlertTriangle size={14} aria-hidden="true" /> Nombres sin match
              </h2>
              <p className={styles.hint}>
                Estas filas no se importan. Revisa que el nombre del informe
                coincida con el del plantel.
              </p>
              <div className={styles.chips}>
                {preview.unmatched.map((u) => (
                  <span key={u.name} className={styles.chipWarn}>
                    {u.name} ({u.rows})
                  </span>
                ))}
              </div>
            </div>
          )}

          {preview.players.length > 0 && (
            <div>
              <h2 className={styles.sectionTitle}>Evaluaciones nuevas</h2>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Jugador</th>
                      <th>Categoría</th>
                      <th>Nuevas</th>
                      <th>Fechas</th>
                      <th>Nombre en el informe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.players.map((p) => (
                      <tr key={p.player_id}>
                        <td className={styles.playerCell}>{p.player}</td>
                        <td className={styles.dim}>{p.category ?? "—"}</td>
                        <td>
                          <span className={styles.badgeNew}>+{p.new}</span>
                        </td>
                        <td className={styles.dim}>{p.dates.join(", ")}</td>
                        <td className={styles.dim}>{p.excel_name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {nothingToDo && (
            <div className={styles.emptyState}>
              <CheckCircle2 size={16} aria-hidden="true" />
              No hay evaluaciones nuevas: todo lo del archivo ya estaba
              registrado.
            </div>
          )}

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={busy || nothingToDo}
              onClick={() => send(false)}
            >
              {stage === "committing"
                ? "Guardando…"
                : `Confirmar y guardar ${preview.created}`}
            </button>
            <button type="button" className={styles.ghostBtn} onClick={reset}>
              <RotateCcw size={14} aria-hidden="true" />
              Empezar de nuevo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "ok" | "warn" | "dim";
}) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span
        className={`${styles.metricValue} ${tone ? styles[tone] : ""}`.trim()}
      >
        {value}
      </span>
    </div>
  );
}
