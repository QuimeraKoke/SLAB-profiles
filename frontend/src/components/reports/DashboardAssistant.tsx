"use client";

import React from "react";

import { api, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast/Toast";
import type { TeamReportWidget, TeamWidgetData } from "@/lib/types";
import { renderTeamWidget } from "./widgets";
import AssistantPanel, { type ChartResult } from "./AssistantPanel";

interface Props {
  categoryId: string;
  departmentSlug: string;
  departmentName: string;
  /** The page's current filters, forwarded so a proposed chart respects the
   *  same position / player / date scope the dashboard is showing. */
  filters: {
    positionId: string;
    playerIds: string[];
    dateFrom: string;
    dateTo: string;
  };
  /** Called after a chart is promoted, so the page can refetch the layout. */
  onPromoted?: () => void;
}

const SUGGESTIONS = [
  "¿Cómo está la distribución del plantel en la métrica clave de esta área?",
  "Compará a los jugadores por su último registro y mostrame un gráfico.",
  "¿Quiénes están fuera de rango? Visualizalo.",
];

/**
 * V2c — team-dashboard wrapper around the shared `AssistantPanel`: asks the
 * view-scoped team assistant, renders proposed charts with the TEAM widget
 * registry, and promotes them to the department's `TeamReportLayout`.
 */
export default function DashboardAssistant({
  categoryId,
  departmentSlug,
  departmentName,
  filters,
  onPromoted,
}: Props) {
  const { toast } = useToast();

  return (
    <AssistantPanel
      label="Preguntar a S-LAB AI"
      scope={departmentName}
      disabled={!categoryId}
      placeholder={categoryId ? "Escribí tu pregunta…" : "Seleccioná una categoría"}
      suggestions={SUGGESTIONS}
      promoteLabel="Promover al panel"
      sendMessage={(messages) =>
        api<{ reply: string; charts: ChartResult[] }>("/assistant/dashboard", {
          method: "POST",
          body: JSON.stringify({
            category_id: categoryId,
            department_slug: departmentSlug,
            messages,
            position_id: filters.positionId || null,
            player_ids: filters.playerIds.length ? filters.playerIds : null,
            date_from: filters.dateFrom || null,
            date_to: filters.dateTo || null,
          }),
        })
      }
      renderChart={(c, id) => renderTeamWidget(toTeamWidget(c, id))}
      promote={async (c) => {
        try {
          await api(`/reports/${departmentSlug}/widgets`, {
            method: "POST",
            body: JSON.stringify({ category_id: categoryId, spec: c.spec }),
          });
          toast.success("Gráfico agregado al panel.");
          onPromoted?.();
        } catch (err) {
          toast.error(
            err instanceof ApiError ? err.message : "No se pudo agregar el gráfico.",
          );
          throw err; // let AssistantPanel revert the button state
        }
      }}
    />
  );
}

/** Wrap a resolved payload into the `TeamReportWidget` shape the team-widget
 *  renderers expect (they read `widget.data`). */
function toTeamWidget(chart: ChartResult, id: string): TeamReportWidget {
  return {
    id,
    chart_type: chart.chart_type,
    title: chart.title ?? "",
    description: "",
    column_span: 12,
    chart_height: null,
    sort_order: 0,
    data: chart as unknown as TeamWidgetData,
  };
}
