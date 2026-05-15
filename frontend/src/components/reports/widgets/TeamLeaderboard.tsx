"use client";

import React from "react";

import type {
  TeamLeaderboardPayload,
  TeamReportWidget,
} from "@/lib/types";

import styles from "./TeamLeaderboard.module.css";

interface Props {
  widget: TeamReportWidget;
}

const AGGREGATOR_LABELS: Record<TeamLeaderboardPayload["aggregator"], string> = {
  sum: "Total",
  avg: "Promedio",
  max: "Máximo",
  latest: "Última toma",
};

// Field-by-field palette for multi_field mode. Same order as
// TeamHorizontalComparison so the two read consistently when stacked
// on the same page.
const FIELD_COLORS = [
  "#dc2626",
  "#0ea5e9",
  "#16a34a",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
];

type LeaderboardRow = TeamLeaderboardPayload["rows"][number];
type SingleRow = Extract<LeaderboardRow, { value: number }>;
type MultiRow = Extract<LeaderboardRow, { values: Record<string, number | null> }>;
const isMultiRow = (row: LeaderboardRow): row is MultiRow => "values" in row;

/** Top-N podium ranking (mode="single") or grouped bars per field
 *  (mode="multi_field"). The mode flips both the row shape and the
 *  rendering — see the discriminated row type above. */
export default function TeamLeaderboard({ widget }: Props) {
  const data = widget.data as TeamLeaderboardPayload;
  const isMultiField = data.mode === "multi_field";

  if (data.empty || (data.rows ?? []).length === 0) {
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

  if (isMultiField) {
    return <MultiFieldView widget={widget} data={data} />;
  }

  if (data.style === "vertical_bars") {
    return <VerticalBarsView widget={widget} data={data} />;
  }

  const unit = data.field?.unit ? ` ${data.field.unit}` : "";

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <ol className={styles.list}>
        {data.rows.filter((r): r is SingleRow => !isMultiRow(r)).map((row) => (
          <li
            key={row.player_id}
            className={`${styles.row} ${podiumClass(row.rank, styles)}`}
          >
            <span className={styles.rank}>#{row.rank}</span>
            <span className={styles.name} title={row.player_name}>
              {row.player_name}
            </span>
            <span className={styles.value}>
              {formatNumber(row.value)}{unit}
            </span>
            <span className={styles.samples}>
              {row.samples} {row.samples === 1 ? "toma" : "tomas"}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function VerticalBarsView({
  widget, data,
}: { widget: TeamReportWidget; data: TeamLeaderboardPayload }) {
  const unit = data.field?.unit ? ` ${data.field.unit}` : "";
  const decimals = typeof data.decimals === "number" ? data.decimals : null;

  // Prefer the new array form; fall back to the legacy single line.
  const refLines = React.useMemo(() => {
    if (data.reference_lines && data.reference_lines.length > 0) {
      return data.reference_lines;
    }
    return data.reference_line ? [data.reference_line] : [];
  }, [data.reference_lines, data.reference_line]);

  const refBands = React.useMemo(
    () => data.reference_bands ?? [],
    [data.reference_bands],
  );

  // Y-axis scale. If the resolver provided explicit y_min/y_max, use
  // those (zoom mode — for densities near 1.0, pH, etc.). Otherwise
  // default to [0, dataMax] including every overlay value so nothing
  // gets clipped above the chart.
  const { yMin, yMax } = React.useMemo(() => {
    const explicitMin = typeof data.y_min === "number" ? data.y_min : null;
    const explicitMax = typeof data.y_max === "number" ? data.y_max : null;

    let dataMax = 0;
    for (const row of data.rows) {
      if (!isMultiRow(row) && row.value > dataMax) dataMax = row.value;
    }
    for (const rl of refLines) {
      if (rl.value > dataMax) dataMax = rl.value;
    }
    for (const rb of refBands) {
      if (rb.max !== null && rb.max > dataMax) dataMax = rb.max;
      if (rb.min !== null && rb.min > dataMax) dataMax = rb.min;
    }
    const min = explicitMin ?? 0;
    const max = explicitMax ?? (dataMax > 0 ? dataMax : 1);
    return { yMin: min, yMax: max > min ? max : min + 1 };
  }, [data.y_min, data.y_max, data.rows, refLines, refBands]);

  // % position of a Y-axis value within [yMin, yMax]. Bottom = yMin, top = yMax.
  const yPercent = React.useCallback(
    (v: number) => {
      const clamped = Math.max(yMin, Math.min(yMax, v));
      return ((clamped - yMin) / (yMax - yMin)) * 100;
    },
    [yMin, yMax],
  );

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />
      <div className={styles.vBarsChart}>
        <div className={styles.vBarsArea}>
          {refBands.map((band, i) => {
            // Clamp band edges into the zoomed [yMin, yMax] viewport so
            // a band that extends beyond the chart still renders to the
            // edge instead of being skipped.
            const topPct = band.max !== null ? 100 - yPercent(band.max) : 0;
            const bottomPct = band.min !== null ? yPercent(band.min) : 0;
            const heightPct = Math.max(0, 100 - topPct - bottomPct);
            if (heightPct <= 0) return null;
            return (
              <div
                key={`band-${i}`}
                className={styles.refBand}
                style={{
                  top: `${topPct}%`,
                  height: `${heightPct}%`,
                  background: band.color,
                }}
              >
                {band.label && (
                  <span className={styles.refBandLabel}>{band.label}</span>
                )}
              </div>
            );
          })}
          {refLines.map((line, i) => {
            const top = 100 - yPercent(line.value);
            return (
              <div
                key={`line-${i}`}
                className={styles.refLine}
                style={{ top: `${top}%`, borderColor: line.color }}
              >
                <span
                  className={styles.refLabel}
                  style={{ color: line.color }}
                >
                  {line.label
                    ? `${line.label}: ${formatNumber(line.value, decimals)}${unit}`
                    : `${formatNumber(line.value, decimals)}${unit}`}
                </span>
              </div>
            );
          })}
          {data.rows.filter((r): r is SingleRow => !isMultiRow(r)).map((row) => {
            // Bar starts at yMin (the chart's baseline when zoomed). When
            // a value falls BELOW yMin the bar becomes 0 — clamp via the
            // helper. min-height = 1% so a non-zero value is always visible.
            const heightPct = row.value > 0 ? Math.max(1, yPercent(row.value)) : 0;
            return (
              <div key={row.player_id} className={styles.vBarCol}>
                <span className={styles.vBarValue}>
                  {row.value > 0 ? formatNumber(row.value, decimals) : "—"}
                </span>
                <div
                  className={styles.vBar}
                  style={{ height: `${heightPct}%` }}
                  title={`${row.player_name}: ${formatNumber(row.value, decimals)}${unit}`}
                />
                <span className={styles.vBarLabel} title={row.player_name}>
                  {shortPlayerName(row.player_name)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MultiFieldView({
  widget, data,
}: { widget: TeamReportWidget; data: TeamLeaderboardPayload }) {
  const fields = React.useMemo(() => data.fields ?? [], [data.fields]);

  // Per-field max so each bar is sized vs its own metric's team-wide
  // max (different units can't share a scale).
  const maxByField = React.useMemo(() => {
    const out: Record<string, number> = {};
    for (const f of fields) {
      let m = 0;
      for (const row of data.rows) {
        if (!isMultiRow(row)) continue;
        const v = row.values[f.key];
        if (typeof v === "number" && v > m) m = v;
      }
      out[f.key] = m > 0 ? m : 1;
    }
    return out;
  }, [fields, data.rows]);

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <div className={styles.legend} aria-hidden="true">
        {fields.map((f, i) => (
          <span key={f.key} className={styles.legendItem}>
            <span
              className={styles.legendSwatch}
              style={{ background: FIELD_COLORS[i % FIELD_COLORS.length] }}
            />
            {f.label}{f.unit ? ` (${f.unit})` : ""}
          </span>
        ))}
      </div>

      <div className={styles.multiBody}>
        {data.rows.filter(isMultiRow).map((row) => (
          <div key={row.player_id} className={styles.multiRow}>
            <span className={styles.multiName} title={row.player_name}>
              {row.player_name}
            </span>
            <div className={styles.multiBars}>
              {fields.map((f, i) => {
                const value = row.values[f.key];
                if (typeof value !== "number") {
                  return (
                    <div key={f.key} className={styles.multiBarRow}>
                      <div className={styles.multiBarEmpty}>—</div>
                      <span className={styles.multiBarLabel}>{f.label}</span>
                    </div>
                  );
                }
                const fieldMax = maxByField[f.key] || 1;
                const widthPct = Math.max(2, (value / fieldMax) * 100);
                const color = FIELD_COLORS[i % FIELD_COLORS.length];
                const fieldUnit = f.unit ? ` ${f.unit}` : "";
                return (
                  <div key={f.key} className={styles.multiBarRow}>
                    <div
                      className={styles.multiBar}
                      style={{ width: `${widthPct}%`, background: color }}
                      title={`${f.label} · ${value}${fieldUnit}`}
                    >
                      <span className={styles.multiBarValue}>
                        {formatNumber(value)}{fieldUnit}
                      </span>
                    </div>
                    <span className={styles.multiBarLabel}>{f.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function podiumClass(rank: number, styles: Record<string, string>): string {
  if (rank === 1) return styles.rowGold;
  if (rank === 2) return styles.rowSilver;
  if (rank === 3) return styles.rowBronze;
  return "";
}

function Header({
  widget, data,
}: { widget: TeamReportWidget; data: TeamLeaderboardPayload }) {
  const aggLabel = AGGREGATOR_LABELS[data.aggregator] ?? data.aggregator;
  const fieldLabel = data.field
    ? data.field.unit
      ? `${data.field.label} (${data.field.unit})`
      : data.field.label
    : "";
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
      {fieldLabel && (
        <span className={styles.subtitleTag}>
          {aggLabel} · {fieldLabel}
        </span>
      )}
    </header>
  );
}

function formatNumber(n: number, decimals?: number | null): string {
  if (typeof decimals === "number") {
    return n.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}

/** Shrink "Lucas Romero Rivera" → "L. Rivera" so 25+ vertical-bar
 *  labels fit without overlapping. Single-word names stay as-is. */
function shortPlayerName(full: string): string {
  const parts = full.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return full;
  const initial = parts[0][0].toUpperCase();
  const lastWord = parts[parts.length - 1];
  return `${initial}. ${lastWord}`;
}
