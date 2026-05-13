"use client";

import React, { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  TeamDistributionBandCount,
  TeamDistributionPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamDistribution.module.css";

const DEFAULT_BAR_COLOR = "#6d28d9";

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
        color: b.color ?? DEFAULT_BAR_COLOR,
        bandLabel: b.band_label ?? null,
      })),
    [data.bins],
  );

  const bandCounts = data.band_counts ?? null;

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

      {bandCounts && bandCounts.length > 0 && (
        <BandCountsRow counts={bandCounts} unit={unit} />
      )}

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
                  bandLabel: string | null;
                };
                return (
                  <div className={styles.tooltip}>
                    {point.bandLabel && (
                      <span className={styles.tooltipBand}>
                        Banda {point.bandLabel}
                      </span>
                    )}
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
              fill={DEFAULT_BAR_COLOR}
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
              onMouseEnter={(_, idx) => setHoverIndex(idx)}
              onMouseLeave={() => setHoverIndex(null)}
            >
              {chartData.map((entry) => (
                <Cell key={entry.index} fill={entry.color} />
              ))}
            </Bar>
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

/** Distributions with fewer than this many players in the filtered roster
 *  are flagged in the UI — too few samples to be a meaningful reference. */
const LIMITED_REFERENCE_THRESHOLD = 5;

function Header({
  widget,
  data,
}: {
  widget: TeamReportWidget;
  data: TeamDistributionPayload;
}) {
  const rosterSize = data.roster_size;
  const limitedReference =
    typeof rosterSize === "number"
    && rosterSize > 0
    && rosterSize < LIMITED_REFERENCE_THRESHOLD;
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
        {limitedReference && (
          <p className={styles.limitedBadge}>
            Con {rosterSize} jugador{rosterSize === 1 ? "" : "es"} — referencia limitada
          </p>
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

interface BandCountsRowProps {
  counts: TeamDistributionBandCount[];
  unit: string;
}

function BandCountsRow({ counts, unit }: BandCountsRowProps) {
  return (
    <div className={styles.bandCountsRow} aria-label="Conteo por banda clínica">
      {counts.map((band, idx) => {
        const range = bandRangeText(band, unit);
        return (
          <div key={`${band.label}-${idx}`} className={styles.bandChip}>
            <span
              className={styles.bandSwatch}
              style={{ background: band.color ?? DEFAULT_BAR_COLOR }}
            />
            <div className={styles.bandChipText}>
              <span className={styles.bandLabel}>{band.label}</span>
              {range && <span className={styles.bandRange}>{range}</span>}
            </div>
            <span className={styles.bandCount}>{band.count}</span>
          </div>
        );
      })}
    </div>
  );
}

function bandRangeText(band: TeamDistributionBandCount, unit: string): string {
  const u = unit.trim();
  const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
  if (band.min === null && band.max !== null) return `≤ ${fmt(band.max)}${u ? " " + u : ""}`;
  if (band.min !== null && band.max === null) return `≥ ${fmt(band.min)}${u ? " " + u : ""}`;
  if (band.min !== null && band.max !== null) return `${fmt(band.min)} – ${fmt(band.max)}${u ? " " + u : ""}`;
  return "";
}
