"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useToast } from "@/components/ui/Toast/Toast";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import Modal from "@/components/ui/Modal/Modal";
import type {
  Episode,
  ExamResult,
  ExamTemplate,
} from "@/lib/types";
import { advanceEpisodeStage } from "@/lib/injuryLog";
import InjuryLog from "./InjuryLog";
import styles from "./ProfileEpisodes.module.css";

const STAGE_LABEL: Record<string, string> = {
  injured: "Lesionado",
  recovery: "Recuperación",
  reintegration: "Return to Train",
  closed: "Return to Play",
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

/** Look up the display label for a categorical value from the template. */
function labelFor(template: ExamTemplate | null, key: string, value: unknown): string {
  const v = String(value ?? "").trim();
  if (!v || !template) return v;
  const f = (template.config_schema?.fields ?? []).find((f) => f.key === key);
  return (f?.option_labels as Record<string, string> | undefined)?.[v] ?? v;
}

/** Today as YYYY-MM-DD. */
function todayStr(): string {
  const n = new Date();
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(
    n.getDate(),
  ).padStart(2, "0")}`;
}

interface Props {
  episode: Episode;
  /** Panel variant: handler for clicking Editar on a timeline row. */
  onEdit?: (result: ExamResult, template: ExamTemplate) => void;
  /** When set, "Editar datos" / "Actualizar etapa" (panel) renders as a link. */
  continueHref?: string;
  /** Panel variant: "Actualizar etapa" fires this callback (opens a modal). */
  onContinue?: () => void;
  /** "panel" (default, InjuryPanel) keeps the legacy result timeline. "lesiones"
   *  (Lesiones tab) shows the structured ficha + a single bitácora timeline and
   *  a lightweight stage-only update. */
  variant?: "panel" | "lesiones";
  /** lesiones variant: called after a stage change so the parent refetches. */
  onChanged?: () => void;
}

/**
 * Episode summary card. Two variants:
 * - "panel" (InjuryPanel, registration sidebar): legacy behaviour — collapsible
 *   timeline of every linked result with per-row Editar + "Actualizar etapa".
 * - "lesiones" (Lesiones tab): structured ficha (definition + stage) whose ONLY
 *   routine edit is the stage; all evolution + documents live in the bitácora
 *   (one merged timeline with stage-transition markers).
 */
export default function EpisodeCard({
  episode,
  onEdit,
  continueHref,
  onContinue,
  variant = "panel",
  onChanged,
}: Props) {
  const stageLabel = episode.stage_label || STAGE_LABEL[episode.stage] || episode.stage;
  const isOpen = episode.status === "open";
  const isLesiones = variant === "lesiones";

  const { toast } = useToast();
  const { confirm } = useConfirm();
  const canEditEpisode = usePermission("exams.change_episode");

  // ── Legacy panel timeline ──────────────────────────────────────────────
  const [showTimeline, setShowTimeline] = useState(false);
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [panelTemplate, setPanelTemplate] = useState<ExamTemplate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ── Lesiones variant: template (for labels + stage options) + bitácora ──
  const [template, setTemplate] = useState<ExamTemplate | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [logRefresh, setLogRefresh] = useState(0);

  // ── availability ("disponible para ser citado") ────────────────────────
  const [availableAt, setAvailableAt] = useState<string | null>(episode.available_at);
  const [editingAvail, setEditingAvail] = useState(false);
  const [availDraft, setAvailDraft] = useState("");
  const [savingAvail, setSavingAvail] = useState(false);

  // ── Stage-change modal (lesiones variant) ──────────────────────────────
  const [stageOpen, setStageOpen] = useState(false);
  const [stageDraft, setStageDraft] = useState(episode.stage);
  const [stageDate, setStageDate] = useState(todayStr());
  const [savingStage, setSavingStage] = useState(false);
  const [closing, setClosing] = useState(false);

  async function saveAvailable(clear: boolean) {
    setSavingAvail(true);
    try {
      const res = await api<Episode>(`/episodes/${episode.id}`, {
        method: "PATCH",
        body: JSON.stringify({ available_at: clear ? "clear" : availDraft }),
      });
      setAvailableAt(res.available_at);
      setEditingAvail(false);
      toast.success(clear ? "Disponibilidad quitada." : "Marcado disponible para citar.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setSavingAvail(false);
    }
  }

  // Load template for the lesiones variant (labels + stage options + bitácora).
  useEffect(() => {
    if (!isLesiones) return;
    let cancelled = false;
    api<ExamTemplate>(`/templates/${episode.template_id}`)
      .then((tpl) => {
        if (!cancelled) setTemplate(tpl);
      })
      .catch(() => {
        /* non-fatal: the ficha still renders raw values */
      });
    return () => {
      cancelled = true;
    };
  }, [isLesiones, episode.template_id]);

  // Panel-variant lazy timeline load.
  useEffect(() => {
    if (isLesiones || !showTimeline || results !== null) return;
    let cancelled = false;
    Promise.all([
      api<ExamResult[]>(`/episodes/${episode.id}/results`),
      api<ExamTemplate>(`/templates/${episode.template_id}`),
    ])
      .then(([rs, tpl]) => {
        if (cancelled) return;
        setResults([...rs].reverse());
        setPanelTemplate(tpl);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.message : "Error cargando historial");
      });
    return () => {
      cancelled = true;
    };
  }, [isLesiones, showTimeline, results, episode.id, episode.template_id]);

  async function saveStage() {
    if (savingStage || !stageDraft) return;
    setSavingStage(true);
    try {
      await advanceEpisodeStage(episode.id, stageDraft, stageDate);
      setStageOpen(false);
      setLogRefresh((n) => n + 1);
      toast.success("Etapa actualizada.");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo actualizar la etapa.");
    } finally {
      setSavingStage(false);
    }
  }

  async function darDeAlta() {
    if (closing) return;
    const ok = await confirm({
      title: "Dar de alta",
      message: "¿Cerrar esta lesión y darla de alta? Pasará al histórico.",
      confirmLabel: "Dar de alta",
      variant: "danger",
    });
    if (!ok) return;
    setClosing(true);
    try {
      await advanceEpisodeStage(episode.id, "closed", todayStr());
      setLogRefresh((n) => n + 1);
      toast.success("Lesión cerrada (alta médica).");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo dar de alta.");
    } finally {
      setClosing(false);
    }
  }

  // The 6 clinical stages (with descriptions) for the picker. "closed" (Alta
  // médica) is the archival action, shown separately — not one of the stages.
  const stageField = template?.episode_config?.stage_field;
  const stageOptions: { value: string; label: string; description: string }[] = (() => {
    if (!template || !stageField) return [];
    const f = (template.config_schema?.fields ?? []).find((f) => f.key === stageField) as
      | { options?: string[]; option_labels?: Record<string, string>; option_descriptions?: Record<string, string> }
      | undefined;
    const opts = (f?.options ?? []) as string[];
    const labels = f?.option_labels ?? {};
    const descs = f?.option_descriptions ?? {};
    return opts
      .filter((o) => o !== "closed")
      .map((o) => ({ value: o, label: labels[o] ?? o, description: descs[o] ?? "" }));
  })();

  const availabilityRow = (
    <div className={styles.row}>
      <span className={styles.rowLabel}>Disponible p/ citar</span>
      <span className={styles.rowValue}>
        {editingAvail ? (
          <span className={styles.availEdit}>
            <input type="date" value={availDraft} onChange={(e) => setAvailDraft(e.target.value)} />
            <button
              type="button" className={styles.tinyBtn}
              disabled={savingAvail || !availDraft} onClick={() => saveAvailable(false)}
            >
              Guardar
            </button>
            <button type="button" className={styles.tinyBtn} onClick={() => setEditingAvail(false)}>
              Cancelar
            </button>
          </span>
        ) : availableAt ? (
          <span className={styles.availEdit}>
            {formatDate(availableAt)}
            {canEditEpisode && (
              <>
                <button
                  type="button" className={styles.tinyBtn}
                  onClick={() => { setAvailDraft(availableAt.slice(0, 10)); setEditingAvail(true); }}
                >
                  editar
                </button>
                <button
                  type="button" className={styles.tinyBtn}
                  disabled={savingAvail} onClick={() => saveAvailable(true)}
                >
                  quitar
                </button>
              </>
            )}
          </span>
        ) : canEditEpisode ? (
          <button
            type="button" className={styles.tinyBtn}
            onClick={() => { setAvailDraft(""); setEditingAvail(true); }}
          >
            Marcar disponible
          </button>
        ) : (
          <span className={styles.muted}>—</span>
        )}
      </span>
    </div>
  );

  // ── Lesiones variant render ────────────────────────────────────────────
  if (isLesiones) {
    const d = episode.latest_result_data || {};
    const region = labelFor(template, "body_part", d.body_part);
    const lado = labelFor(template, "lado", d.lado);
    const tipo = labelFor(template, "type", d.type);
    const severidad = labelFor(template, "severity", d.severity);
    const expected = d.expected_return_date ? String(d.expected_return_date) : null;

    return (
      <div
        className={`${styles.card} ${isOpen ? "" : styles.closed} ${
          showLog ? styles.cardExpanded : ""
        }`}
      >
        <div className={styles.cardHeader}>
          <div>
            <div className={styles.cardTitle}>{episode.title || "(sin título)"}</div>
            <div className={styles.cardSub}>{episode.template_name}</div>
          </div>
          <span className={`${styles.stagePill} ${stageClass(episode.stage)}`}>{stageLabel}</span>
        </div>

        <div className={styles.row}>
          <span className={styles.rowLabel}>Inicio</span>
          <span className={styles.rowValue}>{formatDate(episode.started_at)}</span>
        </div>
        {region && (
          <div className={styles.row}>
            <span className={styles.rowLabel}>Región</span>
            <span className={styles.rowValue}>{region}{lado && lado !== "NA" ? ` · ${lado}` : ""}</span>
          </div>
        )}
        {tipo && (
          <div className={styles.row}>
            <span className={styles.rowLabel}>Tipo</span>
            <span className={styles.rowValue}>{tipo}{severidad ? ` · ${severidad}` : ""}</span>
          </div>
        )}
        {expected && (
          <div className={styles.row}>
            <span className={styles.rowLabel}>Retorno estimado</span>
            <span className={styles.rowValue}>{formatDate(expected)}</span>
          </div>
        )}
        {episode.ended_at && (
          <div className={styles.row}>
            <span className={styles.rowLabel}>Cierre</span>
            <span className={styles.rowValue}>{formatDate(episode.ended_at)}</span>
          </div>
        )}
        {availabilityRow}

        <div className={styles.actions}>
          {isOpen && canEditEpisode && (
            <button
              type="button"
              className={styles.linkBtn}
              disabled={stageOptions.length === 0}
              onClick={() => { setStageDraft(episode.stage); setStageDate(todayStr()); setStageOpen(true); }}
            >
              Actualizar etapa
            </button>
          )}
          <button
            type="button"
            className={showLog ? styles.ghostBtnOn : styles.ghostBtn}
            onClick={() => setShowLog((v) => !v)}
          >
            {showLog ? "Ocultar bitácora" : "Bitácora"}
          </button>
          {continueHref && canEditEpisode && (
            <Link href={continueHref} className={styles.ghostBtn}>
              Editar datos
            </Link>
          )}
          {isOpen && canEditEpisode && (
            <button
              type="button"
              className={styles.ghostBtn}
              disabled={closing}
              onClick={darDeAlta}
            >
              {closing ? "Cerrando…" : "Dar de alta"}
            </button>
          )}
        </div>

        {showLog && template && (
          <div className={styles.logSection}>
            <h5 className={styles.timelineTitle}>Bitácora de la lesión</h5>
            <InjuryLog
              episode={episode}
              template={template}
              canEdit={canEditEpisode}
              refreshToken={logRefresh}
            />
          </div>
        )}

        <Modal open={stageOpen} title="Actualizar etapa" onClose={() => setStageOpen(false)}>
          <div className={styles.stageForm}>
            <span className={styles.stageFieldLabel}>Nueva etapa</span>
            <div className={styles.stageOptList} role="radiogroup" aria-label="Etapa">
              {stageOptions.map((o) => (
                <label key={o.value} className={stageDraft === o.value ? styles.stageOptOn : styles.stageOpt}>
                  <input
                    type="radio"
                    name="stage"
                    value={o.value}
                    checked={stageDraft === o.value}
                    onChange={() => setStageDraft(o.value)}
                  />
                  <span className={styles.stageOptText}>
                    <span className={styles.stageOptLabel}>{o.label}</span>
                    {o.description && <span className={styles.stageOptDesc}>{o.description}</span>}
                  </span>
                </label>
              ))}
            </div>
            <label className={styles.stageField}>
              <span className={styles.stageFieldLabel}>Fecha efectiva</span>
              <input
                type="date"
                className={styles.stageSelect}
                value={stageDate}
                max={todayStr()}
                onChange={(e) => setStageDate(e.target.value)}
              />
            </label>
            <p className={styles.stageHint}>
              Solo cambia la etapa. La evolución, hallazgos y documentos se
              registran en la bitácora. Para cerrar la lesión usá “Dar de alta”.
            </p>
            <div className={styles.stageActions}>
              <button type="button" className={styles.primaryBtn} disabled={savingStage} onClick={saveStage}>
                {savingStage ? "Guardando…" : "Guardar etapa"}
              </button>
              <button type="button" className={styles.ghostBtn} disabled={savingStage} onClick={() => setStageOpen(false)}>
                Cancelar
              </button>
            </div>
          </div>
        </Modal>
      </div>
    );
  }

  // ── Panel variant render (legacy, unchanged behaviour) ─────────────────
  const continueButton = isOpen && (
    continueHref ? (
      <Link href={continueHref} className={styles.linkBtn}>Actualizar etapa</Link>
    ) : onContinue ? (
      <button type="button" className={styles.linkBtn} onClick={onContinue}>Actualizar etapa</button>
    ) : null
  );

  return (
    <div className={`${styles.card} ${isOpen ? "" : styles.closed}`}>
      <div className={styles.cardHeader}>
        <div>
          <div className={styles.cardTitle}>{episode.title || "(sin título)"}</div>
          <div className={styles.cardSub}>{episode.template_name}</div>
        </div>
        <span className={`${styles.stagePill} ${stageClass(episode.stage)}`}>{stageLabel}</span>
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
      {availabilityRow}
      <div className={styles.row}>
        <span className={styles.rowLabel}>Resultados</span>
        <span className={styles.rowValue}>{episode.result_count}</span>
      </div>

      <div className={styles.actions}>
        <button type="button" className={styles.ghostBtn} onClick={() => setShowTimeline((v) => !v)}>
          {showTimeline ? "Ocultar historial" : "Ver historial"}
        </button>
        {continueButton}
      </div>

      {showTimeline && (
        <div className={styles.timeline}>
          <h5 className={styles.timelineTitle}>Historial</h5>
          {loadError && <div className={styles.error}>{loadError}</div>}
          {results === null && !loadError && <div className={styles.timelineEmpty}>Cargando…</div>}
          {results && results.length === 0 && <div className={styles.timelineEmpty}>Sin entradas.</div>}
          {results && panelTemplate && results.map((r) => {
            const stage = String(r.result_data?.stage ?? "");
            const sf = panelTemplate.episode_config?.stage_field;
            const optLabels = (panelTemplate.config_schema?.fields ?? [])
              .find((f) => f.key === sf)?.option_labels as Record<string, string> | undefined;
            const stageLbl = optLabels?.[stage] ?? STAGE_LABEL[stage] ?? stage;
            const noteSnippet = String(r.result_data?.notes ?? "").trim().slice(0, 80);
            return (
              <div key={r.id} className={styles.timelineRow}>
                <div className={styles.timelineMain}>
                  <span>
                    <strong>{formatDateTime(r.recorded_at)}</strong>
                    {stageLbl && ` · ${stageLbl}`}
                  </span>
                  {noteSnippet && (
                    <span className={styles.timelineSub}>
                      {noteSnippet}{noteSnippet.length === 80 ? "…" : ""}
                    </span>
                  )}
                </div>
                {onEdit && (
                  <button type="button" className={styles.ghostBtn} onClick={() => onEdit(r, panelTemplate)}>
                    Editar
                  </button>
                )}
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
