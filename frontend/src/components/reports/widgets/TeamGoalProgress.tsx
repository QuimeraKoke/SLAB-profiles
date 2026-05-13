"use client";

import React, { useMemo, useState } from "react";

import type {
  GoalOperator,
  TeamGoalProgressPayload,
  TeamReportWidget,
} from "@/lib/types";

import styles from "./TeamGoalProgress.module.css";

interface Props {
  widget: TeamReportWidget;
}

type SortDir = "asc" | "desc";
type SortState = { key: string; dir: SortDir };

const OPERATOR_LABELS: Record<GoalOperator, string> = {
  "<=": "≤", "<": "<", "==": "=", ">=": "≥", ">": ">",
};

/** Roster × goals matrix. Each row = player, each column = a unique
 *  (template, field, operator, target) combo. Cells show current value
 *  plus a status badge (achieved / in progress / missed / no data). */
export default function TeamGoalProgress({ widget }: Props) {
  const data = widget.data as TeamGoalProgressPayload;
  const [sort, setSort] = useState<SortState>({ key: "__player", dir: "asc" });

  const sortedRows = useMemo(() => {
    const rows = [...(data.rows ?? [])];
    if (sort.key === "__player") {
      rows.sort((a, b) => a.player_name.localeCompare(b.player_name));
    } else {
      // Sort by status priority within the chosen column: achieved > in_progress > missed > no_data > absent.
      const statusOrder: Record<string, number> = {
        achieved: 0, in_progress: 1, missed: 2, no_data: 3,
      };
      rows.sort((a, b) => {
        const aStatus = a.cells?.[sort.key]?.status;
        const bStatus = b.cells?.[sort.key]?.status;
        const aRank = aStatus === undefined ? 99 : statusOrder[aStatus];
        const bRank = bStatus === undefined ? 99 : statusOrder[bStatus];
        return aRank - bRank;
      });
    }
    if (sort.dir === "desc") rows.reverse();
    return rows;
  }, [data.rows, sort]);

  if (data.empty || data.columns.length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} data={data} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "No hay objetivos activos en este alcance."}
        </div>
      </div>
    );
  }

  const handleSortClick = (key: string) =>
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );

  return (
    <div className={styles.widget}>
      <Header widget={widget} data={data} />

      <SummaryBar summary={data.summary} />

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
                  label={col.field_label}
                  sublabel={`${OPERATOR_LABELS[col.operator]} ${col.target_value}${col.field_unit ? " " + col.field_unit : ""}`}
                  templateName={col.template_name}
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
                  if (!cell) {
                    return (
                      <td
                        key={col.key}
                        className={`${styles.cell} ${styles.statusAbsent}`}
                        title="Este jugador no tiene este objetivo"
                      >
                        —
                      </td>
                    );
                  }
                  const distance = cell.progress?.distance;
                  const distanceText =
                    distance != null
                      ? distance > 0
                        ? `+${formatNumber(distance)}`
                        : formatNumber(distance)
                      : "—";
                  return (
                    <td
                      key={col.key}
                      className={`${styles.cell} ${statusClass(cell.status, styles)}`}
                      title={tooltipFor(cell, col)}
                    >
                      <div className={styles.cellValue}>
                        {cell.current_value !== null
                          ? formatNumber(cell.current_value)
                          : "—"}
                      </div>
                      <div className={styles.cellDelta}>{distanceText}</div>
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
  status: "achieved" | "in_progress" | "missed" | "no_data",
  styles: Record<string, string>,
): string {
  switch (status) {
    case "achieved": return styles.statusAchieved;
    case "in_progress": return styles.statusInProgress;
    case "missed": return styles.statusMissed;
    default: return styles.statusNoData;
  }
}

function tooltipFor(
  cell: TeamGoalProgressPayload["rows"][number]["cells"][string],
  col: TeamGoalProgressPayload["columns"][number],
): string {
  const targetTxt = `${OPERATOR_LABELS[col.operator]} ${col.target_value}${col.field_unit ? " " + col.field_unit : ""}`;
  const valTxt =
    cell.current_value !== null
      ? `${cell.current_value}${col.field_unit ? " " + col.field_unit : ""}`
      : "sin medición";
  const dueTxt =
    cell.days_to_due >= 0
      ? `vence en ${cell.days_to_due} días`
      : `vencido hace ${Math.abs(cell.days_to_due)} días`;
  return `Objetivo: ${targetTxt} · Actual: ${valTxt} · ${dueTxt}`;
}

function SummaryBar({
  summary,
}: { summary: TeamGoalProgressPayload["summary"] }) {
  if (summary.total === 0) return null;
  return (
    <div className={styles.summary}>
      <SummaryItem label="Cumplidos" value={summary.achieved} cls={styles.statusAchieved} />
      <SummaryItem label="En curso" value={summary.in_progress} cls={styles.statusInProgress} />
      <SummaryItem label="Vencidos" value={summary.missed} cls={styles.statusMissed} />
      <SummaryItem label="Sin medición" value={summary.no_data} cls={styles.statusNoData} />
      <span className={styles.summaryTotal}>Total: {summary.total}</span>
    </div>
  );
}

function SummaryItem({
  label, value, cls,
}: { label: string; value: number; cls: string }) {
  return (
    <span className={`${styles.summaryItem} ${cls}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </span>
  );
}

function Header({
  widget,
}: { widget: TeamReportWidget; data: TeamGoalProgressPayload }) {
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
  sublabel?: string;
  templateName?: string;
  sortKey: string;
  currentSort: SortState;
  onClick: (key: string) => void;
  align: "left" | "center";
}

function SortableHeader({
  label, sublabel, templateName, sortKey, currentSort, onClick, align,
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
      title={templateName}
    >
      <span className={styles.headerLabel}>
        {label}
        {arrow && <span className={styles.sortArrow}> {arrow}</span>}
      </span>
      {sublabel && <span className={styles.headerSublabel}>{sublabel}</span>}
    </th>
  );
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2).replace(/\.?0+$/, "");
}
