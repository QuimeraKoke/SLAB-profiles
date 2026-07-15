"use client";

import React, { useEffect, useState } from "react";
import { Activity, FileText, Paperclip, Pencil, Plus, Trash2, X } from "lucide-react";

import Modal from "@/components/ui/Modal/Modal";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { api, ApiError } from "@/lib/api";
import { ACCEPTED_FILE_TYPES, formatSize } from "@/components/ui/AttachmentList/utils";
import type {
  Episode,
  EpisodeNote,
  EpisodeNoteAttachment,
  ExamResult,
  ExamTemplate,
} from "@/lib/types";
import {
  createEpisodeNote,
  deleteAttachment,
  deleteEpisodeNote,
  fetchSignedUrl,
  listEpisodeNotes,
  updateEpisodeNote,
  uploadNoteAttachment,
  type SignedUrl,
} from "@/lib/injuryLog";
import styles from "./InjuryLog.module.css";

interface Props {
  episode: Episode;
  /** The episode's template — supplies stage option labels for the markers. */
  template: ExamTemplate;
  /** Editor-gated: show add / edit / delete affordances. */
  canEdit: boolean;
  /** Bumped by the parent after a stage change so the stage markers refetch. */
  refreshToken?: number;
}

function isImage(mime: string): boolean {
  return (mime || "").toLowerCase().startsWith("image/");
}
function isPdf(mime: string): boolean {
  return (mime || "").toLowerCase() === "application/pdf";
}

/** Format a YYYY-MM-DD (or ISO datetime) WITHOUT going through UTC for the
 *  date-only case (avoids the off-by-one shift in negative timezones). */
function formatDay(iso: string): string {
  const dateOnly = iso.length === 10;
  const d = dateOnly
    ? (() => {
        const [y, m, dd] = iso.split("-").map(Number);
        return new Date(y, m - 1, dd);
      })()
    : new Date(iso);
  return d.toLocaleDateString("es-CL", { day: "2-digit", month: "short", year: "numeric" });
}

function evaTone(eva: number): string {
  if (eva <= 3) return styles.evaLow;
  if (eva <= 6) return styles.evaMid;
  return styles.evaHigh;
}

/** Day-level timestamp from a YYYY-MM-DD (or ISO datetime) string, ignoring
 *  time-of-day — so the timeline sorts purely by the entry's date field. */
function dayTs(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y || 1970, (m || 1) - 1, d || 1).getTime();
}

// A merged timeline item: either a bitácora note or a stage transition.
type TimelineItem =
  | { kind: "note"; ts: number; note: EpisodeNote }
  | { kind: "stage"; ts: number; id: string; label: string; date: string };

export default function InjuryLog({ episode, template, canEdit, refreshToken = 0 }: Props) {
  const episodeId = episode.id;
  const [notes, setNotes] = useState<EpisodeNote[] | null>(null);
  const [stageEvents, setStageEvents] = useState<
    { id: string; label: string; date: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { confirm } = useConfirm();
  const { toast } = useToast();

  const [today] = useState(() => {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(
      n.getDate(),
    ).padStart(2, "0")}`;
  });

  // Add-entry form.
  const [adding, setAdding] = useState(false);
  const [draftDate, setDraftDate] = useState(today);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftNote, setDraftNote] = useState("");
  const [draftEva, setDraftEva] = useState("");
  const [draftFiles, setDraftFiles] = useState<File[]>([]);

  // Inline edit of an existing note.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDate, setEditDate] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editNote, setEditNote] = useState("");
  const [editEva, setEditEva] = useState("");

  // Lightbox viewer.
  const [viewer, setViewer] = useState<SignedUrl | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);

  const reloadNotes = React.useCallback(() => {
    listEpisodeNotes(episodeId)
      .then((data) => setNotes(data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Error cargando la bitácora."));
  }, [episodeId]);

  // Load notes.
  useEffect(() => {
    let cancelled = false;
    listEpisodeNotes(episodeId)
      .then((data) => {
        if (!cancelled) setNotes(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Error cargando la bitácora.");
      });
    return () => {
      cancelled = true;
    };
  }, [episodeId]);

  // Load stage-transition markers from the episode's results (re-runs when the
  // parent bumps refreshToken after a stage change).
  useEffect(() => {
    let cancelled = false;
    api<ExamResult[]>(`/episodes/${episodeId}/results`)
      .then((results) => {
        if (cancelled) return;
        const sf = template.episode_config?.stage_field;
        const optLabels = (template.config_schema?.fields ?? []).find((f) => f.key === sf)
          ?.option_labels as Record<string, string> | undefined;
        // Emit a marker only when the stage actually changes (results carry the
        // definition forward, so consecutive results often share a stage).
        const asc = [...results].sort(
          (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime(),
        );
        const events: { id: string; label: string; date: string }[] = [];
        let prev: string | null = null;
        for (const r of asc) {
          const s = String((sf && r.result_data?.[sf]) ?? "").trim();
          if (!s || s === prev) continue;
          events.push({ id: r.id, label: optLabels?.[s] ?? s, date: r.recorded_at });
          prev = s;
        }
        setStageEvents(events);
      })
      .catch(() => {
        /* stage markers are best-effort; notes still render */
      });
    return () => {
      cancelled = true;
    };
  }, [episodeId, template, refreshToken]);

  function resetDraft() {
    setDraftDate(today);
    setDraftTitle("");
    setDraftNote("");
    setDraftEva("");
    setDraftFiles([]);
    setAdding(false);
  }

  function evaMetrics(raw: string): { eva?: number } {
    const v = raw.trim();
    if (v === "") return {};
    const n = Number(v);
    return Number.isFinite(n) ? { eva: Math.max(0, Math.min(10, Math.round(n))) } : {};
  }

  async function saveNewEntry() {
    if (busy) return;
    if (!draftDate) {
      toast.error("Elegí una fecha para la entrada.");
      return;
    }
    if (!draftTitle.trim() && !draftNote.trim() && draftFiles.length === 0 && draftEva.trim() === "") {
      toast.error("Agregá una nota, un título, EVA o un documento.");
      return;
    }
    setBusy(true);
    try {
      const note = await createEpisodeNote(episodeId, {
        entry_date: draftDate,
        title: draftTitle,
        note: draftNote,
        metrics: evaMetrics(draftEva),
      });
      const failed: string[] = [];
      for (const f of draftFiles) {
        try {
          await uploadNoteAttachment(note.id, f);
        } catch (e) {
          failed.push(`${f.name}: ${e instanceof Error ? e.message : "fallo"}`);
        }
      }
      resetDraft();
      reloadNotes();
      if (failed.length > 0) toast.error(`Entrada guardada, pero fallaron adjuntos: ${failed.join(" · ")}`);
      else toast.success("Entrada agregada a la bitácora.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo guardar la entrada.");
    } finally {
      setBusy(false);
    }
  }

  function startEdit(n: EpisodeNote) {
    setEditingId(n.id);
    setEditDate(n.entry_date);
    setEditTitle(n.title);
    setEditNote(n.note);
    setEditEva(n.metrics?.eva != null ? String(n.metrics.eva) : "");
  }

  async function saveEdit(noteId: string) {
    if (busy) return;
    setBusy(true);
    try {
      await updateEpisodeNote(episodeId, noteId, {
        entry_date: editDate,
        title: editTitle,
        note: editNote,
        metrics: evaMetrics(editEva),
      });
      setEditingId(null);
      reloadNotes();
      toast.success("Entrada actualizada.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo actualizar.");
    } finally {
      setBusy(false);
    }
  }

  async function removeNote(n: EpisodeNote) {
    const ok = await confirm({
      title: "Borrar entrada",
      message: `¿Borrar esta entrada${
        n.attachments.length ? ` y sus ${n.attachments.length} documento(s)` : ""
      }? No se puede deshacer.`,
      confirmLabel: "Borrar",
      variant: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await deleteEpisodeNote(episodeId, n.id);
      reloadNotes();
      toast.success("Entrada eliminada.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo borrar.");
    } finally {
      setBusy(false);
    }
  }

  async function addFilesToNote(noteId: string, files: FileList) {
    if (busy || files.length === 0) return;
    setBusy(true);
    const failed: string[] = [];
    for (const f of Array.from(files)) {
      try {
        await uploadNoteAttachment(noteId, f);
      } catch (e) {
        failed.push(`${f.name}: ${e instanceof Error ? e.message : "fallo"}`);
      }
    }
    reloadNotes();
    setBusy(false);
    if (failed.length > 0) toast.error(`Fallaron adjuntos: ${failed.join(" · ")}`);
    else toast.success("Documento(s) adjuntado(s).");
  }

  async function removeAttachment(att: EpisodeNoteAttachment) {
    const ok = await confirm({
      title: "Borrar documento",
      message: `¿Borrar «${att.filename}»? No se puede deshacer.`,
      confirmLabel: "Borrar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await deleteAttachment(att.id);
      reloadNotes();
      toast.success("Documento eliminado.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo borrar el documento.");
    }
  }

  async function openViewer(att: EpisodeNoteAttachment) {
    setViewerLoading(true);
    try {
      const signed = await fetchSignedUrl(att.id);
      if (isImage(signed.mime_type) || isPdf(signed.mime_type)) setViewer(signed);
      else window.open(signed.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo abrir el documento.");
    } finally {
      setViewerLoading(false);
    }
  }

  function renderThumbs(n: EpisodeNote) {
    if (n.attachments.length === 0) return null;
    return (
      <div className={styles.thumbs}>
        {n.attachments.map((att) => (
          <div key={att.id} className={styles.thumbWrap}>
            <button
              type="button"
              className={styles.thumbBtn}
              onClick={() => openViewer(att)}
              title={att.filename}
              disabled={viewerLoading}
            >
              {isImage(att.mime_type) && att.signed_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className={styles.thumbImg} src={att.signed_url} alt={att.filename} />
              ) : (
                <span className={styles.docChip}>
                  <FileText size={16} />
                  <span className={styles.docName}>{att.filename}</span>
                  <span className={styles.docSize}>{formatSize(att.size_bytes)}</span>
                </span>
              )}
            </button>
            {canEdit && (
              <button
                type="button"
                className={styles.thumbDel}
                onClick={() => removeAttachment(att)}
                aria-label={`Borrar ${att.filename}`}
                title="Borrar documento"
              >
                <X size={12} />
              </button>
            )}
          </div>
        ))}
      </div>
    );
  }

  // Build the merged timeline, newest-first strictly by the entry's DATE field
  // (day-level — the time it was created never affects order).
  const items: TimelineItem[] = [
    ...(notes ?? []).map(
      (n): TimelineItem => ({ kind: "note", ts: dayTs(n.entry_date), note: n }),
    ),
    ...stageEvents.map(
      (s): TimelineItem => ({
        kind: "stage",
        ts: dayTs(s.date),
        id: s.id,
        label: s.label,
        date: s.date,
      }),
    ),
  ].sort((a, b) => b.ts - a.ts);

  const loading = notes === null;
  const isEmpty = !loading && items.length === 0;

  return (
    <div className={styles.log}>
      {error && <div className={styles.error}>{error}</div>}

      {canEdit && (
        <div className={styles.addBlock}>
          {adding ? (
            <div className={styles.form}>
              <div className={styles.formRow}>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>Fecha</span>
                  <input
                    type="date"
                    className={styles.input}
                    value={draftDate}
                    max={today}
                    onChange={(e) => setDraftDate(e.target.value)}
                  />
                </label>
                <label className={`${styles.field} ${styles.grow}`}>
                  <span className={styles.fieldLabel}>Título (opcional)</span>
                  <input
                    type="text"
                    className={styles.input}
                    placeholder="Control ecográfico, Diagnóstico…"
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>EVA dolor (0–10)</span>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    className={`${styles.input} ${styles.evaInput}`}
                    placeholder="—"
                    value={draftEva}
                    onChange={(e) => setDraftEva(e.target.value)}
                  />
                </label>
              </div>
              <textarea
                className={styles.textarea}
                placeholder="Evolución, hallazgos, indicaciones…"
                rows={5}
                value={draftNote}
                onChange={(e) => setDraftNote(e.target.value)}
              />
              <div className={styles.formFiles}>
                <label className={styles.fileBtn}>
                  <Paperclip size={15} />
                  Adjuntar documentos
                  <input
                    type="file"
                    multiple
                    accept={ACCEPTED_FILE_TYPES}
                    className={styles.hidden}
                    onChange={(e) => {
                      if (e.target.files) setDraftFiles(Array.from(e.target.files));
                    }}
                  />
                </label>
                {draftFiles.length > 0 && (
                  <span className={styles.fileCount}>
                    {draftFiles.length} archivo{draftFiles.length === 1 ? "" : "s"} listo
                    {draftFiles.length === 1 ? "" : "s"}
                  </span>
                )}
              </div>
              <div className={styles.formActions}>
                <button type="button" className={styles.primaryBtn} disabled={busy} onClick={saveNewEntry}>
                  {busy ? "Guardando…" : "Guardar entrada"}
                </button>
                <button type="button" className={styles.ghostBtn} disabled={busy} onClick={resetDraft}>
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className={styles.addBtn} onClick={() => setAdding(true)}>
              <Plus size={15} /> Agregar entrada
            </button>
          )}
        </div>
      )}

      {loading && !error && <div className={styles.empty}>Cargando…</div>}
      {isEmpty && <div className={styles.empty}>Sin entradas en la bitácora todavía.</div>}

      {!loading && items.length > 0 && (
        <ol className={styles.timeline}>
          {items.map((item) =>
            item.kind === "stage" ? (
              <li key={`stage-${item.id}`} className={styles.stageEntry}>
                <div className={`${styles.dot} ${styles.dotStage}`} aria-hidden />
                <div className={styles.stageBody}>
                  <Activity size={13} className={styles.stageIcon} aria-hidden />
                  <span className={styles.stageText}>Cambio de etapa → <strong>{item.label}</strong></span>
                  <span className={styles.stageDate}>{formatDay(item.date)}</span>
                </div>
              </li>
            ) : (
              <li key={`note-${item.note.id}`} className={styles.entry}>
                <div className={styles.dot} aria-hidden />
                <div className={styles.entryBody}>
                  {editingId === item.note.id ? (
                    <div className={styles.form}>
                      <div className={styles.formRow}>
                        <input
                          type="date"
                          className={styles.input}
                          value={editDate}
                          max={today}
                          onChange={(e) => setEditDate(e.target.value)}
                        />
                        <input
                          type="text"
                          className={`${styles.input} ${styles.grow}`}
                          placeholder="Título"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                        />
                        <input
                          type="number"
                          min={0}
                          max={10}
                          className={`${styles.input} ${styles.evaInput}`}
                          placeholder="EVA"
                          value={editEva}
                          onChange={(e) => setEditEva(e.target.value)}
                        />
                      </div>
                      <textarea
                        className={styles.textarea}
                        rows={4}
                        value={editNote}
                        onChange={(e) => setEditNote(e.target.value)}
                      />
                      <div className={styles.formActions}>
                        <button
                          type="button"
                          className={styles.primaryBtn}
                          disabled={busy}
                          onClick={() => saveEdit(item.note.id)}
                        >
                          Guardar
                        </button>
                        <button
                          type="button"
                          className={styles.ghostBtn}
                          disabled={busy}
                          onClick={() => setEditingId(null)}
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className={styles.entryHead}>
                        <span className={styles.entryDate}>{formatDay(item.note.entry_date)}</span>
                        {item.note.title && <span className={styles.entryTitle}>{item.note.title}</span>}
                        {item.note.metrics?.eva != null && (
                          <span className={`${styles.evaPill} ${evaTone(item.note.metrics.eva)}`}>
                            EVA {item.note.metrics.eva}/10
                          </span>
                        )}
                        {canEdit && (
                          <span className={styles.entryTools}>
                            <label className={styles.iconBtn} title="Adjuntar documento">
                              <Paperclip size={14} />
                              <input
                                type="file"
                                multiple
                                accept={ACCEPTED_FILE_TYPES}
                                className={styles.hidden}
                                onChange={(e) => {
                                  if (e.target.files) addFilesToNote(item.note.id, e.target.files);
                                  e.target.value = "";
                                }}
                              />
                            </label>
                            <button
                              type="button"
                              className={styles.iconBtn}
                              onClick={() => startEdit(item.note)}
                              title="Editar entrada"
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              type="button"
                              className={`${styles.iconBtn} ${styles.danger}`}
                              onClick={() => removeNote(item.note)}
                              title="Borrar entrada"
                            >
                              <Trash2 size={14} />
                            </button>
                          </span>
                        )}
                      </div>
                      {item.note.note && <p className={styles.entryText}>{item.note.note}</p>}
                      {renderThumbs(item.note)}
                      {item.note.created_by_name && (
                        <span className={styles.entryMeta}>Registrado por {item.note.created_by_name}</span>
                      )}
                    </>
                  )}
                </div>
              </li>
            ),
          )}
        </ol>
      )}

      <Modal open={viewer !== null} title={viewer?.filename ?? ""} onClose={() => setViewer(null)}>
        {viewer && isImage(viewer.mime_type) && (
          // eslint-disable-next-line @next/next/no-img-element
          <img className={styles.viewerImg} src={viewer.url} alt={viewer.filename} />
        )}
        {viewer && isPdf(viewer.mime_type) && (
          <iframe className={styles.viewerPdf} src={viewer.url} title={viewer.filename} />
        )}
      </Modal>
    </div>
  );
}
