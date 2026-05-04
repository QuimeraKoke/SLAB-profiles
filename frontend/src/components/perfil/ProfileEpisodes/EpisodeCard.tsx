"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import type {
  Episode,
  ExamResult,
  ExamTemplate,
} from "@/lib/types";
import styles from "./ProfileEpisodes.module.css";

const STAGE_LABEL: Record<string, string> = {
  injured: "Lesionado",
  recovery: "Recuperación",
  reintegration: "Reintegración",
  closed: "Cerrado",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-CL", {
    day: "2-digit", month: "short", year: "numeric",
  });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("es-CL", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function stageClass(stage: string): string {
  switch (stage) {
    case "injured": return styles.stage_injured;
    case "recovery": return styles.stage_recovery;
    case "reintegration": return styles.stage_reintegration;
    case "closed": return styles.stage_closed;
    default: return "";
  }
}

interface Props {
  episode: Episode;
  /** Required: handler for clicking Editar on a timeline row. The parent
   *  owns the edit modal so the same Modal component can be reused across
   *  consumers (Lesiones tab, InjuryPanel inside a registrar form, etc.). */
  onEdit: (result: ExamResult, template: ExamTemplate) => void;
  /** Optional — when set, "Actualizar etapa" renders as a `<Link>` (preserves
   *  right-click / ctrl-click semantics for the Lesiones tab). */
  continueHref?: string;
  /** Optional — when set (and `continueHref` isn't), "Actualizar etapa"
   *  renders as a button and fires this callback. Used by the InjuryPanel
   *  to open a modal instead of navigating away. */
  onContinue?: () => void;
}

/**
 * Episode summary card used by the Lesiones tab AND the in-form InjuryPanel.
 *
 * Renders the episode header + key dates + stage pill, an "Actualizar etapa"
 * action (if open) that's either a navigation link or an in-place callback,
 * and a collapsible timeline of every linked result with per-row Editar.
 */
export default function EpisodeCard({
  episode,
  onEdit,
  continueHref,
  onContinue,
}: Props) {
  const stageLabel = STAGE_LABEL[episode.stage] ?? episode.stage;
  const isOpen = episode.status === "open";

  const [showTimeline, setShowTimeline] = useState(false);
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [template, setTemplate] = useState<ExamTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!showTimeline || results !== null) return;
    let cancelled = false;
    Promise.all([
      api<ExamResult[]>(`/episodes/${episode.id}/results`),
      api<ExamTemplate>(`/templates/${episode.template_id}`),
    ])
      .then(([rs, tpl]) => {
        if (cancelled) return;
        // Server returns oldest-first; flip so newest is on top.
        setResults([...rs].reverse());
        setTemplate(tpl);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.message : "Error cargando historial");
      });
    return () => {
      cancelled = true;
    };
  }, [showTimeline, results, episode.id, episode.template_id]);

  const continueButton = isOpen && (
    continueHref ? (
      <Link href={continueHref} className={styles.linkBtn}>
        Actualizar etapa
      </Link>
    ) : onContinue ? (
      <button type="button" className={styles.linkBtn} onClick={onContinue}>
        Actualizar etapa
      </button>
    ) : null
  );

  return (
    <div className={`${styles.card} ${isOpen ? "" : styles.closed}`}>
      <div className={styles.cardHeader}>
        <div>
          <div className={styles.cardTitle}>{episode.title || "(sin título)"}</div>
          <div className={styles.cardSub}>{episode.template_name}</div>
        </div>
        <span className={`${styles.stagePill} ${stageClass(episode.stage)}`}>
          {stageLabel}
        </span>
      </div>
      <div className={styles.row}>
        <span className={styles.rowLabel}>Inicio</span>
        <span className={styles.rowValue}>{formatDate(episode.started_at)}</span>
      </div>
      {episode.ended_at && (
        <div className={styles.row}>
          <span className={styles.rowLabel}>Cierre</span>
          <span className={styles.rowValue}>{formatDate(episode.ended_at)}</span>
        </div>
      )}
      <div className={styles.row}>
        <span className={styles.rowLabel}>Resultados</span>
        <span className={styles.rowValue}>{episode.result_count}</span>
      </div>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.ghostBtn}
          onClick={() => setShowTimeline((v) => !v)}
        >
          {showTimeline ? "Ocultar historial" : "Ver historial"}
        </button>
        {continueButton}
      </div>

      {showTimeline && (
        <div className={styles.timeline}>
          <h5 className={styles.timelineTitle}>Historial</h5>
          {loadError && <div className={styles.error}>{loadError}</div>}
          {results === null && !loadError && (
            <div className={styles.timelineEmpty}>Cargando…</div>
          )}
          {results && results.length === 0 && (
            <div className={styles.timelineEmpty}>Sin entradas.</div>
          )}
          {results && template && results.map((r) => {
            const stage = String(r.result_data?.stage ?? "");
            const stageLbl = STAGE_LABEL[stage] ?? stage;
            const noteSnippet = String(r.result_data?.notes ?? "")
              .trim().slice(0, 80);
            return (
              <div key={r.id} className={styles.timelineRow}>
                <div className={styles.timelineMain}>
                  <span>
                    <strong>{formatDateTime(r.recorded_at)}</strong>
                    {stageLbl && ` · ${stageLbl}`}
                  </span>
                  {noteSnippet && (
                    <span className={styles.timelineSub}>
                      {noteSnippet}
                      {noteSnippet.length === 80 ? "…" : ""}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className={styles.ghostBtn}
                  onClick={() => onEdit(r, template)}
                >
                  Editar
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Re-export for parents that want to format episode dates the same way.
export { formatDateTime };
