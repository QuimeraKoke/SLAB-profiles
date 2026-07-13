// API client for the in-app panel builder (§2.c) — arrange + add team-report
// widgets. All endpoints are Editor-role gated on the backend.

import { api } from "@/lib/api";

export interface WidgetPatch {
  column_span?: number;
  title?: string;
  sort_order?: number;
  section_id?: string;
}

export function updateWidget(id: string, patch: WidgetPatch): Promise<unknown> {
  return api(`/reports/widgets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteWidget(id: string): Promise<unknown> {
  return api(`/reports/widgets/${id}`, { method: "DELETE" });
}

export function reorderWidgets(widgetIds: string[]): Promise<unknown> {
  return api(`/reports/widgets/reorder`, {
    method: "POST",
    body: JSON.stringify({ widget_ids: widgetIds }),
  });
}

/** Column-span presets offered by the resize control (12-col grid). */
export const SPAN_PRESETS: { value: number; label: string }[] = [
  { value: 3, label: "¼" },
  { value: 4, label: "⅓" },
  { value: 6, label: "½" },
  { value: 12, label: "Completo" },
];
