"use client";

import React, { use, useEffect, useState } from "react";

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

export default function ReportePage({ params }: PageProps) {
  const { deptSlug } = use(params);
  const { membership } = useAuth();
  // Category comes from the global navbar picker. Positions are
  // report-specific and stay local since they don't apply elsewhere.
  const { categoryId, loading: categoryLoading } = useCategoryContext();
  const [department, setDepartment] = useState<Department | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  // Filters: position + player subset + date range. Default: "Últimos 30 días".
  const [filters, setFilters] = useState<ReportFiltersValue>(() => defaultFilters());
  const [layout, setLayout] = useState<TeamReportResponse["layout"] | null>(null);
  const [layoutFetched, setLayoutFetched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1: resolve the department + the positions the user can filter by.
  // Positions are scoped to the user's club; "Todas" = no filter.
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

  // Step 1b: load the roster for the category — needed by the player
  // multi-select filter. Refreshes when the global category changes.
  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<PlayerSummary[]>(`/players?category_id=${categoryId}`)
      .then((data) => {
        if (cancelled) return;
        setPlayers(data);
        // Reset the player subset when the category changes; the
        // previously-selected IDs may not belong to the new category.
        setFilters((prev) => ({ ...prev, playerIds: [] }));
      })
      .catch(() => {
        // Non-fatal — the filter just shows an empty list.
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  // Step 2: fetch the layout when (department, categoryId) are both ready
  // and refetch when any filter changes. Each widget's data is resolved
  // server-side, so the response already carries everything to render.
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
    api<TeamReportResponse>(
      `/reports/${department.slug}?${params}`,
    )
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
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      {!layoutFetched && !error && (
        <div className={styles.muted}>Cargando reporte…</div>
      )}

      {layout ? (
        <TeamReportDashboard sections={layout.sections} />
      ) : (
        layoutFetched && !error && <Placeholder departmentName={department.name} />
      )}
    </div>
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
        administración: agregá secciones, agregá widgets y elegí los
        indicadores agregados a mostrar.
      </p>
    </div>
  );
}
