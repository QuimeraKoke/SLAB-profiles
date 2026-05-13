"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";

import DynamicUploader from "@/components/forms/DynamicUploader";
import Modal from "@/components/ui/Modal/Modal";
import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import type {
  Episode,
  ExamResult,
  ExamTemplate,
  PlayerDetail,
} from "@/lib/types";
import EpisodeCard, { formatDateTime } from "./EpisodeCard";
import styles from "./ProfileEpisodes.module.css";

interface Props {
  player: PlayerDetail;
}

export default function ProfileEpisodes({ player }: Props) {
  const [episodes, setEpisodes] = useState<Episode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [episodicTemplate, setEpisodicTemplate] = useState<ExamTemplate | null>(null);
  // The result currently being edited in the modal, plus its template
  // (needed because the modal renders DynamicUploader which needs the template).
  const [editTarget, setEditTarget] = useState<{
    result: ExamResult;
    template: ExamTemplate;
  } | null>(null);
  // Bumping reloadKey re-runs the loader effect after a successful edit.
  const [reloadKey, setReloadKey] = useState(0);
  // The "+ Nueva lesión" button records a new ExamResult and may
  // also open a new Episode — both gated by add_examresult.
  const canAddResult = usePermission("exams.add_examresult");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      // Lesiones tab is INJURY-specific. Filter on the `lesiones` slug so
      // other episodic templates (Medicación, etc.) don't bleed in here —
      // they surface in their own department tab as DepartmentCards.
      api<Episode[]>(`/players/${player.id}/episodes?template_slug=lesiones`),
      api<ExamTemplate[]>(`/players/${player.id}/templates`),
    ])
      .then(([eps, templates]) => {
        if (cancelled) return;
        setEpisodes(eps);
        // Match the same slug for the "+ Nueva lesión" button so it routes
        // to Lesiones even when other episodic templates exist on the
        // player's category.
        const ep = templates.find((t) => t.slug === "lesiones") ?? null;
        setEpisodicTemplate(ep);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Error cargando episodios");
      });
    return () => {
      cancelled = true;
    };
  }, [player.id, reloadKey]);

  if (episodes === null) {
    return <div className={styles.container}>Cargando…</div>;
  }

  const open = episodes.filter((e) => e.status === "open");
  const closed = episodes.filter((e) => e.status === "closed");

  const newHref = episodicTemplate
    ? `/perfil/${player.id}/registrar/${episodicTemplate.id}?tab=lesiones&episode=new`
    : null;

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <h3 className={styles.title}>
          Lesiones · {open.length} abierta{open.length === 1 ? "" : "s"}
          {closed.length > 0 && ` · ${closed.length} cerrada${closed.length === 1 ? "" : "s"}`}
        </h3>
        {newHref && canAddResult && (
          <Link href={newHref} className={styles.newBtn}>
            + Nueva lesión
          </Link>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {open.length > 0 && (
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>Episodios abiertos</h4>
          <div className={styles.list}>
            {open.map((ep) => (
              <EpisodeCard
                key={ep.id}
                episode={ep}
                continueHref={`/perfil/${player.id}/registrar/${ep.template_id}?tab=lesiones&episode=${ep.id}`}
                onEdit={(result, template) => setEditTarget({ result, template })}
              />
            ))}
          </div>
        </div>
      )}

      {closed.length > 0 && (
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>Histórico</h4>
          <div className={styles.list}>
            {closed.map((ep) => (
              <EpisodeCard
                key={ep.id}
                episode={ep}
                onEdit={(result, template) => setEditTarget({ result, template })}
              />
            ))}
          </div>
        </div>
      )}

      {episodes.length === 0 && (
        <div className={styles.empty}>
          No hay episodios registrados para este jugador.
        </div>
      )}

      <Modal
        open={editTarget !== null}
        title={
          editTarget
            ? `Editar entrada · ${formatDateTime(editTarget.result.recorded_at)}`
            : ""
        }
        onClose={() => setEditTarget(null)}
      >
        {editTarget && (
          <DynamicUploader
            template={editTarget.template}
            playerId={player.id}
            existingResult={editTarget.result}
            onSaved={() => {
              setEditTarget(null);
              setReloadKey((n) => n + 1);
            }}
            onCancel={() => setEditTarget(null)}
          />
        )}
      </Modal>
    </div>
  );
}
