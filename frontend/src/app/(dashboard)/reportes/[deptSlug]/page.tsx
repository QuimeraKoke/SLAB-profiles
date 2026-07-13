"use client";

import React, { use, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import DownloadExcelButton from "@/components/reports/DownloadExcelButton";
import DownloadPdfButton from "@/components/reports/DownloadPdfButton";
import MatchSelector from "@/components/reports/MatchSelector";
import MatchMultiSelector from "@/components/reports/MatchMultiSelector";
import ReportFilters, { defaultFilters, groupPlayersByPosition } from "@/components/reports/ReportFilters";
import type { ReportFiltersValue } from "@/components/reports/ReportFilters";
import TeamReportDashboard from "@/components/reports/TeamReportDashboard";
import AddWidgetModal from "@/components/reports/AddWidgetModal";
import DashboardAssistant from "@/components/reports/DashboardAssistant";
import { useBreadcrumbLabel } from "@/components/layout/Breadcrumbs";
import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
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

export default function ReportePage({ params }: PageProps) {
  const { deptSlug } = use(params);
  const { membership } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { categoryId, loading: categoryLoading } = useCategoryContext();
  const setBreadcrumbLabel = useBreadcrumbLabel();

  const matchFromUrl = searchParams.get("match_id") ?? "";
  // Preserve null vs "" so we can tell "first load (param absent)" apart
  // from "user explicitly cleared (param present, empty)". The required-
  // mode auto-pick only fires on the former.
  const matchIdsParam = searchParams.get("match_ids");

  const [department, setDepartment] = useState<Department | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  // Team-tab filters.
  const [filters, setFilters] = useState<ReportFiltersValue>(() => defaultFilters());
  const [layout, setLayout] = useState<TeamReportResponse["layout"] | null>(null);
  const [layoutFetched, setLayoutFetched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped after a chart is promoted, so the layout refetches and shows it.
  const [reloadKey, setReloadKey] = useState(0);
  const [editMode, setEditMode] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const canEditPanel = usePermission("dashboards.change_teamreportwidget");

  const updateUrl = (next: {
    match?: string | null;
    matchIds?: string[] | null;
  }) => {
    const sp = new URLSearchParams(searchParams.toString());
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

  // NAV-15: register the real department name so the breadcrumb shows
  // "Físico" (accented) rather than the capitalized slug "Fisico".
  useEffect(() => {
    if (department) setBreadcrumbLabel(deptSlug, department.name);
  }, [department, deptSlug, setBreadcrumbLabel]);

  // Step 1b: roster for the position/player filter + the "Ver perfil"
  // drill-down picker.
  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<PlayerSummary[]>(`/players?category_id=${categoryId}`)
      .then((data) => {
        if (cancelled) return;
        setPlayers(data);
        setFilters((prev) => ({ ...prev, playerIds: [] }));
      })
      .catch(() => {
        // Non-fatal.
      });
    return () => {
      cancelled = true;
    };
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
  }, [department, categoryId, categoryLoading, filters, matchFromUrl, matchIdsParam, reloadKey]);

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
        <div className={styles.controls}>
          <ReportFilters
            positions={positions}
            players={players}
            value={filters}
            onChange={setFilters}
            hideDateRange={layout?.match_selector?.enabled === true}
          />
          {/* NAV-04: the dashboard is squad-only (no "Por jugador" tab). This
              picker is a drill-down jump — choosing a player opens their
              department profile, the canonical per-player surface. */}
          <PlayerPicker
            players={players}
            onJump={(id) => router.push(`/perfil/${id}?tab=${department.slug}`)}
          />
          {layout && categoryId && (
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
          {layout && categoryId && (
            <DownloadPdfButton
              endpoint={`/reports/${department.slug}/team.docx?${teamDocxQuery(categoryId, filters)}`}
              filename={`reporte-${department.slug}-${layout.category.name}.docx`.replace(/\s+/g, "_")}
            />
          )}
          {editMode && categoryId && (
            <button
              type="button"
              className={styles.editToggle}
              onClick={() => setAddOpen(true)}
            >
              + Agregar widget
            </button>
          )}
          {layout && canEditPanel && (
            <button
              type="button"
              className={editMode ? styles.editOn : styles.editToggle}
              onClick={() => setEditMode((e) => !e)}
            >
              {editMode ? "Listo" : "Editar panel"}
            </button>
          )}
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      {categoryId && (
        <DashboardAssistant
          categoryId={categoryId}
          departmentSlug={department.slug}
          departmentName={department.name}
          filters={{
            positionId: filters.positionId,
            playerIds: filters.playerIds,
            dateFrom: filters.date.from,
            dateTo: filters.date.to,
          }}
          onPromoted={() => setReloadKey((k) => k + 1)}
        />
      )}

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
        <TeamReportDashboard
          sections={layout.sections}
          editMode={editMode}
          onChanged={() => setReloadKey((k) => k + 1)}
        />
      ) : (
        layoutFetched && !error && <Placeholder departmentName={department.name} />
      )}

      {categoryId && (
        <AddWidgetModal
          open={addOpen}
          deptSlug={department.slug}
          categoryId={categoryId}
          onClose={() => setAddOpen(false)}
          onAdded={() => setReloadKey((k) => k + 1)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

interface PlayerPickerProps {
  players: PlayerSummary[];
  onJump: (id: string) => void;
}

/** NAV-04 drill-down: a compact picker that jumps to a player's department
 *  profile (the canonical per-player surface). It's a navigation, not a
 *  selection — the value stays empty and resets after navigating. */
function PlayerPicker({ players, onJump }: PlayerPickerProps) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>Ver perfil</span>
      <select
        value=""
        onChange={(e) => {
          if (e.target.value) onJump(e.target.value);
        }}
      >
        <option value="">— ver perfil de un jugador —</option>
        {groupPlayersByPosition(players).map((g) => (
          <optgroup key={g.key} label={g.label}>
            {g.players.map((p) => (
              <option key={p.id} value={p.id}>
                {p.first_name} {p.last_name}
              </option>
            ))}
          </optgroup>
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

/** Query string for the team Word report endpoint — mirrors the current
 *  on-screen filters so the .docx matches what the user is looking at. */
function teamDocxQuery(categoryId: string, filters: ReportFiltersValue): string {
  const sp = new URLSearchParams({ category_id: categoryId });
  if (filters.positionId) sp.set("position_id", filters.positionId);
  if (filters.playerIds.length > 0) sp.set("player_ids", filters.playerIds.join(","));
  if (filters.date.from) sp.set("date_from", filters.date.from);
  if (filters.date.to) sp.set("date_to", filters.date.to);
  return sp.toString();
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
