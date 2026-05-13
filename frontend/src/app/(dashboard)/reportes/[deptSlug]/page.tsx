"use client";

import React, { use, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import DateRangeControl, {
  defaultDateRange,
  type DateRangeValue,
} from "@/components/common/DateRangeControl";
import ProfileDepartment from "@/components/perfil/ProfileDepartment/ProfileDepartment";
import DownloadExcelButton from "@/components/reports/DownloadExcelButton";
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

  const updateUrl = (next: { tab?: TabKey; player?: string | null }) => {
    const sp = new URLSearchParams(searchParams.toString());
    if (next.tab !== undefined) sp.set("tab", next.tab);
    if (next.player !== undefined) {
      if (next.player) sp.set("player", next.player);
      else sp.delete("player");
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
    if (filters.date.from) params.set("date_from", filters.date.from);
    if (filters.date.to) params.set("date_to", filters.date.to);
    api<TeamReportResponse>(`/reports/${department.slug}?${params}`)
      .then((data) => {
        if (cancelled) return;
        setLayout(data.layout);
        setLayoutFetched(true);
        setError(null);
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
  }, [department, categoryId, categoryLoading, filters]);

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
              />
              {layout && (
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
              )}
            </>
          ) : (
            <PlayerPicker
              players={players}
              selectedId={selectedPlayerId}
              onChange={(id) => updateUrl({ player: id || null })}
            />
          )}
        </div>
      </header>

      <nav className={styles.tabs} role="tablist" aria-label="Vistas del reporte">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "plantel"}
          className={`${styles.tab} ${activeTab === "plantel" ? styles.tabActive : ""}`}
          onClick={() => updateUrl({ tab: "plantel" })}
        >
          Plantel
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "por_jugador"}
          className={`${styles.tab} ${activeTab === "por_jugador" ? styles.tabActive : ""}`}
          onClick={() => updateUrl({ tab: "por_jugador" })}
        >
          Por jugador
        </button>
      </nav>

      {error && <div className={styles.error}>{error}</div>}

      {activeTab === "plantel" ? (
        <>
          {!layoutFetched && !error && (
            <div className={styles.muted}>Cargando reporte…</div>
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
