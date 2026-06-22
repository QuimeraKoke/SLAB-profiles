"use client";

import React from "react";

import { api, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DashboardWidget, WidgetData } from "@/lib/types";
import { renderWidget } from "@/components/dashboards/widgets";
import AssistantPanel, { type ChartResult } from "@/components/reports/AssistantPanel";

interface Props {
  playerId: string;
  playerName: string;
  departmentSlug: string;
  departmentName: string;
  /** ISO date strings ("YYYY-MM-DD") for the cross-tab filter (empty = unbounded). */
  dateFrom: string;
  dateTo: string;
  /** Called after a chart is promoted, so the profile can refetch the layout. */
  onPromoted?: () => void;
}

const SUGGESTIONS = [
  "Mostrame la evolución de las métricas clave de este jugador.",
  "Compará sus últimas tomas en una tabla.",
  "¿Cómo viene su carga / rendimiento en el tiempo?",
];

/**
 * V4c — player-profile wrapper around the shared `AssistantPanel`: asks the
 * per-player assistant, renders proposed charts with the PER-PLAYER widget
 * registry, and promotes them to the department's profile `DepartmentLayout`
 * (rendered per player across the category).
 */
export default function PlayerAssistant({
  playerId,
  playerName,
  departmentSlug,
  departmentName,
  dateFrom,
  dateTo,
  onPromoted,
}: Props) {
  const { toast } = useToast();

  return (
    <AssistantPanel
      label="Preguntar a S-LAB AI"
      scope={playerName}
      suggestions={SUGGESTIONS}
      promoteLabel={`Agregar al panel de ${departmentName}`}
      sendMessage={(messages) =>
        api<{ reply: string; charts: ChartResult[] }>("/assistant/player", {
          method: "POST",
          body: JSON.stringify({
            player_id: playerId,
            department_slug: departmentSlug,
            messages,
            date_from: dateFrom || null,
            date_to: dateTo || null,
          }),
        })
      }
      renderChart={(c, id) => renderWidget(toPlayerWidget(c, id))}
      promote={async (c) => {
        try {
          await api(`/players/${playerId}/dashboard-widgets`, {
            method: "POST",
            body: JSON.stringify({ department_slug: departmentSlug, spec: c.spec }),
          });
          toast.success(`Gráfico agregado al panel de ${departmentName}.`);
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

/** Wrap a resolved payload into the per-player `DashboardWidget` shape the
 *  per-player renderers expect (they read `widget.data`). */
function toPlayerWidget(chart: ChartResult, id: string): DashboardWidget {
  const spec = chart.spec as { display_config?: Record<string, unknown> } | undefined;
  return {
    id,
    chart_type: chart.chart_type,
    title: chart.title ?? "",
    description: "",
    column_span: 12,
    chart_height: null,
    sort_order: 0,
    display_config: spec?.display_config ?? {},
    data: chart as unknown as WidgetData,
  };
}
