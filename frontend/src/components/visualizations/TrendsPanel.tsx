"use client";

import React, { useMemo } from "react";

import type { ExamField, ExamResult, ExamTemplate } from "@/lib/types";
import { DynamicVisualizer } from "./Registry";
import type { SeriesPoint } from "./types";
import styles from "./TrendsPanel.module.css";

interface TrendsPanelProps {
  results: ExamResult[];
  templates: ExamTemplate[];
}

interface FieldSeries {
  field: ExamField;
  series: SeriesPoint[];
}

/**
 * Aggregates results into one series per (field key + chart_type), so the same
 * metric across multiple templates plots on a single chart. Returns groups
 * keyed by `chart_type` so the panel can split stat cards (compact grid) from
 * full-width visualizations like line charts.
 */
function buildSeries(results: ExamResult[], templates: ExamTemplate[]): FieldSeries[] {
  const templateById = new Map(templates.map((t) => [t.id, t]));
  // Map from "key|chart_type" → field metadata + accumulated points
  const acc = new Map<string, FieldSeries>();

  // Process results oldest-first so series end up chronological without re-sorting.
  const sorted = [...results].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime(),
  );

  for (const result of sorted) {
    const template = templateById.get(result.template_id);
    const fields = template?.config_schema?.fields ?? [];
    for (const field of fields) {
      if (!field.chart_type) continue;
      if (!(field.key in result.result_data)) continue;
      const dedupKey = `${field.key}|${field.chart_type}`;
      let entry = acc.get(dedupKey);
      if (!entry) {
        entry = { field, series: [] };
        acc.set(dedupKey, entry);
      }
      entry.series.push({
        recorded_at: result.recorded_at,
        value: result.result_data[field.key] as SeriesPoint["value"],
      });
    }
  }

  return Array.from(acc.values());
}

const STAT_CHART_TYPES = new Set(["stat_card"]);

export default function TrendsPanel({ results, templates }: TrendsPanelProps) {
  const seriesGroups = useMemo(() => buildSeries(results, templates), [results, templates]);

  if (seriesGroups.length === 0) return null;

  const stats = seriesGroups.filter((g) => STAT_CHART_TYPES.has(g.field.chart_type ?? ""));
  const wide = seriesGroups.filter((g) => !STAT_CHART_TYPES.has(g.field.chart_type ?? ""));

  return (
    <section className={styles.container}>
      <h3 className={styles.heading}>Tendencias</h3>

      {stats.length > 0 && (
        <div className={styles.statsGrid}>
          {stats.map(({ field, series }) => (
            <DynamicVisualizer key={`${field.key}|stat`} field={field} series={series} />
          ))}
        </div>
      )}

      {wide.length > 0 && (
        <div className={styles.wideGrid}>
          {wide.map(({ field, series }) => (
            <DynamicVisualizer key={`${field.key}|${field.chart_type}`} field={field} series={series} />
          ))}
        </div>
      )}
    </section>
  );
}
