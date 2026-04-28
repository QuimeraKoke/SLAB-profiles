"use client";

import React, { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type {
  DepartmentLayoutResponse,
  Department,
  ExamResult,
  ExamTemplate,
} from "@/lib/types";
import DashboardEntryPanel from "@/components/perfil/ProfileDepartment/DashboardEntryPanel";
import DepartmentCard from "@/components/perfil/DepartmentCard/DepartmentCard";
import DepartmentDashboard from "@/components/dashboards/DepartmentDashboard";
import styles from "./ProfileDepartment.module.css";

interface ProfileDepartmentProps {
  playerId: string;
  department: Department;
}

export default function ProfileDepartment({ playerId, department }: ProfileDepartmentProps) {
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [layout, setLayout] = useState<DepartmentLayoutResponse["layout"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const refetchLayout = useCallback(() => {
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setResults(null);
    setTemplates([]);
    setLayout(null);
    setError(null);

    const dept = encodeURIComponent(department.slug);
    Promise.all([
      api<ExamResult[]>(`/players/${playerId}/results?department=${dept}`),
      api<ExamTemplate[]>(`/players/${playerId}/templates?department=${dept}`),
      api<DepartmentLayoutResponse>(`/players/${playerId}/views?department=${dept}`),
    ])
      .then(([resultsData, templatesData, layoutData]) => {
        if (cancelled) return;
        setResults(resultsData);
        setTemplates(templatesData);
        setLayout(layoutData.layout);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load department data");
        setResults([]);
      });

    return () => {
      cancelled = true;
    };
  }, [playerId, department.slug, reloadKey]);

  const handleResultSaved = (result: ExamResult) => {
    setResults((prev) => (prev ? [result, ...prev] : [result]));
    // Layout payloads are server-aggregated, so we need a refetch to see new data.
    if (layout) {
      refetchLayout();
    }
  };

  const renderBody = () => {
    if (results === null && !error) {
      return <div className={styles.loading}>Cargando…</div>;
    }
    if (error) {
      return <div className={styles.error}>{error}</div>;
    }
    if (templates.length === 0) {
      return (
        <div className={styles.empty}>
          No hay plantillas para <code>{department.slug}</code> aplicables a esta categoría.
          Crea una en el panel de administración para empezar.
        </div>
      );
    }

    if (layout) {
      return (
        <>
          <DashboardEntryPanel
            templates={templates}
            playerId={playerId}
            onResultSaved={handleResultSaved}
          />
          <DepartmentDashboard sections={layout.sections} />
        </>
      );
    }

    // Fallback to the legacy auto-rendered grid.
    return (
      <div className={styles.grid}>
        {templates.map((t) => (
          <DepartmentCard
            key={t.id}
            template={t}
            results={(results ?? []).filter((r) => r.template_id === t.id)}
            playerId={playerId}
            onResultSaved={handleResultSaved}
          />
        ))}
      </div>
    );
  };

  return (
    <section className={styles.container}>
      <header className={styles.header}>
        <h2 className={styles.title}>{department.name}</h2>
        {results !== null && (
          <span className={styles.subtitle}>
            {layout
              ? `Layout configurado · ${layout.sections.length} ${
                  layout.sections.length === 1 ? "sección" : "secciones"
                }`
              : `${templates.length} ${templates.length === 1 ? "plantilla" : "plantillas"}`}
          </span>
        )}
      </header>

      {renderBody()}
    </section>
  );
}
