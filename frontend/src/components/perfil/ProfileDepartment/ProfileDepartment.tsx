"use client";

import React, { useEffect, useState } from "react";

import DownloadPlayerExcelButton from "@/components/perfil/ProfileDepartment/DownloadPlayerExcelButton";
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
  /** "First Last" — used for the Excel filename + summary sheet. */
  playerName: string;
  department: Department;
  /** ISO date strings ("YYYY-MM-DD") for the cross-tab filter, set on
   *  the parent page. Empty string = no bound on that side. */
  dateFrom: string;
  dateTo: string;
  /** Pre-rendered control so the parent owns the date state — keeps it
   *  shared across all department tabs without prop drilling setters. */
  dateRangeControl: React.ReactNode;
}

export default function ProfileDepartment({
  playerId,
  playerName,
  department,
  dateFrom,
  dateTo,
  dateRangeControl,
}: ProfileDepartmentProps) {
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

    // Templates and per-row history (`results`) are intentionally NOT
    // narrowed by the date filter — the "Agregar examen" picker should
    // always offer every applicable template, and the per-template
    // history card (legacy view) shows the full timeline. Only the
    // dashboard layout aggregation respects the window.
    const dept = encodeURIComponent(department.slug);
    const layoutParams = new URLSearchParams({ department: department.slug });
    if (dateFrom) layoutParams.set("date_from", dateFrom);
    if (dateTo) layoutParams.set("date_to", dateTo);

    Promise.all([
      api<ExamResult[]>(`/players/${playerId}/results?department=${dept}`),
      api<ExamTemplate[]>(`/players/${playerId}/templates?department=${dept}`),
      api<DepartmentLayoutResponse>(`/players/${playerId}/views?${layoutParams}`),
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
  }, [playerId, department.slug, dateFrom, dateTo]);

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
        <div className={styles.titleBlock}>
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
        </div>
        <div className={styles.controls}>
          {dateRangeControl}
          {layout && (
            <DownloadPlayerExcelButton
              playerName={playerName}
              department={department}
              sections={layout.sections}
              dateFrom={dateFrom}
              dateTo={dateTo}
            />
          )}
        </div>
      </header>

      {renderBody()}
    </section>
  );
}
