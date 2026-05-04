"use client";

import React, { useEffect, useMemo, useState } from "react";

import DynamicUploader from "@/components/forms/DynamicUploader";
import Modal from "@/components/ui/Modal/Modal";
import { api, ApiError } from "@/lib/api";
import type { ExamField, ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./ResultsHistoryPanel.module.css";

interface Props {
  template: ExamTemplate;
  playerId: string;
  /** Default state of the <details> wrapper. Defaults to closed. */
  defaultOpen?: boolean;
}

const PAGE_SIZE = 8;

/**
 * Collapsible "previous entries" panel for a given (player, template).
 *
 * Used on the registrar page so the doctor can review and edit past
 * readings without leaving the data-entry view. Owns its own fetch +
 * edit modal + delete logic — drop-in component.
 */
export default function ResultsHistoryPanel({
  template,
  playerId,
  defaultOpen = false,
}: Props) {
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ExamResult | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setResults(null);
    setError(null);
    api<ExamResult[]>(`/players/${playerId}/results?template=${template.id}`)
      .then((data) => {
        if (cancelled) return;
        const sorted = [...data].sort(
          (a, b) =>
            new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime(),
        );
        setResults(sorted);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Error al cargar el historial");
        setResults([]);
      });
    return () => {
      cancelled = true;
    };
  }, [playerId, template.id, refreshKey]);

  const columns = useMemo(
    () => pickColumns(template.config_schema?.fields ?? []),
    [template.config_schema],
  );

  const list = results ?? [];
  const totalPages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const visible = list.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  const refresh = () => setRefreshKey((k) => k + 1);

  const handleSaved = () => {
    setEditing(null);
    refresh();
  };

  const handleDelete = async (result: ExamResult) => {
    if (!confirm("¿Borrar este registro? Esta acción no se puede deshacer.")) {
      return;
    }
    setDeletingId(result.id);
    setError(null);
    try {
      await api(`/results/${result.id}`, { method: "DELETE" });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al borrar");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <details className={styles.panel} open={defaultOpen}>
      <summary className={styles.summary}>
        <span className={styles.summaryTitle}>
          Historial · {template.name}
        </span>
        <span className={styles.summaryCount}>
          {results === null
            ? "…"
            : `${list.length} ${list.length === 1 ? "registro" : "registros"}`}
        </span>
      </summary>

      <div className={styles.body}>
        {error && <div className={styles.error}>{error}</div>}

        {results === null ? (
          <div className={styles.muted}>Cargando…</div>
        ) : list.length === 0 ? (
          <div className={styles.muted}>Sin registros previos para este jugador.</div>
        ) : (
          <>
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    {columns.map((c) => (
                      <th key={c.key}>{c.label}</th>
                    ))}
                    <th aria-label="Acciones" className={styles.rowActionsHead} />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.id}>
                      <td className={styles.dateCell}>{formatDate(r.recorded_at)}</td>
                      {columns.map((c) => {
                        const raw = r.result_data[c.key];
                        return (
                          <td
                            key={c.key}
                            title={raw === null || raw === undefined ? "" : String(raw)}
                          >
                            {truncate(formatValue(raw), 36)}
                            {c.unit && raw !== null && raw !== undefined && raw !== ""
                              ? ` ${c.unit}`
                              : ""}
                          </td>
                        );
                      })}
                      <td className={styles.rowActions}>
                        <button
                          type="button"
                          className={styles.rowBtn}
                          onClick={() => setEditing(r)}
                          aria-label="Editar registro"
                          title="Editar"
                        >
                          ✏️
                        </button>
                        <button
                          type="button"
                          className={`${styles.rowBtn} ${styles.rowBtnDanger}`}
                          onClick={() => handleDelete(r)}
                          disabled={deletingId === r.id}
                          aria-label="Borrar registro"
                          title="Borrar"
                        >
                          {deletingId === r.id ? "…" : "🗑"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className={styles.pagination}>
                <button
                  type="button"
                  className={styles.pageBtn}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  aria-label="Página anterior"
                >
                  ‹
                </button>
                <span className={styles.pageInfo}>
                  {safePage + 1} / {totalPages}
                </span>
                <button
                  type="button"
                  className={styles.pageBtn}
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={safePage >= totalPages - 1}
                  aria-label="Página siguiente"
                >
                  ›
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <Modal
        open={editing !== null}
        title={`Editar — ${template.name}`}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <DynamicUploader
            template={template}
            playerId={playerId}
            existingResult={editing}
            onSaved={handleSaved}
            onCancel={() => setEditing(null)}
          />
        )}
      </Modal>
    </details>
  );
}

// Mirror DepartmentCard's column-picking heuristic so the registrar history
// table feels visually coherent with the per-department card on the profile.
function pickColumns(fields: ExamField[]): ExamField[] {
  const subject = fields.find((f) => f.key === "asunto" || f.key === "objetivo");
  const status = fields.find((f) => f.key === "estado");
  const calculated = fields.filter((f) => f.type === "calculated");
  const otherShort = fields.filter(
    (f) =>
      f !== subject &&
      f !== status &&
      f.type !== "calculated" &&
      f.type !== "date" &&
      !(f.type === "text" && f.multiline),
  );

  const picked: ExamField[] = [];
  if (subject) picked.push(subject);
  if (status) picked.push(status);
  for (const f of calculated) {
    if (picked.length >= 4) break;
    picked.push(f);
  }
  for (const f of otherShort) {
    if (picked.length >= 4) break;
    picked.push(f);
  }
  return picked.slice(0, 4);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + "…";
}
