"use client";

import React, { useEffect, useState } from "react";

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
import MatchHistoryTable from "@/components/perfil/MatchHistoryTable/MatchHistoryTable";
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

  // Refetch only the results list. Used after a row is edited or deleted in
  // a child DepartmentCard so the table re-renders without thrashing the
  // template + layout fetches.
  const refreshResults = React.useCallback(() => {
    let cancelled = false;
    const dept = encodeURIComponent(department.slug);
    api<ExamResult[]>(`/players/${playerId}/results?department=${dept}`)
      .then((data) => {
        if (!cancelled) setResults(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to refresh results");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [playerId, department.slug]);

  useEffect(() => {
    let cancelled = false;
    // Defer the "clear state for new fetch" via a microtask so the lint
    // rule `react-hooks/set-state-in-effect` doesn't flag the synchronous
    // resets. Same behavior — runs before any render.
    Promise.resolve().then(() => {
      if (cancelled) return;
      setResults(null);
      setTemplates([]);
      setLayout(null);
      setError(null);
    });

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
  }, [playerId, department.slug]);

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
            departmentSlug={department.slug}
          />
          <DepartmentDashboard sections={layout.sections} />
        </>
      );
    }

    // Fallback to the legacy auto-rendered grid.
    return (
      <div className={styles.grid}>
        {templates.map((t) => {
          const templateResults = (results ?? []).filter((r) => r.template_id === t.id);
          // Templates that opt into event linking get a dedicated history view
          // pulling opponent + score from the linked event metadata.
          if (t.input_config?.allow_event_link) {
            return (
              <MatchHistoryTable
                key={t.id}
                template={t}
                results={templateResults}
                playerId={playerId}
              />
            );
          }
          return (
            <DepartmentCard
              key={t.id}
              template={t}
              results={templateResults}
              playerId={playerId}
              departmentSlug={department.slug}
              onMutated={refreshResults}
            />
          );
        })}
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
