"use client";

import React from "react";

import { api } from "@/lib/api";
import type { DashboardWidget, WidgetData } from "@/lib/types";
import { renderWidget } from "@/components/dashboards/widgets";
import AssistantPanel, { type ChartResult } from "@/components/reports/AssistantPanel";

interface Props {
  playerId: string;
  playerName: string;
}

const SUGGESTIONS = [
  "¿Qué debería mirar de este jugador hoy?",
  "Mostrame la evolución de sus métricas con alerta.",
  "Compará sus últimas tomas físicas en un gráfico.",
];

/**
 * Resumen-tab assistant: a cross-department, per-player Q&A bar that can
 * propose charts to REVIEW inline. Charts are TRANSIENT — the Resumen view is
 * not a configurable layout, so there is no promote/pin action (we omit the
 * `promote` prop, which hides the button).
 */
export default function ResumenAssistant({ playerId, playerName }: Props) {
  return (
    <AssistantPanel
      label="Preguntar a S-LAB AI"
      scope={playerName}
      suggestions={SUGGESTIONS}
      sendMessage={(messages) =>
        api<{ reply: string; charts: ChartResult[] }>("/assistant/player/resumen", {
          method: "POST",
          body: JSON.stringify({
            player_id: playerId,
            messages,
            date_from: null,
            date_to: null,
          }),
        })
      }
      renderChart={(c, id) => renderWidget(toPlayerWidget(c, id))}
      // No `promote` → charts render for review only (Resumen isn't configurable).
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
