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
    return buckets.map((b) => ({
      label: b.label,
      iso: b.iso,
      value: selectedKey ? b.values?.[selectedKey] : undefined,
    }));
  }, [data.buckets, selectedKey, isByPosition, groups]);

  const showSelector = (data.fields ?? []).length > 1;
  const unit = selectedField?.unit ? ` ${selectedField.unit}` : "";

  if (data.empty || (data.buckets ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header
          widget={widget}
          field={selectedField}
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
        field={selectedField}
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
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fill: "#6b7280", fontSize: 11 }} />
            <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const point = payload[0]?.payload as
                  | { label: string; value?: number; [k: string]: unknown }
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
                      <span className={styles.tooltipDate}>{point.label}</span>
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

                if (point.value === undefined || point.value === null) return null;
                return (
                  <div className={styles.tooltip}>
                    <span className={styles.tooltipDate}>{point.label}</span>
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
                  type="monotone"
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
            ) : (
              <Line
                type="monotone"
                dataKey="value"
                stroke={SINGLE_LINE_COLOR}
                strokeWidth={2}
                dot={{ r: 3, fill: SINGLE_LINE_COLOR, stroke: "#ffffff", strokeWidth: 1 }}
                activeDot={{ r: 5, fill: SINGLE_LINE_COLOR, stroke: "#ffffff", strokeWidth: 2 }}
                isAnimationActive={false}
                connectNulls
              />
            )}
          </LineChart>
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
  bucketSize: "week" | "month";
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
  const bucketLabel = bucketSize === "month" ? "mes" : "semana";
  const metaCopy = isByPosition
    ? `Promedio por posición · agrupado por ${bucketLabel}`
    : `Promedio del plantel · agrupado por ${bucketLabel}`;
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
