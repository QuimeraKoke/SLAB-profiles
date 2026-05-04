"use client";

import React, { useEffect, useState } from "react";

import DynamicUploader from "@/components/forms/DynamicUploader";
import EpisodeCard, {
  formatDateTime,
} from "@/components/perfil/ProfileEpisodes/EpisodeCard";
import Modal from "@/components/ui/Modal/Modal";
import { api, ApiError } from "@/lib/api";
import type {
  Episode,
  ExamResult,
  ExamTemplate,
  PlayerDetail,
} from "@/lib/types";
import episodeStyles from "@/components/perfil/ProfileEpisodes/ProfileEpisodes.module.css";
import styles from "./InjuryPanel.module.css";

interface Props {
  /** Used by EpisodeCard to render player-scoped routes if needed; for the
   *  panel's in-place flows we never navigate, so most of PlayerDetail is
   *  unused but the EpisodeCard prop signature requires it. */
  player: PlayerDetail;
}

/**
 * Active modal state. Three flows live in this panel:
 *   - "new"      → create a brand-new injury (DynamicUploader, no episode)
 *   - "continue" → progress an existing open episode (DynamicUploader + episodeId)
 *   - "edit"     → edit a past entry inside any episode (DynamicUploader edit-mode)
 */
type ModalState =
  | null
  | { kind: "new" }
  | { kind: "continue"; episode: Episode }
  | { kind: "edit"; result: ExamResult; template: ExamTemplate };

export default function InjuryPanel({ player }: Props) {
  const [openEpisodes, setOpenEpisodes] = useState<Episode[] | null>(null);
  const [injuryTemplate, setInjuryTemplate] = useState<ExamTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      // Filter to the `lesiones` slug — InjuryPanel is INJURY-specific.
      // Other episodic templates (Medicación, etc.) shouldn't appear here.
      api<Episode[]>(`/players/${player.id}/episodes?status=open&template_slug=lesiones`),
      api<ExamTemplate[]>(`/players/${player.id}/templates`),
    ])
      .then(([eps, templates]) => {
        if (cancelled) return;
        setOpenEpisodes(eps);
        const ep = templates.find((t) => t.slug === "lesiones") ?? null;
        setInjuryTemplate(ep);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Error cargando lesiones");
      });
    return () => {
      cancelled = true;
    };
  }, [player.id, reloadKey]);

  const closeModal = () => setModal(null);
  const handleSaved = () => {
    setModal(null);
    setReloadKey((n) => n + 1);
  };

  const renderModalBody = (): React.ReactNode => {
    if (modal === null) return null;
    if (modal.kind === "new") {
      if (!injuryTemplate) return null;
      return (
        <DynamicUploader
          template={injuryTemplate}
          playerId={player.id}
          episodeId={null}
          onSaved={handleSaved}
          onCancel={closeModal}
        />
      );
    }
    if (modal.kind === "continue") {
      // The episode list endpoint already serializes `latest_result_data`,
      // so we have the prefill data without a second fetch. We use the
      // cached injuryTemplate — assumes one episodic template per club
      // (true today; revisit if multi-template episodes ship).
      if (!injuryTemplate) return null;
      return (
        <DynamicUploader
          template={injuryTemplate}
          playerId={player.id}
          episodeId={modal.episode.id}
          initialValues={modal.episode.latest_result_data}
          onSaved={handleSaved}
          onCancel={closeModal}
        />
      );
    }
    // edit
    return (
      <DynamicUploader
        template={modal.template}
        playerId={player.id}
        existingResult={modal.result}
        onSaved={handleSaved}
        onCancel={closeModal}
      />
    );
  };

  const modalTitle = (): string => {
    if (modal === null) return "";
    if (modal.kind === "new") return "Nueva lesión";
    if (modal.kind === "continue") {
      return `Actualizar etapa · ${modal.episode.title || "(sin título)"}`;
    }
    return `Editar entrada · ${formatDateTime(modal.result.recorded_at)}`;
  };

  if (openEpisodes === null) {
    return (
      <div className={styles.panel}>
        <div className={styles.loading}>Cargando lesiones…</div>
      </div>
    );
  }

  return (
    <>
      <div className={styles.panel}>
        <div className={styles.toolbar}>
          <h4 className={styles.title}>
            <strong>Lesiones abiertas</strong>{" "}
            <span>· {openEpisodes.length}</span>
          </h4>
          <button
            type="button"
            className={styles.newBtn}
            onClick={() => setModal({ kind: "new" })}
            disabled={!injuryTemplate}
            title={
              injuryTemplate
                ? "Registrar nueva lesión"
                : "No hay plantilla de lesiones aplicable a esta categoría"
            }
          >
            + Registrar lesión
          </button>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        {openEpisodes.length === 0 ? (
          <div className={styles.empty}>Sin lesiones abiertas.</div>
        ) : (
          <div className={episodeStyles.list}>
            {openEpisodes.map((ep) => (
              <EpisodeCard
                key={ep.id}
                episode={ep}
                onContinue={() => setModal({ kind: "continue", episode: ep })}
                onEdit={(result, template) =>
                  setModal({ kind: "edit", result, template })
                }
              />
            ))}
          </div>
        )}
      </div>

      <Modal
        open={modal !== null}
        title={modalTitle()}
        onClose={closeModal}
      >
        {renderModalBody()}
      </Modal>
    </>
  );
}
