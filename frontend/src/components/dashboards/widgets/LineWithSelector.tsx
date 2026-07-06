"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";
import type {
  CrossExamMatchInfo,
  DashboardWidget,
  LineWithSelectorPayload,
  PositionComparison,
} from "@/lib/types";
import { ChartWindowNav, fullRangeDomain, useChartWindow, windowRangeLabel } from "./ChartWindow";
import { MovingAvgControl, trailingMean, useMovingAverage } from "./MovingAverage";
import styles from "./Widget.module.css";

interface LineWithSelectorProps {
  widget: DashboardWidget;
  /** Present when the widget lives on a player profile — enables the
   *  same-position comparison toggle (data is fetched on demand). */
  playerId?: string;
}

// Reference-line styling by kind: load context (match acute/chronic) vs peer
// averages (team / same-position).
const REF_LINE_COLORS: Record<string, string> = {
  acute: "#f59e0b",
  chronic: "#7c3aed",
  team: "#64748b",
  position: "#0d9488",
};
const REF_LINE_FALLBACK: Record<string, string> = {
  acute: "Aguda",
  chronic: "Crónica",
  team: "Equipo",
  position: "Posición",
};

type CompareMode = "none" | "mean" | "players";

const MEAN_COLOR = "#7c3aed";
const PEER_PALETTE = [
  "#94a3b8",
  "#f59e0b",
  "#10b981",
  "#a855f7",
  "#06b6d4",
  "#f97316",
  "#84cc16",
  "#ec4899",
];

export default function LineWithSelector({ widget, playerId }: LineWithSelectorProps) {
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

  const ma = useMovingAverage();

  const activeSeries = useMemo(() => {
    if (!activeField) return [];
    const points = data.series[activeField.key] ?? [];
    const rows = points
      .filter((p) => p.value !== null && p.value !== undefined)
      .map((p) => ({
        recorded_at: p.recorded_at,
        day: p.recorded_at.slice(0, 10),
        value: p.value as number,
        label: formatShortDate(p.recorded_at),
      }));
    // Computed over the FULL series (not the visible window) so the first
    // visible points still average real prior history when paging back.
    const avg = trailingMean(rows.map((r) => r.value), ma.windowSize);
    return rows.map((r, i) => ({ ...r, mov_avg: avg[i] }));
  }, [data.series, activeField, ma.windowSize]);

  // Each chart owns its time window: latest points first, chevrons to page
  // back through history. Re-anchors when the user switches variable.
  const window = useChartWindow(activeSeries, undefined, activeField?.key);

  // Acute / chronic match-load reference lines for the active variable.
  const refLines = (activeField && data.reference_lines?.[activeField.key]) || [];

  // ---- Same-position comparison (on-demand) -------------------------------
  const [compareMode, setCompareMode] = useState<CompareMode>("none");
  const [comparisons, setComparisons] = useState<Record<string, PositionComparison>>({});
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const comparison = activeField ? comparisons[activeField.key] : undefined;
  const activeFieldKey = activeField?.key;

  useEffect(() => {
    if (compareMode === "none" || !playerId || !activeFieldKey) return;
    if (comparisons[activeFieldKey]) return;
    let cancelled = false;
    // Microtask wrap: no sync setState inside the effect body (react-hooks purity).
    queueMicrotask(() => {
      if (!cancelled) setComparisonLoading(true);
    });
    api<PositionComparison>(
      `/players/${playerId}/widgets/${widget.id}/position-comparison?key=${encodeURIComponent(activeFieldKey)}`,
    )
      .then((res) => {
        if (!cancelled) setComparisons((m) => ({ ...m, [activeFieldKey]: res }));
      })
      .catch(() => {
        if (!cancelled)
          setComparisons((m) => ({
            ...m,
            [activeFieldKey]: { position: null, players: [], mean: [] },
          }));
      })
      .finally(() => {
        if (!cancelled) setComparisonLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [compareMode, playerId, activeFieldKey, comparisons, widget.id]);

  // Peer series indexed by calendar day, ready to join onto the player's rows.
  const peerData = useMemo(() => {
    const meanByDay = new Map((comparison?.mean ?? []).map((p) => [p.day, p]));
    const players = (comparison?.players ?? []).map((pl, i) => ({
      dataKey: `peer::${pl.player_id}`,
      name: pl.name,
      color: PEER_PALETTE[i % PEER_PALETTE.length],
      byDay: new Map(
        pl.points
          .filter((pt) => pt.value !== null && pt.value !== undefined)
          .map((pt) => [pt.recorded_at.slice(0, 10), pt.value as number]),
      ),
    }));
    return { meanByDay, players };
  }, [comparison]);

  // Comparison values join the player's own rows by day — the x-axis stays
  // anchored to the viewed player's samples, toggling never reshapes it.
  // Joined over the FULL dataset: the viewport (window.xDomain) pans over
  // these rows, so off-screen rows must be ready before they scroll in.
  const chartRows = useMemo(() => {
    if (compareMode === "none" || !comparison) return window.data;
    return window.data.map((row) => {
      const extra: Record<string, number | null> = {};
      if (compareMode === "mean") {
        const m = peerData.meanByDay.get(row.day);
        extra.peer_mean = m ? m.value : null;
        extra.peer_mean_n = m ? m.n : null;
      } else {
        for (const pl of peerData.players) {
          extra[pl.dataKey] = pl.byDay.get(row.day) ?? null;
        }
      }
      return { ...row, ...extra };
    });
  }, [window.data, compareMode, comparison, peerData]);

  const comparing = compareMode !== "none";
  const meanName = `Media ${comparison?.position ?? "posición"}`;

  // Fixed axis over the FULL history (plus whatever comparison series are
  // showing) — the frame stays put while the window slides.
  const yDomain = useMemo(() => {
    const vals: (number | null)[] = activeSeries.map((r) => r.value);
    if (compareMode === "mean") {
      for (const p of comparison?.mean ?? []) vals.push(p.value);
    } else if (compareMode === "players") {
      for (const pl of comparison?.players ?? [])
        for (const pt of pl.points) vals.push(pt.value);
    }
    return fullRangeDomain(vals);
  }, [activeSeries, compareMode, comparison]);

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

      <div className={styles.compareBar}>
        {playerId && (
          <div className={styles.segmented} role="group" aria-label="Comparar con la posición">
            {(
              [
                ["none", "Individual"],
                ["mean", "Media posición"],
                ["players", "Jugadores"],
              ] as [CompareMode, string][]
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                className={`${styles.segBtn} ${compareMode === mode ? styles.segBtnActive : ""}`}
                aria-pressed={compareMode === mode}
                onClick={() => setCompareMode(mode)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        <MovingAvgControl ma={ma} />
        {comparing && comparisonLoading && (
          <span className={styles.compareHint}>Cargando…</span>
        )}
        {comparing && !comparisonLoading && comparison && (
          <span className={styles.compareHint}>
            {comparison.players.length > 0
              ? `vs. ${comparison.position ?? "posición"} (${comparison.players.length} jugadores)`
              : "Sin datos de otros jugadores de la posición"}
          </span>
        )}
      </div>

      {activeSeries.length === 0 ? (
        <div className={styles.empty}>Sin datos para esta variable.</div>
      ) : (
        <>
        <ChartWindowNav window={window} label={windowRangeLabel(window.visible)} />
        <div className={styles.chartArea} style={{ height: widget.chart_height ?? 360 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartRows} margin={{ top: 8, right: refLines.length ? 70 : 16, left: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              {/* Numeric idx axis: the viewport (domain) pans smoothly over
                  the full dataset. Explicit height keeps the title INSIDE
                  the axis band, clear of the legend row. */}
              <XAxis
                dataKey="idx"
                type="number"
                domain={window.xDomain}
                ticks={window.ticks}
                tickFormatter={window.formatTick}
                allowDataOverflow
                tick={{ fontSize: 11, fill: "#6b7280" }}
                stroke="#d1d5db"
                height={46}
                label={{
                  value: xAxisTitle,
                  position: "insideBottom",
                  offset: 0,
                  style: { fill: "#6b7280", fontSize: 11, fontWeight: 600 },
                }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#6b7280" }}
                stroke="#d1d5db"
                width={72}
                domain={yDomain ?? ["auto", "auto"]}
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
                content={(p) => (
                  <ChartTooltip
                    {...p}
                    unit={activeField?.unit ?? ""}
                    matches={data.matches}
                    meanName={meanName}
                  />
                )}
                cursor={{ stroke: "#9ca3af", strokeDasharray: "3 3" }}
              />
              {(comparing || ma.enabled) && (
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} iconType="circle" iconSize={8} />
              )}
              {refLines.map((rl) => {
                const color = REF_LINE_COLORS[rl.kind] ?? "#64748b";
                const prefix = rl.short ?? REF_LINE_FALLBACK[rl.kind] ?? "";
                return (
                  <ReferenceLine
                    key={rl.kind}
                    y={rl.value}
                    stroke={color}
                    strokeDasharray="5 4"
                    strokeWidth={1.5}
                    ifOverflow="extendDomain"
                    label={{
                      value: `${prefix} ${fmtRef(rl.value)}`.trim(),
                      position: "right",
                      fill: color,
                      fontSize: 10,
                      fontWeight: 700,
                    }}
                  />
                );
              })}
              {compareMode === "mean" && (
                <Line
                  type="monotone"
                  dataKey="peer_mean"
                  name={meanName}
                  stroke={MEAN_COLOR}
                  strokeWidth={1.8}
                  strokeDasharray="6 4"
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              )}
              {compareMode === "players" &&
                peerData.players.map((pl) => (
                  <Line
                    key={pl.dataKey}
                    type="monotone"
                    dataKey={pl.dataKey}
                    name={pl.name}
                    stroke={pl.color}
                    strokeWidth={1.2}
                    strokeOpacity={0.85}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
              {ma.enabled && (
                <Line
                  type="monotone"
                  dataKey="mov_avg"
                  name={`Media móvil (últ. ${ma.windowSize})`}
                  stroke="#1d4ed8"
                  strokeWidth={1.6}
                  strokeDasharray="4 3"
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              )}
              <Line
                type="monotone"
                dataKey="value"
                name="Jugador"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ r: 3, fill: "#3b82f6" }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        </>
      )}
    </div>
  );
}

interface TooltipEntry {
  // Loosely typed on purpose: recharts' TooltipPayloadEntry allows accessor
  // functions, array values, etc. We narrow with `typeof` before use.
  dataKey?: unknown;
  name?: unknown;
  value?: unknown;
  color?: string;
  payload?: {
    value?: number;
    recorded_at?: string;
    day?: string;
    peer_mean_n?: number | null;
  };
}

interface TooltipProps {
  active?: boolean;
  // `readonly` so the type matches Recharts' TooltipPayload which marks
  // its payload as readonly. We only read from it.
  payload?: ReadonlyArray<TooltipEntry>;
  unit: string;
  matches?: Record<string, CrossExamMatchInfo>;
  meanName: string;
}

function ChartTooltip({ active, payload, unit, matches, meanName }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point || typeof point.value !== "number" || !point.recorded_at) return null;
  const match = point.day ? matches?.[point.day] : undefined;

  // Comparison entries (mean or peers) — everything except the main line.
  const others = payload.filter(
    (e) => e.dataKey !== "value" && typeof e.value === "number",
  );
  return (
    <div className={styles.chartTooltip}>
      <span className={styles.chartTooltipDate}>{formatLongDate(point.recorded_at)}</span>
      {match && (
        <span className={styles.chartTooltipValue}>
          {match.opponent
            ? `Partido vs ${match.opponent}${
                match.home === true ? " (local)" : match.home === false ? " (visita)" : ""
              }`
            : `Partido: ${match.title}`}
        </span>
      )}
      <span className={styles.chartTooltipValue}>
        {others.length > 0 ? "Jugador: " : ""}
        {point.value.toFixed(1)}
        {unit ? ` ${unit}` : ""}
      </span>
      {others.map((e) => {
        const isMean = e.dataKey === "peer_mean";
        const label = isMean
          ? `${meanName}${point.peer_mean_n ? ` (n=${point.peer_mean_n})` : ""}`
          : String(e.name ?? "");
        return (
          <span key={String(e.dataKey)} className={styles.chartTooltipPeer} style={{ color: e.color }}>
            {label}: {(e.value as number).toFixed(1)}
            {unit ? ` ${unit}` : ""}
          </span>
        );
      })}
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

/** Compact reference-line value: 9835.8 → "9.8k", 33.5 → "33.5". */
function fmtRef(v: number): string {
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
