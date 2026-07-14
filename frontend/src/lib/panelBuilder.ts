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

// ── Add widget (reuses the promote-from-spec endpoint) ───────────────────────

export interface WidgetOptionTemplate {
  slug: string;
  name: string;
  department: string;
  numeric_fields: { key: string; label: string; unit: string }[];
}
export interface WidgetOptionChartType {
  value: string;
  label: string;
  multi_field: boolean;
}
export interface WidgetOptions {
  templates: WidgetOptionTemplate[];
  chart_types: WidgetOptionChartType[];
}

export interface WidgetSpec {
  chart_type: string;
  title: string;
  sources: {
    template_slug: string;
    field_keys: string[];
    aggregation: string;
    aggregation_param?: number;
  }[];
  display_config?: Record<string, unknown>;
}

export function fetchWidgetOptions(deptSlug: string, categoryId: string): Promise<WidgetOptions> {
  return api<WidgetOptions>(`/reports/${deptSlug}/widget-options?category_id=${categoryId}`);
}

export function addWidget(deptSlug: string, categoryId: string, spec: WidgetSpec): Promise<unknown> {
  return api(`/reports/${deptSlug}/widgets`, {
    method: "POST",
    body: JSON.stringify({ category_id: categoryId, spec }),
  });
}

// ── Edit an existing widget's config in place (§5 / Fase 5) ──────────────────

export interface WidgetConfig {
  chart_type: string;
  title: string;
  template_slug: string;
  field_keys: string[];
  aggregation: string;
  display_config: Record<string, unknown>;
}

export function fetchWidgetConfig(widgetId: string): Promise<WidgetConfig> {
  return api<WidgetConfig>(`/reports/widgets/${widgetId}/config`);
}

export function editWidget(widgetId: string, spec: WidgetSpec): Promise<unknown> {
  return api(`/reports/widgets/${widgetId}/config`, {
    method: "PATCH",
    body: JSON.stringify({ spec }),
  });
}
