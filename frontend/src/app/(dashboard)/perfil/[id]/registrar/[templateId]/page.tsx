"use client";

import React, { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import BulkIngestForm from "@/components/forms/BulkIngestForm";
import BulkIngestPlaceholder from "@/components/forms/BulkIngestPlaceholder";
import DynamicUploader from "@/components/forms/DynamicUploader";
import TeamTableForm from "@/components/forms/TeamTableForm";
import InjuryPanel from "@/components/perfil/InjuryPanel/InjuryPanel";
import ResultsHistoryPanel from "@/components/perfil/ResultsHistoryPanel/ResultsHistoryPanel";
import { api, ApiError } from "@/lib/api";
import type {
  Episode,
  ExamInputMode,
  ExamTemplate,
  PlayerDetail,
} from "@/lib/types";
import styles from "./page.module.css";

function resolveInputMode(
  template: ExamTemplate,
  override: string | null,
): ExamInputMode {
  const cfg = template.input_config;
  const enabled = cfg?.input_modes ?? ["single"];
  if (override && (enabled as string[]).includes(override)) {
    return override as ExamInputMode;
  }
  if (cfg?.default_input_mode && enabled.includes(cfg.default_input_mode)) {
    return cfg.default_input_mode;
  }
  return enabled[0] ?? "single";
}

interface PageProps {
  params: Promise<{ id: string; templateId: string }>;
}

export default function RegistrarExamPage({ params }: PageProps) {
  const { id, templateId } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabSlug = searchParams.get("tab");

  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [template, setTemplate] = useState<ExamTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Episode picker state for episodic templates. URL `?episode=new` or
  // `?episode=<uuid>` skips the picker; otherwise we fetch open episodes
  // and ask the user to choose.
  const episodeParam = searchParams.get("episode");
  const [openEpisodes, setOpenEpisodes] = useState<Episode[] | null>(null);
  const [episodeChoice, setEpisodeChoice] = useState<string | "new" | null>(
    episodeParam ?? null,
  );
  // When continuing an existing episode (episodeChoice is a UUID), we
  // pre-fill the form with the latest linked result so the doctor only
  // edits what changed (stage, notes, dates).
  const [continueInitial, setContinueInitial] = useState<
    Record<string, unknown> | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPlayer(null);
      setTemplate(null);
      setError(null);
    });

    Promise.all([
      api<PlayerDetail>(`/players/${id}`),
      api<ExamTemplate>(`/templates/${templateId}`),
    ])
      .then(([playerData, templateData]) => {
        if (cancelled) return;
        setPlayer(playerData);
        setTemplate(templateData);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudo cargar la plantilla");
      });

    return () => {
      cancelled = true;
    };
  }, [id, templateId]);

  // Once we have the template, if it's episodic and we don't have a URL
  // override, load the player's open episodes for the picker.
  useEffect(() => {
    if (!template?.is_episodic) return;
    if (episodeChoice !== null) return; // URL pre-selected → no fetch needed
    let cancelled = false;
    api<Episode[]>(`/players/${id}/episodes?status=open`)
      .then((eps) => {
        if (cancelled) return;
        setOpenEpisodes(eps.filter((e) => e.template_id === template.id));
      })
      .catch(() => {
        if (!cancelled) setOpenEpisodes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [template, id, episodeChoice]);

  // When the user picks an existing episode, fetch its latest_result_data
  // so the form starts pre-populated with the prior reading's values.
  // We only fire the fetch when we actually need it; the parent guards
  // against using `continueInitial` for "new"/null choices.
  const shouldFetchContinue = Boolean(
    template?.is_episodic && episodeChoice && episodeChoice !== "new",
  );
  useEffect(() => {
    if (!shouldFetchContinue || !episodeChoice) return;
    let cancelled = false;
    api<Episode>(`/episodes/${episodeChoice}`)
      .then((ep) => {
        if (cancelled) return;
        setContinueInitial(ep.latest_result_data ?? {});
      })
      .catch(() => {
        if (!cancelled) setContinueInitial({});
      });
    return () => {
      cancelled = true;
    };
  }, [shouldFetchContinue, episodeChoice]);

  const backHref = tabSlug
    ? `/perfil/${id}?tab=${encodeURIComponent(tabSlug)}`
    : `/perfil/${id}`;

  const goBack = () => router.push(backHref);

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.error} role="alert">
          {error}
        </div>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
      </div>
    );
  }

  if (!player || !template) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Cargando…</div>
      </div>
    );
  }

  const departmentName = template.department?.name ?? "Departamento";
  const modeOverride = searchParams.get("mode");
  const mode = resolveInputMode(template, modeOverride);

  const showEpisodePicker =
    template.is_episodic
    && episodeChoice === null
    && openEpisodes !== null
    && openEpisodes.length > 0;

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
        <div className={styles.titles}>
          <span className={styles.eyebrow}>
            {player.first_name} {player.last_name} · {departmentName}
            <span className={styles.modeTag}>{mode}</span>
          </span>
          <h1 className={styles.title}>Nueva entrada · {template.name}</h1>
        </div>
      </header>

      {template.show_injuries && (
        <div style={{ marginBottom: 16 }}>
          <InjuryPanel player={player} />
        </div>
      )}

      <div className={styles.formWrap}>
        {showEpisodePicker ? (
          <EpisodePickerForm
            episodes={openEpisodes ?? []}
            onPick={(choice) => setEpisodeChoice(choice)}
            onCancel={goBack}
          />
        ) : mode === "bulk_ingest" ? (
          template.input_config?.column_mapping ? (
            <BulkIngestForm
              template={template}
              categoryId={player.category.id}
              onCommitted={goBack}
              onCancel={goBack}
            />
          ) : (
            <BulkIngestPlaceholder template={template} />
          )
        ) : mode === "team_table" ? (
          <TeamTableForm
            template={template}
            categoryId={player.category.id}
            onCommitted={goBack}
            onCancel={goBack}
          />
        ) : shouldFetchContinue && continueInitial === null ? (
          // Continuing an existing episode — wait until we've fetched the
          // latest result so DynamicUploader's useState initializer reads
          // the prefill on its FIRST mount (it doesn't re-read on prop change).
          <div style={{ padding: 24, color: "#6b7280" }}>
            Cargando datos de la lesión…
          </div>
        ) : (
          <DynamicUploader
            template={template}
            playerId={player.id}
            episodeId={
              template.is_episodic && episodeChoice && episodeChoice !== "new"
                ? episodeChoice
                : null
            }
            initialValues={
              template.is_episodic && episodeChoice && episodeChoice !== "new"
                ? continueInitial ?? undefined
                : undefined
            }
            onSaved={goBack}
            onCancel={goBack}
          />
        )}
      </div>

      {/* Past entries for this (player, template), collapsed by default.
       *  Hidden during episode-picker / team / bulk modes — those flows
       *  either haven't picked a player yet (team/bulk) or are choosing
       *  which episode to continue (picker), so a single-player history
       *  panel doesn't apply. */}
      {!showEpisodePicker && mode === "single" && (
        <ResultsHistoryPanel template={template} playerId={player.id} />
      )}
    </div>
  );
}

interface EpisodePickerFormProps {
  episodes: Episode[];
  onPick: (choice: string | "new") => void;
  onCancel: () => void;
}

function EpisodePickerForm({ episodes, onPick, onCancel }: EpisodePickerFormProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: 24,
        background: "#ffffff",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
      }}
    >
      <h3 style={{ margin: 0, fontSize: "1rem", color: "#111827" }}>
        ¿Es una nueva lesión o continuás un episodio existente?
      </h3>
      <p style={{ margin: 0, fontSize: "0.85rem", color: "#6b7280" }}>
        Hay {episodes.length} episodio{episodes.length === 1 ? "" : "s"} abierto
        {episodes.length === 1 ? "" : "s"} para este jugador.
      </p>
      <button
        type="button"
        onClick={() => onPick("new")}
        style={{
          background: "#6d28d9", color: "white", border: "none",
          borderRadius: 6, padding: "10px 14px", fontWeight: 600,
          cursor: "pointer", textAlign: "left",
        }}
      >
        + Nueva lesión
      </button>
      <div style={{ fontSize: "0.78rem", color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.04em" }}>
        Continuar episodio
      </div>
      {episodes.map((ep) => (
        <button
          key={ep.id}
          type="button"
          onClick={() => onPick(ep.id)}
          style={{
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 6,
            padding: "10px 14px",
            textAlign: "left",
            cursor: "pointer",
            color: "#111827",
          }}
        >
          <div style={{ fontWeight: 600 }}>{ep.title || "(sin título)"}</div>
          <div style={{ fontSize: "0.78rem", color: "#6b7280" }}>
            Etapa actual: <strong>{ep.stage}</strong> · iniciado {new Date(ep.started_at).toLocaleDateString("es-CL")}
          </div>
        </button>
      ))}
      <button
        type="button"
        onClick={onCancel}
        style={{
          background: "none", color: "#6b7280", border: "1px solid #d1d5db",
          borderRadius: 6, padding: "8px 14px", cursor: "pointer",
          alignSelf: "flex-start",
        }}
      >
        Cancelar
      </button>
    </div>
  );
}
