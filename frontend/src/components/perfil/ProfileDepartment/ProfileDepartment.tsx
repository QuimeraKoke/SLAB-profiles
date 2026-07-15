"use client";

import React, { useEffect, useState } from "react";

import DownloadPlayerExcelButton from "@/components/perfil/ProfileDepartment/DownloadPlayerExcelButton";
import DownloadPdfButton from "@/components/reports/DownloadPdfButton";
import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
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
import AddWidgetModal from "@/components/reports/AddWidgetModal";
import PlayerAssistant from "./PlayerAssistant";
import styles from "./ProfileDepartment.module.css";

interface ProfileDepartmentProps {
  playerId: string;
  /** "First Last" — used for the Excel filename + summary sheet. */
  playerName: string;
  /** Player's category — scopes the widget-options for the panel editor. */
  categoryId: string;
  department: Department;
}

export default function ProfileDepartment({
  playerId,
  playerName,
  categoryId,
  department,
}: ProfileDepartmentProps) {
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [layout, setLayout] = useState<DepartmentLayoutResponse["layout"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after a chart is promoted, so the layout refetches and shows it.
  const [reloadKey, setReloadKey] = useState(0);
  const [editMode, setEditMode] = useState(false);
  // §5b — panel editor: add + edit-in-place per-player widgets.
  const [addOpen, setAddOpen] = useState(false);
  const [editWidgetId, setEditWidgetId] = useState<string | null>(null);
  const canEditPanel = usePermission("dashboards.change_widget");

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

    // The layout is fetched WITHOUT a date window: every chart receives its
    // full history and owns its own time window client-side (chevron
    // navigation in each widget) — there is no global date filter anymore.
    const dept = encodeURIComponent(department.slug);
    const layoutParams = new URLSearchParams({ department: department.slug });

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
  }, [playerId, department.slug, reloadKey]);

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
          <DepartmentDashboard
            sections={layout.sections}
            playerId={playerId}
            editMode={editMode}
            onChanged={() => setReloadKey((k) => k + 1)}
            onEditWidget={(id) => setEditWidgetId(id)}
          />
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
          {layout && (
            <DownloadPlayerExcelButton
              playerName={playerName}
              department={department}
              sections={layout.sections}
              dateFrom=""
              dateTo=""
            />
          )}
          {layout && (
            <DownloadPdfButton
              endpoint={playerDeptDocxEndpoint(playerId, department.slug, "", "")}
              filename={`reporte-${playerName}-${department.slug}.docx`.replace(/\s+/g, "_")}
            />
          )}
          {layout && canEditPanel && editMode && (
            <button
              type="button"
              className={styles.editToggle}
              onClick={() => setAddOpen(true)}
            >
              + Agregar gráfico
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

      <PlayerAssistant
        playerId={playerId}
        playerName={playerName}
        departmentSlug={department.slug}
        departmentName={department.name}
        dateFrom=""
        dateTo=""
        onPromoted={() => setReloadKey((k) => k + 1)}
      />

      {renderBody()}

      <AddWidgetModal
        open={addOpen || editWidgetId !== null}
        scope="player"
        playerId={playerId}
        deptSlug={department.slug}
        categoryId={categoryId}
        editWidgetId={editWidgetId}
        onClose={() => { setAddOpen(false); setEditWidgetId(null); }}
        onAdded={() => { setAddOpen(false); setEditWidgetId(null); setReloadKey((k) => k + 1); }}
      />
    </section>
  );
}

/** Word report endpoint for a player's department, carrying the current date
 *  window so the .docx matches what's on screen. */
function playerDeptDocxEndpoint(
  playerId: string,
  slug: string,
  dateFrom: string,
  dateTo: string,
): string {
  const sp = new URLSearchParams();
  if (dateFrom) sp.set("date_from", dateFrom);
  if (dateTo) sp.set("date_to", dateTo);
  const qs = sp.toString();
  return `/players/${playerId}/departments/${slug}/report.docx${qs ? `?${qs}` : ""}`;
}
