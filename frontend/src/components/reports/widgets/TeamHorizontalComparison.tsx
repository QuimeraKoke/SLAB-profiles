"use client";

import React, { useMemo, useState } from "react";

import type {
  TeamHorizontalComparisonPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamHorizontalComparison.module.css";

interface Props {
  widget: TeamReportWidget;
}

// Most-recent → oldest, dark → light. Keeps the eye on the latest reading.
const SERIES_COLORS = ["#6d28d9", "#9061f9", "#b5a0ff", "#d4caff", "#e9e3ff"];

// In position mode each row owns a base color; older series fade toward
// transparent on top of that base. Returns an inline `background` value.
const POSITION_SERIES_ALPHAS = [1.0, 0.7, 0.45, 0.28, 0.16];
function positionBarColor(base: string, idx: number): string {
  const alpha = POSITION_SERIES_ALPHAS[idx] ?? 0.12;
  // base is a hex string like "#a855f7" — convert to rgba so we can fade.
  const hex = base.replace("#", "");
  const full = hex.length === 3
    ? hex.split("").map((c) => c + c).join("")
    : hex;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

type Row = TeamHorizontalComparisonPayload["rows"][number];
type GroupRow = Extract<Row, { group_id: string }>;
type PlayerRow = Extract<Row, { player_id: string }>;
const isGroupRow = (row: Row): row is GroupRow => "group_id" in row;

export default function TeamHorizontalComparison({ widget }: Props) {
  const data = widget.data as TeamHorizontalComparisonPayload;
  const isByPosition = data.grouping === "position";

  // Track the user's explicit pick. The "effective" key falls back to the
  // resolver's default whenever the picked key isn't in the current
  // `fields` (e.g. the layout was edited and the field was removed,
  // or the widget remounted with a fresh config). Computing the
  // effective key at render time avoids set-state-in-effect anti-patterns.
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const selectedKey = useMemo(() => {
    const fields = data.fields ?? [];
    if (pickedKey && fields.some((f) => f.key === pickedKey)) {
      return pickedKey;
    }
    return data.default_field_key || fields[0]?.key || "";
  }, [data.fields, data.default_field_key, pickedKey]);

  const selectedField = useMemo(
    () => (data.fields ?? []).find((f) => f.key === selectedKey) ?? null,
    [data.fields, selectedKey],
  );

  // Global max, scoped to the SELECTED field, so switching fields rescales
  // the bars to that field's data range (kg and cm don't share a scale).
  const max = useMemo(() => {
    if (!selectedKey) return 1;
    const all: number[] = [];
    for (const row of data.rows ?? []) {
      const list = row.values?.[selectedKey] ?? [];
      for (const v of list) all.push(v.value);
    }
    return all.length > 0 ? Math.max(...all) : 1;
  }, [data.rows, selectedKey]);

  if (data.empty || (data.rows ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header
          widget={widget}
          field={selectedField}
          fields={data.fields ?? []}
          selectedKey={selectedKey}
          onSelect={setPickedKey}
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

  const unitLabel = selectedField?.unit ? ` ${selectedField.unit}` : "";
  const seriesCount = data.limit_per_player || 1;

  return (
    <div
      className={styles.widget}
      style={
        widget.chart_height
          ? ({ "--chart-height": `${widget.chart_height}px` } as React.CSSProperties)
          : undefined
      }
    >
      <Header
        widget={widget}
        field={selectedField}
        fields={data.fields ?? []}
        selectedKey={selectedKey}
        onSelect={setPickedKey}
        isByPosition={isByPosition}
      />

      {isByPosition ? (
        <div className={styles.legend} aria-hidden="true">
          {(data.groups ?? []).map((g) => (
            <span key={g.id} className={styles.legendItem}>
              <span
                className={styles.legendSwatch}
                style={{ background: g.color }}
              />
              {g.name}
            </span>
          ))}
        </div>
      ) : (
        <div className={styles.legend} aria-hidden="true">
          {Array.from({ length: seriesCount }).map((_, i) => (
            <span key={i} className={styles.legendItem}>
              <span
                className={styles.legendSwatch}
                style={{ background: SERIES_COLORS[i] ?? "#cbd5e1" }}
              />
              {i === 0
                ? "Más reciente"
                : i === 1
                  ? "Anterior"
                  : `${i + 1}ª anterior`}
            </span>
          ))}
        </div>
      )}

      <div className={styles.body}>
        {data.rows.map((row) => {
          const values = row.values?.[selectedKey] ?? [];
          const isGroup = isGroupRow(row);
          const rowKey = isGroup ? row.group_id : (row as PlayerRow).player_id;
          const rowName = isGroup ? row.group_name : (row as PlayerRow).player_name;
          return (
            <div key={rowKey} className={styles.row}>
              <div className={styles.playerName} title={rowName}>
                {isGroup && (
                  <span
                    className={styles.positionDot}
                    style={{ background: row.color }}
                  />
                )}
                <span className={styles.playerNameText}>{rowName}</span>
              </div>
              <div className={styles.bars}>
                {values.length === 0 ? (
                  <div className={styles.noData}>—</div>
                ) : (
                  values.map((v, i) => {
                    const widthPct = Math.max(2, (v.value / max) * 100);
                    const bg = isGroup
                      ? positionBarColor(row.color, i)
                      : (SERIES_COLORS[i] ?? "#cbd5e1");
                    return (
                      <div key={i} className={styles.barRow}>
                        <div
                          className={styles.bar}
                          style={{
                            width: `${widthPct}%`,
                            background: bg,
                            color: isGroup && i >= 2 ? "#111827" : "#ffffff",
                          }}
                          title={`${v.label} · ${v.value}${unitLabel}`}
                        >
                          <span className={styles.barValue}>
                            {formatNumber(v.value)}
                            {unitLabel}
                          </span>
                        </div>
                        <span className={styles.barDate}>{v.label}</span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          );
        })}
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
  isByPosition: boolean;
}

function Header({ widget, field, fields, selectedKey, onSelect, isByPosition }: HeaderProps) {
  const showSelector = fields.length > 1;
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
        {isByPosition && (
          <span className={styles.meta}>
            Promedio mensual por posición · últimos meses con datos
          </span>
        )}
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
                {f.label}
                {f.unit ? ` (${f.unit})` : ""}
              </option>
            ))}
          </select>
        </label>
      ) : (
        field && (
          <span className={styles.fieldTag}>
            {field.label}
            {field.unit ? ` · ${field.unit}` : ""}
          </span>
        )
      )}
    </header>
  );
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}
