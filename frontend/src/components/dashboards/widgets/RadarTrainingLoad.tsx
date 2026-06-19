"use client";

import React, { useMemo } from "react";
import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import type { DashboardWidget, TrainingRadarPayload, TrainingRadarAxis } from "@/lib/types";
import styles from "./Widget.module.css";

interface Props {
  widget: DashboardWidget;
}

/** Radar comparing the latest training session's GPS variables against the
 *  player's chronic match load (100% ring). Each axis = training % of chronic. */
export default function RadarTrainingLoad({ widget }: Props) {
  const data = widget.data as TrainingRadarPayload;
  const axes = data.axes ?? [];

  const chartData = useMemo(
    () =>
      axes.map((a) => ({
        axis: a.label,
        entrenamiento: a.pct,
        cronica: data.reference_pct ?? 100,
        meta: a,
      })),
    [axes, data.reference_pct],
  );

  // Domain headroom so a >100% axis (training above match) stays on-canvas.
  const maxPct = axes.reduce((m, a) => Math.max(m, a.pct), 0);
  const domainMax = Math.max(120, Math.ceil(maxPct / 20) * 20);

  if (data.empty || axes.length === 0) {
    return (
      <div className={styles.widget}>
        <header className={styles.header}>
          <h4 className={styles.title}>{widget.title}</h4>
        </header>
        <div className={styles.empty}>Sin sesión de entrenamiento para comparar.</div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
        {data.session_date && (
          <span className={styles.headerTag}>Sesión {formatDate(data.session_date)}</span>
        )}
      </header>
      <div className={styles.chartArea} style={{ height: widget.chart_height ?? 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={chartData} outerRadius="68%" margin={{ top: 8, right: 24, bottom: 8, left: 24 }}>
            <PolarGrid stroke="#e5e7eb" />
            <PolarAngleAxis dataKey="axis" tick={{ fontSize: 10, fill: "#475467" }} />
            <PolarRadiusAxis
              angle={90}
              domain={[0, domainMax]}
              tick={{ fontSize: 9, fill: "#98a2b3" }}
              tickFormatter={(v) => `${v}%`}
            />
            <Radar
              name="Carga crónica (100%)"
              dataKey="cronica"
              stroke="#e7b07a"
              fill="#e7b07a"
              fillOpacity={0.28}
              isAnimationActive={false}
            />
            <Radar
              name="Entrenamiento"
              dataKey="entrenamiento"
              stroke="#e2483d"
              fill="#e2483d"
              fillOpacity={0.32}
              isAnimationActive={false}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Tooltip content={(p) => <RadarTooltip {...p} />} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: { meta?: TrainingRadarAxis } }>;
}

function RadarTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const m = payload[0]?.payload?.meta;
  if (!m) return null;
  const unit = m.unit ? ` ${m.unit}` : "";
  return (
    <div className={styles.chartTooltip}>
      <span className={styles.chartTooltipDate}>{m.label}</span>
      <span className={styles.chartTooltipValue}>
        {m.pct}% de la carga crónica
      </span>
      <span style={{ fontSize: 11, color: "#6b7280" }}>
        entren. {m.training_value}{unit} · crónica {m.reference_value}{unit}
      </span>
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
