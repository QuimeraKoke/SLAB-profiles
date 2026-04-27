"use client";

import React, { lazy, Suspense } from "react";

import StatCard from "./StatCard";
import type { VisualizerProps } from "./types";

/**
 * The component registry that PROJECT.md asks for.
 *
 * Mapping `chart_type` strings → React components is the *only* place new
 * visualizations need to be wired in. Anywhere else in the app stays
 * data-driven.
 *
 * Heavier components (LineChart pulls in recharts; BodyMap will pull in SVG
 * assets) are lazy-loaded so the initial bundle stays small. StatCard is
 * eagerly imported because it's tiny and used everywhere.
 */
const LineChart = lazy(() => import("./LineChart"));
const BodyMap = lazy(() => import("./BodyMap"));

const ComponentRegistry: Record<string, React.ComponentType<VisualizerProps>> = {
  stat_card: StatCard,
  line: LineChart,
  body_map: BodyMap,
};

export function DynamicVisualizer({ field, series }: VisualizerProps) {
  const chartType = field.chart_type;
  if (!chartType) return null;

  const Component = ComponentRegistry[chartType];
  if (!Component) {
    return (
      <div style={{ padding: 12, fontSize: 12, color: "#6b7280" }}>
        Unsupported chart_type: <code>{chartType}</code>
      </div>
    );
  }

  return (
    <Suspense fallback={<div style={{ padding: 12, color: "#9ca3af" }}>Cargando…</div>}>
      <Component field={field} series={series} />
    </Suspense>
  );
}

export { ComponentRegistry };
