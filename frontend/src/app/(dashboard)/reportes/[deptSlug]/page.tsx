"use client";

import React, { use, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import DateRangeControl, {
  defaultDateRange,
  type DateRangeValue,
} from "@/components/common/DateRangeControl";
import ProfileDepartment from "@/components/perfil/ProfileDepartment/ProfileDepartment";
import DownloadExcelButton from "@/components/reports/DownloadExcelButton";
import DownloadPdfButton from "@/components/reports/DownloadPdfButton";
import MatchSelector from "@/components/reports/MatchSelector";
import MatchMultiSelector from "@/components/reports/MatchMultiSelector";
import ReportFilters, { defaultFilters } from "@/components/reports/ReportFilters";
import type { ReportFiltersValue } from "@/components/reports/ReportFilters";
import TeamReportDashboard from "@/components/reports/TeamReportDashboard";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useCategoryContext } from "@/context/CategoryContext";
import type {
  Department,
  PlayerSummary,
  Position,
  TeamReportResponse,
} from "@/lib/types";
import styles from "./page.module.css";

interface PageProps {
  params: Promise<{ deptSlug: string }>;
}

type TabKey = "plantel" | "por_jugador";

export default function ReportePage({ params }: PageProps) {
  const { deptSlug } = use(params);
  const { membership } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { categoryId, loading: categoryLoading } = useCategoryContext();

  // Top-level tab + selected player (Por jugador) persisted in URL.
  // Default "plantel" keeps backward-compat for users with bookmarks.
  const tabFromUrl = (searchParams.get("tab") as TabKey) || "plantel";
  const playerFromUrl = searchParams.get("player") ?? "";
  const matchFromUrl = searchParams.get("match_id") ?? "";
  // Preserve null vs "" so we can tell "first load (param absent)" apart
  // from "user explicitly cleared (param present, empty)". The required-
  // mode auto-pick only fires on the former.
  const matchIdsParam = searchParams.get("match_ids");
  const matchIdsFromUrl = matchIdsParam ?? "";

  const [department, setDepartment] = useState<Department | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  // Team-tab filters.
  const [filters, setFilters] = useState<ReportFiltersValue>(() => defaultFilters());
  // Per-player tab: own date range (the per-player ProfileDepartment expects
  // it shaped slightly differently — uses just from/to strings).
  const [playerDateRange, setPlayerDateRange] = useState<DateRangeValue>(
    () => defaultDateRange(),
  );
  const [layout, setLayout] = useState<TeamReportResponse["layout"] | null>(null);
  const [layoutFetched, setLayoutFetched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync URL → state on navigation (back/forward). Memo since we use
  // these as render inputs many times in the JSX.
  const activeTab: TabKey =
    tabFromUrl === "por_jugador" ? "por_jugador" : "plantel";
  const selectedPlayerId = playerFromUrl;

  const updateUrl = (next: {
    tab?: TabKey;
    player?: string | null;
    match?: string | null;
    matchIds?: string[] | null;
  }) => {
    const sp = new URLSearchParams(searchParams.toString());
    if (next.tab !== undefined) sp.set("tab", next.tab);
    if (next.player !== undefined) {
      if (next.player) sp.set("player", next.player);
      else sp.delete("player");
    }
    if (next.match !== undefined) {
      if (next.match) sp.set("match_id", next.match);
      else sp.delete("match_id");
    }
    if (next.matchIds !== undefined) {
      if (next.matchIds === null) {
        // Programmatic reset (e.g. switching layouts). Remove the param
        // so the next load triggers the required-mode auto-pick.
        sp.delete("match_ids");
      } else if (next.matchIds.length > 0) {
        sp.set("match_ids", next.matchIds.join(","));
      } else {
        // Empty array = user clicked Limpiar. Keep the param present
        // (as `match_ids=`) so the backend can tell "explicit empty"
        // apart from "first load, no selection yet".
        sp.set("match_ids", "");
      }
    }
    router.replace(`/reportes/${deptSlug}?${sp.toString()}`);
  };

  // Step 1: resolve the department + the positions the user can filter by.
  useEffect(() => {
    if (!membership) return;
    let cancelled = false;
    Promise.all([
      api<Department[]>(`/clubs/${membership.club.id}/departments`),
      api<Position[]>(`/clubs/${membership.club.id}/positions`),
    ])
      .then(([depts, poss]) => {
        if (cancelled) return;
        const dept = depts.find((d) => d.slug === deptSlug) ?? null;
        setDepartment(dept);
        setPositions(
          [...poss].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
        );
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Error al cargar el reporte");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [membership, deptSlug]);

  // Step 1b: roster for both the multi-select filter (Plantel tab) and the
  // single-player picker (Por jugador tab).
  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<PlayerSummary[]>(`/players?category_id=${categoryId}`)
      .then((data) => {
        if (cancelled) return;
        setPlayers(data);
        setFilters((prev) => ({ ...prev, playerIds: [] }));
        // If the previously-selected player isn't in this category, drop it.
        if (selectedPlayerId && !data.find((p) => p.id === selectedPlayerId)) {
          updateUrl({ player: null });
        }
      })
      .catch(() => {
        // Non-fatal.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryId]);

  // Step 2: fetch the team-view layout. Only matters when on Plantel tab,
  // but we fetch eagerly so switching back is instant.
  useEffect(() => {
    if (!department || categoryLoading || !categoryId) return;
    let cancelled = false;
    const params = new URLSearchParams({ category_id: categoryId });
    if (filters.positionId) params.set("position_id", filters.positionId);
    if (filters.playerIds.length > 0) {
      params.set("player_ids", filters.playerIds.join(","));
    }
    // When the layout exposes a match selector, the chosen match scopes
    // time — sending date_from/to in addition would just confuse the
    // resolver. We still send them on the first request (before layout
    // is loaded) because we don't yet know whether the layout uses match
    // selection; the backend ignores the dates for match-scoped widgets.
    const skipDates = layout?.match_selector?.enabled === true;
    if (!skipDates && filters.date.from) params.set("date_from", filters.date.from);
    if (!skipDates && filters.date.to) params.set("date_to", filters.date.to);
    if (matchFromUrl) params.set("match_id", matchFromUrl);
    // matchIdsParam preserves null vs "" — only suppress the param when
    // it's null (URL doesn't carry it). An explicit empty value means
    // "user clicked Limpiar"; the backend needs to see that to skip the
    // required-mode auto-fill, so we still send it.
    if (matchIdsParam !== null) params.set("match_ids", matchIdsParam);
    api<TeamReportResponse>(`/reports/${department.slug}?${params}`)
      .then((data) => {
        if (cancelled) return;
        setLayout(data.layout);
        setLayoutFetched(true);
        setError(null);
        // Required-mode auto-pick: if the backend selected match(es) for
        // us (URL was empty), reflect it in the URL so deep-linking +
        // the picker's value stay coherent.
        const sel = data.layout?.match_selector;
        const mode = sel?.mode ?? "single";
        if (sel?.enabled) {
          if (mode === "single" && sel.selected_id && sel.selected_id !== matchFromUrl) {
            updateUrl({ match: sel.selected_id });
          } else if (
            mode === "multi"
            && Array.isArray(sel.selected_ids)
            && sel.selected_ids.length > 0
            && matchIdsParam === null  // only on first load (param absent)
          ) {
            updateUrl({ matchIds: sel.selected_ids });
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Error al cargar el reporte");
          setLayout(null);
          setLayoutFetched(true);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [department, categoryId, categoryLoading, filters, matchFromUrl, matchIdsParam]);

  const selectedPlayer = useMemo(
    () => players.find((p) => p.id === selectedPlayerId) ?? null,
    [players, selectedPlayerId],
  );

  if (!department) {
    return (
      <div className={styles.container}>
        <div className={styles.muted}>
          {error ? <span className={styles.error}>{error}</span> : "Cargando…"}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.titles}>
          <span className={styles.eyebrow}>Reporte por departamento</span>
          <h1 className={styles.title}>{department.name}</h1>
        </div>
        {/* Controls vary by tab: Plantel shows team filters + Excel.
            Por jugador shows the player picker + a date range for the
            per-player view (reused inside ProfileDepartment). */}
        <div className={styles.controls}>
          {activeTab === "plantel" ? (
            <>
              <ReportFilters
                positions={positions}
                players={players}
                value={filters}
                onChange={setFilters}
                hideDateRange={layout?.match_selector?.enabled === true}
              />
              {layout && categoryId && (
                <>
                  <DownloadExcelButton
                    deptSlug={department.slug}
                    sections={layout.sections}
                    meta={{
                      departmentName: department.name,
                      categoryName: layout.category.name,
                      filters: {
                        positionLabel: filterPositionLabel(filters.positionId, positions),
                        playerNames: filterPlayerNames(filters.playerIds, players),
                        dateFrom: filters.date.from,
                        dateTo: filters.date.to,
                      },
                    }}
                  />
                  <DownloadPdfButton
                    endpoint={buildTeamReportEndpoint(
                      department.slug, categoryId, filters, matchFromUrl,
                    )}
                    filename={`reporte-${department.slug}-${layout.category.name}.docx`.replace(/\s+/g, "_")}
                  />
                </>
              )}
            </>
          ) : (
            <>
              <PlayerPicker
                players={players}
                selectedId={selectedPlayerId}
                onChange={(id) => updateUrl({ player: id || null })}
              />
              {/* PDF download for the selected player lives inside the
                  embedded ProfileDepartment below, next to the Excel
                  button. Two stacked PDF buttons in the header + body
                  was redundant; keeping only the contextual one. */}
            </>
          )}
        </div>
      </header>

      {(() => {
        // ME-3 follow-up: complete the half-implemented APG pattern.
        // `role="tablist"` was already here but with no arrow-key nav
        // and no roving tabIndex — screen readers told users to use
        // arrow keys that did nothing. Phase 3 IA-3 will likely retire
        // the "Por jugador" tab entirely (replaced by a link out to
        // the player profile); until then, finish the keyboard story.
        const tabs: Array<{ id: "plantel" | "por_jugador"; label: string }> = [
          { id: "plantel", label: "Plantel" },
          { id: "por_jugador", label: "Por jugador" },
        ];
        const onTabKey = (e: React.KeyboardEvent<HTMLButtonElement>) => {
          const idx = tabs.findIndex((t) => t.id === activeTab);
          if (idx < 0) return;
          let next: number | null = null;
          if (e.key === "ArrowRight") next = (idx + 1) % tabs.length;
          else if (e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
          else if (e.key === "Home") next = 0;
          else if (e.key === "End") next = tabs.length - 1;
          if (next !== null) {
            e.preventDefault();
            updateUrl({ tab: tabs[next].id });
          }
        };
        return (
          <nav className={styles.tabs} role="tablist" aria-label="Vistas del reporte">
            {tabs.map((t) => {
              const isActive = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  tabIndex={isActive ? 0 : -1}
                  className={`${styles.tab} ${isActive ? styles.tabActive : ""}`}
                  onClick={() => updateUrl({ tab: t.id })}
                  onKeyDown={onTabKey}
                >
                  {t.label}
                </button>
              );
            })}
          </nav>
        );
      })()}

      {error && <div className={styles.error}>{error}</div>}

      {activeTab === "plantel" ? (
        <>
          {!layoutFetched && !error && (
            <div className={styles.muted}>Cargando reporte…</div>
          )}
          {layout?.match_selector?.enabled && (
            layout.match_selector.mode === "multi" ? (
              <MatchMultiSelector
                config={layout.match_selector}
                onChange={(ids) => updateUrl({ matchIds: ids })}
              />
            ) : (
              <MatchSelector
                config={layout.match_selector}
                onChange={(id) => updateUrl({ match: id || null })}
              />
            )
          )}
          {layout ? (
            <TeamReportDashboard sections={layout.sections} />
          ) : (
            layoutFetched && !error && <Placeholder departmentName={department.name} />
          )}
        </>
      ) : (
        // Por jugador — replicates exactly what /perfil/[id] shows under
        // the matching department tab. Same widgets, same registrar bar.
        <>
          {!selectedPlayer ? (
            <div className={styles.placeholder}>
              <h3 className={styles.placeholderTitle}>Elige un jugador</h3>
              <p className={styles.placeholderBody}>
                Selecciona un jugador del listado de arriba para ver su
                perfil de <strong>{department.name}</strong>: indicadores,
                evolución y cargar un examen nuevo.
              </p>
            </div>
          ) : (
            <>
              {/* IA-3: canonical per-player department view lives at
                  `/perfil/[id]?tab=<dept>`. We render the same data here
                  but invite users to the profile for the extra context
                  (timeline, eventos, objetivos, lesiones) — positive
                  framing instead of "wrong place". */}
              <div
                role="note"
                aria-label="Acceso al perfil del jugador"
                style={{
                  margin: "0 0 12px",
                  padding: "10px 14px",
                  background: "#eef2ff",
                  border: "1px solid #c7d2fe",
                  borderRadius: 6,
                  fontSize: "0.85rem",
                  color: "#3730a3",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <span>
                  Vista de <strong>{selectedPlayer.first_name} {selectedPlayer.last_name}</strong>{" "}
                  · Abre su perfil para línea de tiempo, eventos y objetivos.
                </span>
                <a
                  href={`/perfil/${selectedPlayer.id}?tab=${department.slug}`}
                  style={{
                    color: "#4f46e5",
                    fontWeight: 500,
                    textDecoration: "underline",
                    textDecorationColor: "#c7d2fe",
                    textUnderlineOffset: 2,
                    whiteSpace: "nowrap",
                  }}
                >
                  Abrir perfil →
                </a>
              </div>
              <ProfileDepartment
                playerId={selectedPlayer.id}
                playerName={`${selectedPlayer.first_name} ${selectedPlayer.last_name}`}
                department={department}
                dateFrom={playerDateRange.date.from}
                dateTo={playerDateRange.date.to}
                dateRangeControl={
                  <DateRangeControl
                    value={playerDateRange}
                    onChange={setPlayerDateRange}
                    variant="compact"
                  />
                }
              />
            </>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

interface PlayerPickerProps {
  players: PlayerSummary[];
  selectedId: string;
  onChange: (id: string) => void;
}

/** Compact single-select picker for the "Por jugador" tab. Native
 *  <select> with a "—" option for "no player chosen". */
function PlayerPicker({ players, selectedId, onChange }: PlayerPickerProps) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>Jugador</span>
      <select
        value={selectedId}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">— elige un jugador —</option>
        {players.map((p) => (
          <option key={p.id} value={p.id}>
            {p.first_name} {p.last_name}
          </option>
        ))}
      </select>
    </label>
  );
}

function buildTeamReportEndpoint(
  deptSlug: string,
  categoryId: string,
  filters: ReportFiltersValue,
  matchId: string,
): string {
  const params = new URLSearchParams({ category_id: categoryId });
  if (filters.positionId) params.set("position_id", filters.positionId);
  if (filters.playerIds.length > 0) {
    params.set("player_ids", filters.playerIds.join(","));
  }
  if (filters.date.from) params.set("date_from", filters.date.from);
  if (filters.date.to) params.set("date_to", filters.date.to);
  if (matchId) params.set("match_id", matchId);
  return `/reports/${deptSlug}/team.docx?${params.toString()}`;
}

function filterPositionLabel(positionId: string, positions: Position[]): string {
  if (!positionId) return "Todas";
  const p = positions.find((x) => x.id === positionId);
  return p ? p.name : "Todas";
}

function filterPlayerNames(playerIds: string[], players: PlayerSummary[]): string[] {
  if (playerIds.length === 0) return [];
  const byId = new Map(players.map((p) => [p.id, `${p.first_name} ${p.last_name}`]));
  return playerIds.map((id) => byId.get(id) ?? id);
}

function Placeholder({ departmentName }: { departmentName: string }) {
  return (
    <div className={styles.placeholder}>
      <h3 className={styles.placeholderTitle}>Sin reporte configurado</h3>
      <p className={styles.placeholderBody}>
        Aún no hay un layout activo para <strong>{departmentName}</strong> en
        esta categoría. Un administrador puede crear uno desde
        {" "}
        <code>Dashboards → Team Report Layouts</code> en el panel de
        administración: agrega secciones, agrega widgets y elige los
        indicadores agregados a mostrar.
      </p>
    </div>
  );
}
