"use client";

import React, { useMemo } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  TeamDailyGroupedBarsPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamDailyGroupedBars.module.css";

interface Props {
  widget: TeamReportWidget;
}

/**
 * Per-day grouped bars across N metrics, with an optional overlay line
 * showing the per-day sum (e.g. "Total Bienestar" on Check-IN).
 *
 * Y axis is the metric value (mean across roster). X axis is the day.
 * Bars within a day are grouped side-by-side, one per field. The Line
 * overlay is drawn on a SECOND Y axis so a 5-25 total doesn't crush
 * a 1-5 per-axis scale.
 */
export default function TeamDailyGroupedBars({ widget }: Props) {
  const data = widget.data as TeamDailyGroupedBarsPayload;
  const fields = data.fields ?? [];
  // Stabilize the array reference so the chartData useMemo deps don't
  // churn on every render.
  const buckets = useMemo(() => data.buckets ?? [], [data.buckets]);

  // Recharts wants an array of plain objects. Map each bucket so its
  // field values are reachable by the Bar's dataKey, plus a `_total`
  // key for the overlay line.
  const chartData = useMemo(
    () =>
      buckets.map((b) => ({
        label: b.label,
        iso: b.iso,
        _total: b.total ?? undefined,
        ...Object.fromEntries(
          Object.entries(b.values).map(([k, v]) => [
            k,
            v === null ? undefined : v,
          ]),
        ),
      })),
    [buckets],
  );

  if (data.empty || buckets.length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  const height = widget.chart_height ?? 320;

  // Build Recharts axis domains. When the resolver pins them via
  // y_min/y_max we hand them through verbatim; otherwise pass undefined
  // so recharts auto-scales as before.
  const barsDomain = buildDomain(data.y_min, data.y_max);
  const totalDomain = buildDomain(data.total_y_min, data.total_y_max);
  const decimals = typeof data.decimals === "number" ? data.decimals : 2;

  return (
    <div className={styles.widget}>
      <Header widget={widget} />
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <ComposedChart data={chartData} margin={{ top: 16, right: 24, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fill: "#6b7280", fontSize: 11 }} />
            <YAxis
              yAxisId="bars"
              tick={{ fill: "#6b7280", fontSize: 11 }}
              allowDecimals
              domain={barsDomain}
            />
            {data.show_total_line && (
              <YAxis
                yAxisId="total"
                orientation="right"
                tick={{ fill: "#6b7280", fontSize: 11 }}
                domain={totalDomain}
              />
            )}
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div className={styles.tooltip}>
                    <span className={styles.tooltipDate}>{label}</span>
                    {payload.map((p) => (
                      <span key={String(p.dataKey)} className={styles.tooltipRow}>
                        <span
                          className={styles.tooltipSwatch}
                          style={{ background: String(p.color) }}
                        />
                        <span className={styles.tooltipLabel}>{p.name}</span>
                        <span className={styles.tooltipValue}>
                          {typeof p.value === "number"
                            ? p.value.toFixed(decimals)
                            : "—"}
                        </span>
                      </span>
                    ))}
                  </div>
                );
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: "0.72rem", paddingTop: "8px" }}
            />
            {fields.map((f) => (
              <Bar
                key={f.key}
                yAxisId="bars"
                dataKey={f.key}
                name={f.label}
                fill={f.color}
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              />
            ))}
            {data.show_total_line && (
              <Line
                yAxisId="total"
                type="monotone"
                dataKey="_total"
                name={data.total_label || "Total"}
                stroke={data.total_color || "#111827"}
                strokeWidth={2}
                dot={{ r: 3, fill: data.total_color || "#111827" }}
                isAnimationActive={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Header({ widget }: { widget: TeamReportWidget }) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
    </header>
  );
}

/** Build a recharts `domain` prop from optional resolver-provided
 *  min/max. Returns `undefined` when nothing is set so recharts'
 *  default auto-domain kicks in. Recharts accepts `["auto", "auto"]`
 *  as a sentinel for each end. */
function buildDomain(
  min: number | null | undefined,
  max: number | null | undefined,
): [number | "auto", number | "auto"] | undefined {
  if ((min === null || min === undefined) && (max === null || max === undefined)) {
    return undefined;
  }
  return [
    typeof min === "number" ? min : "auto",
    typeof max === "number" ? max : "auto",
  ];
}
