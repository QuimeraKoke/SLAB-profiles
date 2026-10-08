"use client";

import React, { useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  TeamPositionGroup,
  TeamReportWidget,
  TeamTrendLinePayload,
} from "@/lib/types";
import styles from "./TeamTrendLine.module.css";

interface Props {
  widget: TeamReportWidget;
}

const SINGLE_LINE_COLOR = "#6d28d9";
const MAX_LABELS = 24;
/** Several fields at once (`series: "all"`): the validated categorical slots,
 *  in fixed order (dataviz reference palette). */
const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];

/** "153.7 · +5.6 %": the value, and its change from the previous point. */
function PointLabel(props: {
  x?: number | string; y?: number | string; value?: unknown; index?: number;
  pcts: (number | null)[]; withPct: boolean;
  /** Indexes to label; null = every point. */
  only: Set<number> | null;
}) {
  const { x, y, value, index, pcts, withPct, only } = props;
  if (typeof value !== "number" || x === undefined || y === undefined) return null;
  if (only && (index === undefined || !only.has(index))) return null;
  const pct = withPct && index !== undefined ? pcts[index] : null;
  const v = Number.isInteger(value) ? String(value) : value.toFixed(value >= 100 ? 1 : 2);
  return (
    <text x={Number(x)} y={Number(y) - 9} textAnchor="middle" fontSize={10.5} fill="#344054">
      <tspan fontWeight={700}>{v}</tspan>
      {pct !== null && <tspan fill="#667085">{` ${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`}</tspan>}
    </text>
  );
}

export default function TeamTrendLine({ widget }: Props) {
  const data = widget.data as TeamTrendLinePayload;
  const isByPosition = data.grouping === "position";
  // Stabilize the array reference so downstream useMemo deps don't churn.
  const groups: TeamPositionGroup[] = useMemo(
    () => (isByPosition ? (data.groups ?? []) : []),
    [isByPosition, data.groups],
  );

  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const selectedKey = useMemo(() => {
    const fields = data.fields ?? [];
    if (pickedKey && fields.some((f) => f.key === pickedKey)) return pickedKey;
    return data.default_field_key || fields[0]?.key || "";
  }, [data.fields, data.default_field_key, pickedKey]);

  const selectedField = useMemo(
    () => (data.fields ?? []).find((f) => f.key === selectedKey) ?? null,
    [data.fields, selectedKey],
  );

  // Two shapes:
  //  - team-wide: { label, iso, value }            (single <Line dataKey="value">)
  //  - by position: { label, iso, [groupId]: mean } (one <Line> per group)
  // Recharts drops missing keys → gaps are honored by `connectNulls`.
  const chartData = useMemo(() => {
    const buckets = data.buckets ?? [];
    if (isByPosition) {
      return buckets.map((b) => {
        const entry: Record<string, string | number | undefined> = {
          label: b.label,
          iso: b.iso,
        };
        for (const g of groups) {
          entry[g.id] = b.values_by_group?.[g.id]?.[selectedKey];
        }
        return entry;
      });
    }
    return buckets.map((b) => {
      const entry: Record<string, string | number | undefined> = {
        label: b.label,
        iso: b.iso,
        detail: b.detail,
        value: selectedKey ? b.values?.[selectedKey] : undefined,
      };
      // "all" mode: every field on its own key, drawn side by side.
      for (const f of data.fields ?? []) entry[`f_${f.key}`] = b.values?.[f.key];
      return entry;
    });
  }, [data.buckets, data.fields, selectedKey, isByPosition, groups]);

  const display = data.display ?? { point_labels: "none", style: "line", series: "select" };
  const perMatch = data.bucket_size === "day";
  const labelByIso = useMemo(
    () => new Map((data.buckets ?? []).map((b) => [b.iso, b.label])),
    [data.buckets],
  );
  const highlight = perMatch && data.highlight_iso && labelByIso.has(data.highlight_iso)
    ? data.highlight_iso : null;
  // A season of matches is too many numbers to print: past MAX_LABELS points
  // only the chosen match and the latest carry one (the tooltip has the rest).
  const labelOnly = useMemo(() => {
    const n = data.buckets?.length ?? 0;
    if (n <= MAX_LABELS) return null;
    const keep = new Set<number>([n - 1]);
    const h = (data.buckets ?? []).findIndex((b) => b.iso === data.highlight_iso);
    if (h >= 0) keep.add(h);
    return keep;
  }, [data.buckets, data.highlight_iso]);
  const allSeries = display.series === "all" && !isByPosition && (data.fields ?? []).length > 1;
  // % change from the previous point WITH a value (a bucket with no test is
  // skipped, not compared against).
  const pcts = useMemo(() => {
    const out: (number | null)[] = [];
    let prev: number | null = null;
    for (const d of chartData) {
      const v = d.value;
      if (typeof v !== "number") {
        out.push(null);
        continue;
      }
      out.push(prev !== null && prev !== 0 ? ((v - prev) / Math.abs(prev)) * 100 : null);
      prev = v;
    }
    return out;
  }, [chartData]);

  const everyField = (data.fields ?? []).length > 1 && data.display?.series === "all" && !isByPosition;
  const showSelector = (data.fields ?? []).length > 1 && !everyField;
  // Evaluation charts (point labels) join a few test days: straight segments,
  // because a smoothed curve bulges past the labelled points.
  const curve = (data.display?.point_labels ?? "none") !== "none" ? "linear" : "monotone";
  const unit = selectedField?.unit ? ` ${selectedField.unit}` : "";

  if (data.empty || (data.buckets ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header
          widget={widget}
          field={everyField ? null : selectedField}
          fields={data.fields ?? []}
          selectedKey={selectedKey}
          onSelect={setPickedKey}
          showSelector={showSelector}
          bucketSize={data.bucket_size}
          isByPosition={isByPosition}
        />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  const height = widget.chart_height ?? 280;

  return (
    <div className={styles.widget}>
      <Header
        widget={widget}
        field={everyField ? null : selectedField}
        fields={data.fields ?? []}
        selectedKey={selectedKey}
        onSelect={setPickedKey}
        showSelector={showSelector}
        bucketSize={data.bucket_size}
        isByPosition={isByPosition}
      />
      {isByPosition && groups.length > 0 && (
        <div className={styles.legend} aria-hidden="true">
          {groups.map((g) => (
            <span key={g.id} className={styles.legendItem}>
              <span
                className={styles.legendSwatch}
                style={{ background: g.color }}
              />
              {g.name}
            </span>
          ))}
        </div>
      )}
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <ComposedChart data={chartData}
            margin={{ top: display.point_labels !== "none" ? 22 : 8, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            {/* Point labels need room past the first and last point; and a
                test like T10 (1.6–1.9 s) reads flat against a zero baseline,
                so labelled charts fit the axis to the data. */}
            {/* Day buckets key the axis by date: "26 sep" repeats across
                seasons, and two equal category labels collapse into one. */}
            <XAxis dataKey={perMatch ? "iso" : "label"} tick={{ fill: "#6b7280", fontSize: 11 }}
              tickFormatter={perMatch ? (iso: string) => labelByIso.get(iso) ?? iso : undefined}
              padding={display.point_labels !== "none" ? { left: 28, right: 40 } : undefined} />
            <YAxis tick={{ fill: "#6b7280", fontSize: 11 }}
              domain={display.point_labels !== "none" ? ["auto", "auto"] : undefined} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const point = payload[0]?.payload as
                  | { label: string; detail?: string; value?: number; [k: string]: unknown }
                  | undefined;
                if (!point) return null;

                if (isByPosition) {
                  const rows = groups
                    .map((g) => {
                      const v = point[g.id];
                      return typeof v === "number"
                        ? { group: g, value: v }
                        : null;
                    })
                    .filter((r): r is { group: TeamPositionGroup; value: number } => r !== null);
                  if (rows.length === 0) return null;
                  return (
                    <div className={styles.tooltip}>
                      <span className={styles.tooltipDate}>
                        {point.label}{point.detail ? ` · ${point.detail}` : ""}
                      </span>
                      {rows.map(({ group, value }) => (
                        <span key={group.id} className={styles.tooltipRow}>
                          <span
                            className={styles.tooltipSwatch}
                            style={{ background: group.color }}
                          />
                          <span className={styles.tooltipLabel}>{group.label}</span>
                          <span className={styles.tooltipValue}>
                            {value.toFixed(2)}
                            {unit}
                          </span>
                        </span>
                      ))}
                    </div>
                  );
                }

                if (allSeries) {
                  const rows = (data.fields ?? [])
                    .map((f, i) => ({ f, i, v: point[`f_${f.key}`] }))
                    .filter((r): r is { f: typeof r.f; i: number; v: number } => typeof r.v === "number");
                  if (rows.length === 0) return null;
                  return (
                    <div className={styles.tooltip}>
                      <span className={styles.tooltipDate}>
                        {point.label}{point.detail ? ` · ${point.detail}` : ""}
                      </span>
                      {rows.map(({ f, i, v }) => (
                        <span key={f.key} className={styles.tooltipRow}>
                          <span className={styles.tooltipSwatch}
                            style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                          <span className={styles.tooltipLabel}>{f.label}</span>
                          <span className={styles.tooltipValue}>
                            {v.toFixed(2)}{f.unit ? ` ${f.unit}` : ""}
                          </span>
                        </span>
                      ))}
                    </div>
                  );
                }

                if (point.value === undefined || point.value === null) return null;
                return (
                  <div className={styles.tooltip}>
                    <span className={styles.tooltipDate}>
                        {point.label}{point.detail ? ` · ${point.detail}` : ""}
                      </span>
                    <span className={styles.tooltipValue}>
                      {point.value.toFixed(2)}
                      {unit}
                    </span>
                  </div>
                );
              }}
            />
            {isByPosition ? (
              groups.map((g) => (
                <Line
                  key={g.id}
                  type={curve}
                  dataKey={g.id}
                  name={g.name}
                  stroke={g.color}
                  strokeWidth={2}
                  dot={{ r: 3, fill: g.color, stroke: "#ffffff", strokeWidth: 1 }}
                  activeDot={{ r: 5, fill: g.color, stroke: "#ffffff", strokeWidth: 2 }}
                  isAnimationActive={false}
                  connectNulls
                />
              ))
            ) : allSeries ? (
              (data.fields ?? []).map((f, i) => (
                <Line
                  key={f.key}
                  type={curve}
                  dataKey={`f_${f.key}`}
                  name={f.label}
                  stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3.5, fill: SERIES_COLORS[i % SERIES_COLORS.length], stroke: "#ffffff", strokeWidth: 1 }}
                  activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2 }}
                  isAnimationActive={false}
                  connectNulls
                />
              ))
            ) : (
              [
                display.style === "area" && (
                  <Area key="area" type={curve} dataKey="value" stroke="none"
                    fill={SINGLE_LINE_COLOR} fillOpacity={0.12} isAnimationActive={false}
                    connectNulls tooltipType="none" />
                ),
                <Line
                  key="line"
                  type={curve}
                  dataKey="value"
                  stroke={SINGLE_LINE_COLOR}
                  strokeWidth={2}
                  dot={{ r: 3, fill: SINGLE_LINE_COLOR, stroke: "#ffffff", strokeWidth: 1 }}
                  activeDot={{ r: 5, fill: SINGLE_LINE_COLOR, stroke: "#ffffff", strokeWidth: 2 }}
                  isAnimationActive={false}
                  connectNulls
                >
                  {display.point_labels !== "none" && (
                    <LabelList dataKey="value"
                      content={(p) => (
                        <PointLabel {...(p as object)} pcts={pcts} only={labelOnly}
                          withPct={display.point_labels === "value_pct"} />
                      )} />
                  )}
                </Line>,
              ]
            )}
            {highlight && (
              <ReferenceLine x={highlight} stroke="#1d2939" strokeDasharray="4 3"
                label={{ value: "Partido elegido", position: "insideTopRight", fill: "#344054", fontSize: 10 }} />
            )}
            {allSeries && (
              <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={8}
                formatter={(v) => <span style={{ color: "#4b5563" }}>{v}</span>} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface HeaderProps {
  widget: TeamReportWidget;
  field: { key: string; label: string; unit: string } | null;
  fields: { key: string; label: string; unit: string }[];
  selectedKey: string;
  onSelect: (key: string) => void;
  showSelector: boolean;
  bucketSize: "week" | "month" | "day";
  isByPosition: boolean;
}

function Header({
  widget,
  field,
  fields,
  selectedKey,
  onSelect,
  showSelector,
  bucketSize,
  isByPosition,
}: HeaderProps) {
  const bucketLabel = bucketSize === "month" ? "mes" : bucketSize === "day" ? "partido" : "semana";
  const metaCopy = isByPosition
    ? `Promedio por posición · por ${bucketLabel}`
    : `Promedio del plantel · por ${bucketLabel}`;
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
        <span className={styles.meta}>{metaCopy}</span>
      </div>
      {showSelector ? (
        <label className={styles.fieldSelectLabel}>
          <span className={styles.fieldSelectHint}>Indicador</span>
          <select
            className={styles.fieldSelect}
            value={selectedKey}
            onChange={(e) => onSelect(e.target.value)}
          >
            {fields.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}{f.unit ? ` (${f.unit})` : ""}
              </option>
            ))}
          </select>
        </label>
      ) : (
        field && (
          <span className={styles.fieldTag}>
            {field.label}{field.unit ? ` · ${field.unit}` : ""}
          </span>
        )
      )}
    </header>
  );
}
