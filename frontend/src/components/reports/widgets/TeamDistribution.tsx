"use client";

import React, { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  TeamDistributionPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamDistribution.module.css";

interface Props {
  widget: TeamReportWidget;
}

export default function TeamDistribution({ widget }: Props) {
  const data = widget.data as TeamDistributionPayload;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const unit = data.field?.unit ? ` ${data.field.unit}` : "";

  const chartData = useMemo(
    () =>
      (data.bins ?? []).map((b, i) => ({
        index: i,
        // X-axis label: midpoint, two decimals.
        label: ((b.low + b.high) / 2).toFixed(1),
        rangeLabel: `${b.low.toFixed(1)} – ${b.high.toFixed(1)}`,
        count: b.count,
      })),
    [data.bins],
  );

  if (data.empty || (data.bins ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} data={data} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  const height = widget.chart_height ?? 240;
  const hoveredBin =
    hoverIndex !== null && data.bins ? data.bins[hoverIndex] : null;

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <div className={styles.statsRow}>
        <Stat label="N" value={data.stats.n} format="int" />
        <Stat label="Media" value={data.stats.mean} unit={unit} />
        <Stat label="Mediana" value={data.stats.median} unit={unit} />
        <Stat label="Min" value={data.stats.min} unit={unit} />
        <Stat label="Max" value={data.stats.max} unit={unit} />
      </div>

      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <BarChart
            data={chartData}
            margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
          >
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fill: "#6b7280", fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fill: "#6b7280", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const point = payload[0]?.payload as {
                  rangeLabel: string;
                  count: number;
                };
                return (
                  <div className={styles.tooltip}>
                    <span className={styles.tooltipRange}>
                      {point.rangeLabel}{unit}
                    </span>
                    <span className={styles.tooltipCount}>
                      {point.count} jugador{point.count === 1 ? "" : "es"}
                    </span>
                  </div>
                );
              }}
            />
            <Bar
              dataKey="count"
              fill="#6d28d9"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
              onMouseEnter={(_, idx) => setHoverIndex(idx)}
              onMouseLeave={() => setHoverIndex(null)}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {hoveredBin && hoveredBin.players.length > 0 && (
        <div className={styles.binDetail}>
          <span className={styles.binDetailLabel}>
            {hoveredBin.low.toFixed(1)}–{hoveredBin.high.toFixed(1)}{unit}:
          </span>
          <span className={styles.binDetailPlayers}>
            {hoveredBin.players
              .map((p) => `${p.name} (${p.value.toFixed(1)})`)
              .join(", ")}
          </span>
        </div>
      )}
    </div>
  );
}

function Header({
  widget,
  data,
}: {
  widget: TeamReportWidget;
  data: TeamDistributionPayload;
}) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
      {data.field && (
        <span className={styles.fieldTag}>
          {data.field.label}
          {data.field.unit ? ` · ${data.field.unit}` : ""}
        </span>
      )}
    </header>
  );
}

interface StatProps {
  label: string;
  value?: number;
  unit?: string;
  format?: "int";
}

function Stat({ label, value, unit, format }: StatProps) {
  if (value === undefined || value === null) return null;
  const display =
    format === "int" ? String(value) : value.toFixed(2);
  return (
    <div className={styles.statItem}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>
        {display}{format === "int" ? "" : unit ?? ""}
      </span>
    </div>
  );
}
