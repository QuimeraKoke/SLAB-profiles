"use client";

import React, { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DashboardWidget, LineWithSelectorPayload } from "@/lib/types";
import styles from "./Widget.module.css";

interface LineWithSelectorProps {
  widget: DashboardWidget;
}

export default function LineWithSelector({ widget }: LineWithSelectorProps) {
  const data = widget.data as LineWithSelectorPayload;
  const fields = data.available_fields ?? [];
  const [activeKey, setActiveKey] = useState<string>(fields[0]?.key ?? "");

  const activeField = fields.find((f) => f.key === activeKey) ?? fields[0];

  const distinctTemplates = new Set(
    fields.map((f) => f.template_id).filter(Boolean),
  );
  const showTemplateLabel = distinctTemplates.size > 1;

  const config = (widget.display_config ?? {}) as {
    x_axis_title?: string;
    y_axis_title?: string;
  };
  const xAxisTitle = config.x_axis_title ?? "Fecha";
  const defaultYTitle = activeField
    ? `${activeField.label}${activeField.unit ? ` (${activeField.unit})` : ""}`
    : "";
  const yAxisTitle = config.y_axis_title ?? defaultYTitle;

  const activeSeries = useMemo(() => {
    if (!activeField) return [];
    const points = data.series[activeField.key] ?? [];
    return points
      .filter((p) => p.value !== null && p.value !== undefined)
      .map((p) => ({
        recorded_at: p.recorded_at,
        value: p.value as number,
        label: formatShortDate(p.recorded_at),
      }));
  }, [data.series, activeField]);

  if (fields.length === 0) {
    return (
      <div className={styles.widget}>
        <header className={styles.header}>
          <h4 className={styles.title}>{widget.title}</h4>
        </header>
        <div className={styles.empty}>Sin variables configuradas.</div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
        <select
          className={styles.fieldSelect}
          value={activeField?.key}
          onChange={(e) => setActiveKey(e.target.value)}
        >
          {fields.map((f) => {
            const prefix =
              showTemplateLabel && f.template_label ? `${f.template_label} — ` : "";
            return (
              <option key={f.key} value={f.key}>
                {prefix}
                {f.label}
                {f.unit ? ` (${f.unit})` : ""}
              </option>
            );
          })}
        </select>
      </header>

      {activeSeries.length === 0 ? (
        <div className={styles.empty}>Sin datos para esta variable.</div>
      ) : (
        <div className={styles.chartArea} style={{ height: widget.chart_height ?? 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={activeSeries} margin={{ top: 8, right: 16, left: 8, bottom: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "#6b7280" }}
                stroke="#d1d5db"
                label={{
                  value: xAxisTitle,
                  position: "insideBottom",
                  offset: -12,
                  style: { fill: "#6b7280", fontSize: 11, fontWeight: 600 },
                }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#6b7280" }}
                stroke="#d1d5db"
                width={72}
                domain={["auto", "auto"]}
                label={
                  yAxisTitle
                    ? {
                        value: yAxisTitle,
                        angle: -90,
                        position: "insideLeft",
                        offset: 8,
                        style: {
                          textAnchor: "middle",
                          fill: "#6b7280",
                          fontSize: 11,
                          fontWeight: 600,
                        },
                      }
                    : undefined
                }
              />
              <Tooltip
                content={(p) => <ChartTooltip {...p} unit={activeField?.unit ?? ""} />}
                cursor={{ stroke: "#9ca3af", strokeDasharray: "3 3" }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ r: 3, fill: "#3b82f6" }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

interface TooltipProps {
  active?: boolean;
  // `readonly` so the type matches Recharts' TooltipPayload which marks
  // its payload as readonly. We only read from it.
  payload?: ReadonlyArray<{ payload?: { value?: number; recorded_at?: string } }>;
  unit: string;
}

function ChartTooltip({ active, payload, unit }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point || typeof point.value !== "number" || !point.recorded_at) return null;
  return (
    <div className={styles.chartTooltip}>
      <span className={styles.chartTooltipDate}>{formatLongDate(point.recorded_at)}</span>
      <span className={styles.chartTooltipValue}>
        {point.value.toFixed(1)}
        {unit ? ` ${unit}` : ""}
      </span>
    </div>
  );
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}`;
}

function formatLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
