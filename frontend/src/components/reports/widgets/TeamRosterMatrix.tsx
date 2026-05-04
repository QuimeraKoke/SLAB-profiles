"use client";

import React, { useMemo, useState } from "react";

import type {
  TeamReportWidget,
  TeamRosterMatrixPayload,
} from "@/lib/types";
import styles from "./TeamRosterMatrix.module.css";

interface Props {
  widget: TeamReportWidget;
}

type SortDir = "asc" | "desc";
type SortState = { key: string; dir: SortDir };

export default function TeamRosterMatrix({ widget }: Props) {
  const data = widget.data as TeamRosterMatrixPayload;

  // Default sort: player name asc. Click any header to sort by that column.
  // Repeated clicks toggle direction; clicking a different column resets to asc.
  const [sort, setSort] = useState<SortState>({ key: "__player", dir: "asc" });

  const sortedRows = useMemo(() => {
    const rows = [...(data.rows ?? [])];
    if (sort.key === "__player") {
      rows.sort((a, b) => a.player_name.localeCompare(b.player_name));
    } else {
      rows.sort((a, b) => {
        const av = a.cells?.[sort.key]?.value;
        const bv = b.cells?.[sort.key]?.value;
        // Missing cells sort to the bottom regardless of direction so the
        // table stays scannable ("who's missing this measurement?" still
        // visible even on a desc sort).
        if (av === undefined && bv === undefined) return 0;
        if (av === undefined) return 1;
        if (bv === undefined) return -1;
        return av - bv;
      });
    }
    if (sort.dir === "desc") rows.reverse();
    return rows;
  }, [data.rows, sort]);

  const handleSortClick = (key: string) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  };

  if (data.empty || (data.rows ?? []).length === 0) {
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

  const showColors = data.coloring === "vs_team_range";

  return (
    <div className={styles.widget}>
      <Header widget={widget} />

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <SortableHeader
                label="Jugador"
                sortKey="__player"
                currentSort={sort}
                onClick={handleSortClick}
                align="left"
              />
              {data.columns.map((col) => (
                <SortableHeader
                  key={col.key}
                  label={col.label}
                  unit={col.unit}
                  sortKey={col.key}
                  currentSort={sort}
                  onClick={handleSortClick}
                  align="right"
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr key={row.player_id}>
                <td className={styles.playerCell} title={row.player_name}>
                  {row.player_name}
                </td>
                {data.columns.map((col) => {
                  const cell = row.cells?.[col.key];
                  if (cell === undefined) {
                    return (
                      <td
                        key={col.key}
                        className={`${styles.cell} ${styles.missingCell}`}
                      >
                        —
                      </td>
                    );
                  }
                  const range = data.ranges?.[col.key];
                  const bg = showColors && range ? cellColor(cell.value, range) : null;
                  const delta = computeDelta(cell, data.variation);
                  return (
                    <td
                      key={col.key}
                      className={styles.cell}
                      style={bg ? { background: bg } : undefined}
                      title={
                        cell.previous_value !== undefined && cell.previous_iso
                          ? `Medido el ${formatDate(cell.iso)} · anterior: ${formatNumber(
                              cell.previous_value,
                            )} (${formatDate(cell.previous_iso)})`
                          : `Medido el ${formatDate(cell.iso)}`
                      }
                    >
                      <span className={styles.cellValue}>
                        {formatNumber(cell.value)}
                      </span>
                      {delta && (
                        <span
                          className={`${styles.delta} ${
                            delta.dir === "up"
                              ? styles.deltaUp
                              : delta.dir === "down"
                                ? styles.deltaDown
                                : styles.deltaFlat
                          }`}
                        >
                          {delta.arrow} {delta.text}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
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

interface SortableHeaderProps {
  label: string;
  unit?: string;
  sortKey: string;
  currentSort: SortState;
  onClick: (key: string) => void;
  align: "left" | "right";
}

function SortableHeader({
  label,
  unit,
  sortKey,
  currentSort,
  onClick,
  align,
}: SortableHeaderProps) {
  const isActive = currentSort.key === sortKey;
  const arrow = isActive ? (currentSort.dir === "asc" ? "▲" : "▼") : "";
  return (
    <th
      className={`${styles.headerCell} ${align === "right" ? styles.alignRight : ""}`}
      onClick={() => onClick(sortKey)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick(sortKey);
        }
      }}
    >
      <span>
        {label}
        {unit && <span className={styles.unit}> ({unit})</span>}
        {arrow && <span className={styles.sortArrow}> {arrow}</span>}
      </span>
    </th>
  );
}

// Light → strong purple gradient based on where `value` falls within the
// team's [min, max]. Identical min/max → flat color. Used only when the
// admin enabled `vs_team_range` coloring.
function cellColor(value: number, range: { min: number; max: number }): string {
  const span = range.max - range.min;
  const t = span > 0 ? (value - range.min) / span : 0.5;
  const clamped = Math.max(0, Math.min(1, t));
  // Linear interp: very light purple → mid purple. Stops short of dark
  // purple so black text on top stays readable.
  const r = Math.round(245 - clamped * 90);
  const g = Math.round(243 - clamped * 100);
  const b = Math.round(255 - clamped * 50);
  return `rgb(${r}, ${g}, ${b})`;
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

interface DeltaResult {
  arrow: string;
  text: string;
  dir: "up" | "down" | "flat";
}

/**
 * Returns a render-ready delta payload, or null when the variation should
 * be hidden (mode=off, no prior reading, or division-by-zero on percent).
 */
function computeDelta(
  cell: { value: number; previous_value?: number },
  mode: "off" | "absolute" | "percent",
): DeltaResult | null {
  if (mode === "off") return null;
  if (cell.previous_value === undefined) return null;
  const diff = cell.value - cell.previous_value;
  const dir = diff > 0 ? "up" : diff < 0 ? "down" : "flat";
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "•";

  if (mode === "percent") {
    if (cell.previous_value === 0) return null;
    const pct = (diff / cell.previous_value) * 100;
    const sign = pct > 0 ? "+" : "";
    return { arrow, dir, text: `${sign}${pct.toFixed(1)}%` };
  }

  // absolute
  const sign = diff > 0 ? "+" : "";
  return { arrow, dir, text: `${sign}${formatNumber(diff)}` };
}
