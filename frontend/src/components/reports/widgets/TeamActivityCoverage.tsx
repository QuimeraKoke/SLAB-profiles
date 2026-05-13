"use client";

import React, { useMemo, useState } from "react";

import type {
  TeamActivityCoveragePayload,
  TeamReportWidget,
} from "@/lib/types";

import styles from "./TeamActivityCoverage.module.css";

interface Props {
  widget: TeamReportWidget;
}

type SortDir = "asc" | "desc";
type SortState = { key: string; dir: SortDir };

/** Roster × templates matrix coloring each cell by how stale the player's
 *  last result on that template is. Green = on schedule, yellow = due
 *  soon, red = overdue, gray = never evaluated. Thresholds are configured
 *  server-side (see `team_aggregation::_resolve_team_activity_coverage`). */
export default function TeamActivityCoverage({ widget }: Props) {
  const data = widget.data as TeamActivityCoveragePayload;
  const [sort, setSort] = useState<SortState>({ key: "__player", dir: "asc" });

  const sortedRows = useMemo(() => {
    const rows = [...(data.rows ?? [])];
    if (sort.key === "__player") {
      rows.sort((a, b) => a.player_name.localeCompare(b.player_name));
    } else {
      rows.sort((a, b) => {
        const av = a.cells?.[sort.key]?.days_since;
        const bv = b.cells?.[sort.key]?.days_since;
        // Never-evaluated cells sort to the bottom regardless of direction
        // so "who's overdue?" stays visible on both asc and desc.
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        return av - bv;
      });
    }
    if (sort.dir === "desc") rows.reverse();
    return rows;
  }, [data.rows, sort]);

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

  const handleSortClick = (key: string) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  };

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <div className={styles.legend}>
        <span className={`${styles.legendDot} ${styles.statusOk}`} />
        <span>≤ {data.thresholds.green_max} días</span>
        <span className={`${styles.legendDot} ${styles.statusDue}`} />
        <span>{data.thresholds.green_max + 1}–{data.thresholds.yellow_max} días</span>
        <span className={`${styles.legendDot} ${styles.statusOverdue}`} />
        <span>&gt; {data.thresholds.yellow_max} días</span>
        <span className={`${styles.legendDot} ${styles.statusNever}`} />
        <span>Sin registro</span>
      </div>

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
                  sortKey={col.key}
                  currentSort={sort}
                  onClick={handleSortClick}
                  align="center"
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
                  if (!cell || cell.status === "never") {
                    return (
                      <td
                        key={col.key}
                        className={`${styles.cell} ${styles.statusNever}`}
                        title="Sin registro"
                      >
                        —
                      </td>
                    );
                  }
                  return (
                    <td
                      key={col.key}
                      className={`${styles.cell} ${statusClass(cell.status, styles)}`}
                      title={`Última toma: ${cell.last_iso ?? "—"} (${cell.days_since} d)`}
                    >
                      {cell.days_since} d
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

function statusClass(
  status: "ok" | "due" | "overdue" | "never",
  styles: Record<string, string>,
): string {
  switch (status) {
    case "ok": return styles.statusOk;
    case "due": return styles.statusDue;
    case "overdue": return styles.statusOverdue;
    default: return styles.statusNever;
  }
}

function Header({
  widget, data,
}: { widget: TeamReportWidget; data: TeamActivityCoveragePayload }) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
      <span className={styles.asOf}>al {data.as_of}</span>
    </header>
  );
}

interface SortableHeaderProps {
  label: string;
  sortKey: string;
  currentSort: SortState;
  onClick: (key: string) => void;
  align: "left" | "center";
}

function SortableHeader({
  label, sortKey, currentSort, onClick, align,
}: SortableHeaderProps) {
  const isActive = currentSort.key === sortKey;
  const arrow = isActive ? (currentSort.dir === "asc" ? "▲" : "▼") : "";
  return (
    <th
      className={`${styles.headerCell} ${align === "center" ? styles.alignCenter : ""}`}
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
        {arrow && <span className={styles.sortArrow}> {arrow}</span>}
      </span>
    </th>
  );
}
