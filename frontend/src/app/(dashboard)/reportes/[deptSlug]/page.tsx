"use client";

import React, { use, useEffect, useState } from "react";

import TeamReportDashboard from "@/components/reports/TeamReportDashboard";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useCategoryContext } from "@/context/CategoryContext";
import type {
  Department,
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
  // Empty string = "Todas las posiciones" (no filter); otherwise a position UUID.
  const [positionId, setPositionId] = useState<string>("");
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

  // Step 2: fetch the layout when (department, categoryId) are both ready
  // and refetch when the picker changes. Each widget's data is resolved
  // server-side, so the response already carries everything to render.
  useEffect(() => {
    if (!department || categoryLoading || !categoryId) return;
    let cancelled = false;
    const params = new URLSearchParams({ category_id: categoryId });
    if (positionId) params.set("position_id", positionId);
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
  }, [department, categoryId, positionId, categoryLoading]);

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
          {positions.length > 0 && (
            <label className={styles.field}>
              <span className={styles.label}>Posición</span>
              <select
                value={positionId}
                onChange={(e) => setPositionId(e.target.value)}
              >
                <option value="">Todas</option>
                {positions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.abbreviation ? ` (${p.abbreviation})` : ""}
                  </option>
                ))}
              </select>
            </label>
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
