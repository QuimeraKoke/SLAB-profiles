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
  TeamReportWidget,
  TeamTrendLinePayload,
} from "@/lib/types";
import styles from "./TeamTrendLine.module.css";

interface Props {
  widget: TeamReportWidget;
}

export default function TeamTrendLine({ widget }: Props) {
  const data = widget.data as TeamTrendLinePayload;

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

  // Recharts wants an array of objects keyed by the dataKey we pass to <Line>.
  // We map each bucket's selected-field value into `value`. Buckets with no
  // reading for the selected field omit `value` and Recharts drops the point.
  const chartData = useMemo(
    () =>
      (data.buckets ?? []).map((b) => ({
        label: b.label,
        iso: b.iso,
        value: selectedKey ? b.values?.[selectedKey] : undefined,
      })),
    [data.buckets, selectedKey],
  );

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
      />
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fill: "#6b7280", fontSize: 11 }} />
            <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const point = payload[0]?.payload as { label: string; value?: number };
                if (point?.value === undefined || point.value === null) return null;
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
            <Line
              type="monotone"
              dataKey="value"
              stroke="#6d28d9"
              strokeWidth={2}
              dot={{ r: 3, fill: "#6d28d9", stroke: "#ffffff", strokeWidth: 1 }}
              activeDot={{ r: 5, fill: "#6d28d9", stroke: "#ffffff", strokeWidth: 2 }}
              isAnimationActive={false}
              connectNulls
            />
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
}

function Header({
  widget,
  field,
  fields,
  selectedKey,
  onSelect,
  showSelector,
  bucketSize,
}: HeaderProps) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
        <span className={styles.meta}>
          Promedio del plantel · agrupado por {bucketSize === "month" ? "mes" : "semana"}
        </span>
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
