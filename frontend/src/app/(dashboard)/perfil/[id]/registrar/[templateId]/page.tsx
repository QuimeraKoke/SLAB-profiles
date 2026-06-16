"use client";

import React, { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import BulkIngestForm from "@/components/forms/BulkIngestForm";
import BulkIngestPlaceholder from "@/components/forms/BulkIngestPlaceholder";
import DynamicUploader from "@/components/forms/DynamicUploader";
import MatchPicker from "@/components/forms/MatchPicker";
import TeamTableForm from "@/components/forms/TeamTableForm";
import InjuryPanel from "@/components/perfil/InjuryPanel/InjuryPanel";
import ResultsHistoryPanel from "@/components/perfil/ResultsHistoryPanel/ResultsHistoryPanel";
import { api, ApiError } from "@/lib/api";
import type {
  CalendarEvent,
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

// Spanish labels for the tab strip. Keep keys aligned with
// `ExamInputMode` so adding a new mode is one line + one label.
const MODE_LABELS: Record<ExamInputMode, string> = {
  single: "Por jugador",
  bulk_ingest: "Por equipo · subir archivo",
  team_table: "Por equipo · tabla",
  quick_list: "Lista rápida",
};

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
  const enabledModes = (template.input_config?.input_modes ?? ["single"]) as ExamInputMode[];
  const mode = resolveInputMode(template, modeOverride);
  const showModeTabs = enabledModes.length > 1;

  const onPickMode = (next: ExamInputMode) => {
    // Sync via URL so a refresh / share-link preserves the choice and
    // resolveInputMode() in this same component keeps the override in
    // its enabled-modes guard.
    const params = new URLSearchParams(searchParams.toString());
    params.set("mode", next);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const showEpisodePicker =
    template.is_episodic
    && episodeChoice === null
    && openEpisodes !== null
    && openEpisodes.length > 0;

  // Team-table and bulk-ingest render wide grids; let the registrar
  // claim most of the viewport instead of the 960px default.
  const wideMode = mode === "team_table" || mode === "bulk_ingest";
  const containerClass = wideMode
    ? `${styles.container} ${styles.containerWide}`
    : styles.container;

  return (
    <div className={containerClass}>
      <header className={styles.header}>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
        <div className={styles.titles}>
          <span className={styles.eyebrow}>
            {player.first_name} {player.last_name} · {departmentName}
            {!showModeTabs && (
              <span className={styles.modeTag}>{mode}</span>
            )}
          </span>
          <h1 className={styles.title}>Nueva entrada · {template.name}</h1>
        </div>
      </header>

      {template.show_injuries && (
        <div style={{ marginBottom: 16 }}>
          <InjuryPanel player={player} />
        </div>
      )}

      {showModeTabs && !showEpisodePicker && (
        <div className={styles.modeTabs} role="tablist" aria-label="Modo de carga">
          {enabledModes.map((m) => {
            const active = m === mode;
            return (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={active}
                className={
                  active
                    ? `${styles.modeTab} ${styles.modeTabActive}`
                    : styles.modeTab
                }
                onClick={() => onPickMode(m)}
              >
                {MODE_LABELS[m] ?? m}
              </button>
            );
          })}
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
          template.link_to_match ? (
            <MatchScopedTeamTable
              template={template}
              categoryId={player.category.id}
              onCommitted={goBack}
              onCancel={goBack}
            />
          ) : (
            <TeamTableForm
              template={template}
              categoryId={player.category.id}
              onCommitted={goBack}
              onCancel={goBack}
            />
          )
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

/**
 * Inline team-table for `link_to_match=True` templates. Shows a
 * single-match picker grouped by month-year above; once a match is
 * picked we fetch its roster and render TeamTableForm scoped to that
 * match (eventId set, participantIds filtered to "dressed" players —
 * titular / suplente_ingresa / citado_no_vestir). The dressed filter
 * matches the convocatoria semantics on /partidos/[id]/editar.
 */
function MatchScopedTeamTable({
  template, categoryId, onCommitted, onCancel,
}: {
  template: ExamTemplate;
  categoryId: string;
  onCommitted?: () => void;
  onCancel?: () => void;
}) {
  const [matches, setMatches] = useState<CalendarEvent[]>([]);
  const [loadingMatches, setLoadingMatches] = useState(true);
  const [pickedMatchId, setPickedMatchId] = useState<string | null>(null);
  const [roster, setRoster] = useState<Array<{ player_id: string; match_role: string }> | null>(null);
  const [loadingRoster, setLoadingRoster] = useState(false);

  // Fetch the category's matches once. Past first (newest), then
  // upcoming — same order MatchPicker preserves when grouping.
  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      event_type: "match",
      category_id: categoryId,
    });
    api<CalendarEvent[]>(`/events?${params}`)
      .then((data) => {
        if (cancelled) return;
        const now = Date.now();
        const sorted = [...data].sort((a, b) => {
          const at = new Date(a.starts_at).getTime();
          const bt = new Date(b.starts_at).getTime();
          const aPast = at <= now;
          const bPast = bt <= now;
          if (aPast !== bPast) return aPast ? -1 : 1;
          return bt - at;
        });
        setMatches(sorted);
      })
      .catch(() => {
        if (!cancelled) setMatches([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingMatches(false);
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  // Fetch the roster every time the user picks (or switches) a match.
  // The dressed-players filter happens below from this data.
  useEffect(() => {
    if (!pickedMatchId) {
      setRoster(null);
      return;
    }
    let cancelled = false;
    setLoadingRoster(true);
    api<Array<{ player_id: string; match_role: string }>>(
      `/events/${pickedMatchId}/roster`,
    )
      .then((data) => {
        if (!cancelled) setRoster(data);
      })
      .catch(() => {
        if (!cancelled) setRoster([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingRoster(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pickedMatchId]);

  const dressedIds = useMemo(() => {
    if (!roster) return [];
    const DRESSED = new Set(["titular", "suplente_ingresa", "citado_no_vestir"]);
    return roster
      .filter((r) => DRESSED.has(r.match_role))
      .map((r) => r.player_id);
  }, [roster]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{
        padding: "16px 20px", background: "#ffffff",
        border: "1px solid #e5e7eb", borderRadius: 8,
      }}>
        {loadingMatches ? (
          <div style={{ color: "#6b7280", fontSize: "0.9rem" }}>Cargando partidos…</div>
        ) : matches.length === 0 ? (
          <div style={{ color: "#6b7280", fontSize: "0.9rem" }}>
            No hay partidos cargados para esta categoría. Crea uno desde{" "}
            <Link href="/partidos/nuevo" style={{ color: "#6d28d9", fontWeight: 600 }}>
              Partidos → Nuevo
            </Link>.
          </div>
        ) : (
          <MatchPicker
            matches={matches}
            value={pickedMatchId}
            onChange={setPickedMatchId}
            label="Partido"
            required
            placeholder="Elige un partido para cargar el rendimiento…"
          />
        )}
      </div>

      {pickedMatchId && (
        loadingRoster ? (
          <div style={{
            padding: "16px 20px", color: "#6b7280", fontSize: "0.9rem",
            background: "#ffffff", border: "1px solid #e5e7eb", borderRadius: 8,
          }}>
            Cargando convocatoria…
          </div>
        ) : dressedIds.length === 0 ? (
          <div style={{
            padding: "16px 20px", color: "#6b7280", fontSize: "0.9rem",
            background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8,
          }}>
            Este partido no tiene jugadores marcados como titular /
            suplente ingresa / citado sin vestir. Configurá la
            convocatoria desde{" "}
            <Link href={`/partidos/${pickedMatchId}/editar`} style={{ color: "#6d28d9", fontWeight: 600 }}>
              el editor del partido
            </Link>{" "}
            antes de cargar el rendimiento.
          </div>
        ) : (
          <TeamTableForm
            key={pickedMatchId}
            template={template}
            categoryId={categoryId}
            eventId={pickedMatchId}
            participantIds={dressedIds}
            onCommitted={onCommitted}
            onCancel={onCancel}
          />
        )
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
