"use client";

import React, { useMemo, useState } from "react";

import type {
  TeamReportWidget,
  TeamSeasonStatsPayload,
} from "@/lib/types";
import styles from "./TeamSeasonStats.module.css";

interface Props {
  widget: TeamReportWidget;
}

type Row = TeamSeasonStatsPayload["rows"][number];

type SortKey =
  | "player_name"
  | "citaciones"
  | "partidos_jugados"
  | "partidos_titular"
  | "minutos"
  | "pct_minutos_jugados"
  | "goles"
  | "amarillas"
  | "rojas";

type SortDir = "asc" | "desc";

/** Color buckets for the % Minutos Jugados column. Match the green→red
 * conditional formatting in the client's screenshot. Thresholds picked
 * to map roughly: ≥75% green, 50-75% lime, 35-50% amber, 20-35% orange,
 * <20% red. Empty value = neutral. */
function pctColor(pct: number): { bg: string; fg: string } {
  if (pct >= 75) return { bg: "#16a34a", fg: "#ffffff" };
  if (pct >= 60) return { bg: "#22c55e", fg: "#022c1a" };
  if (pct >= 45) return { bg: "#84cc16", fg: "#1a2e05" };
  if (pct >= 30) return { bg: "#eab308", fg: "#3a2e05" };
  if (pct >= 15) return { bg: "#f97316", fg: "#3a1605" };
  return { bg: "#dc2626", fg: "#ffffff" };
}

/**
 * Per-player season-stats table. One row per player, columns aggregated
 * over the matches resolved by the layout's multi-match selector (or
 * every in-window match when nothing is selected).
 *
 * Sortable headers — click once for desc, again for asc. Default sort
 * matches the backend `order_by` (typically minutes desc).
 */
export default function TeamSeasonStats({ widget }: Props) {
  const data = widget.data as TeamSeasonStatsPayload;

  const [sortKey, setSortKey] = useState<SortKey>("minutos");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  // Off by default — the table is cleaner without bench / never-cited
  // players. Tick the box to surface them as dim rows at the bottom.
  const [showUncited, setShowUncited] = useState(false);

  const visibleRows = useMemo(() => {
    const all = data.rows ?? [];
    return showUncited ? all : all.filter((r) => r.citaciones > 0);
  }, [data.rows, showUncited]);

  const sortedRows = useMemo(() => {
    const rows = [...visibleRows];
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc"
          ? av.localeCompare(bv)
          : bv.localeCompare(av);
      }
      const an = typeof av === "number" ? av : Number(av) || 0;
      const bn = typeof bv === "number" ? bv : Number(bv) || 0;
      return sortDir === "asc" ? an - bn : bn - an;
    });
    return rows;
  }, [visibleRows, sortKey, sortDir]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Names default ascending, numerics default descending.
      setSortDir(key === "player_name" ? "asc" : "desc");
    }
  };

  // Empty payload (no matches selected) vs filter-empty (matches selected
  // but every player has 0 citations and the checkbox is off) need
  // different copy.
  const totalRows = data.rows?.length ?? 0;
  const hiddenByFilter = !showUncited && totalRows > 0 && sortedRows.length === 0;
  if (data.empty || totalRows === 0) {
    return (
      <div className={styles.widget}>
        <Header
          widget={widget}
          matchesCount={data.matches_count}
          showUncited={showUncited}
          onToggleShowUncited={setShowUncited}
          totalRows={totalRows}
          visibleRows={sortedRows.length}
        />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin partidos seleccionados — elegí al menos uno para ver estadísticas."}
        </div>
      </div>
    );
  }
  if (hiddenByFilter) {
    return (
      <div className={styles.widget}>
        <Header
          widget={widget}
          matchesCount={data.matches_count}
          showUncited={showUncited}
          onToggleShowUncited={setShowUncited}
          totalRows={totalRows}
          visibleRows={sortedRows.length}
        />
        <div className={styles.empty}>
          Ningún jugador tiene citaciones en los partidos seleccionados.
          Activá &quot;Mostrar jugadores sin convocatoria&quot; para verlos.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <Header
        widget={widget}
        matchesCount={data.matches_count}
        showUncited={showUncited}
        onToggleShowUncited={setShowUncited}
        totalRows={totalRows}
        visibleRows={sortedRows.length}
      />

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <Th label="Jugador" k="player_name" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="left" sticky />
              <Th label="Partidos equipo" k="citaciones" sortKey={sortKey} sortDir={sortDir} onSort={onSort} disabled />
              <Th label="Citaciones" k="citaciones" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="Partidos Jugados" k="partidos_jugados" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="Partidos Titular" k="partidos_titular" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="Minutos" k="minutos" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="% Minutos Jugados" k="pct_minutos_jugados" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="Goles" k="goles" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="Amarillas" k="amarillas" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <Th label="Rojas" k="rojas" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => {
              const dim = row.citaciones === 0;
              return (
                <tr key={row.player_id} className={dim ? styles.rowDim : undefined}>
                  <td className={`${styles.cellName} ${styles.sticky}`} title={row.player_name}>
                    {row.player_name}
                  </td>
                  <td className={styles.num}>{row.partidos_equipo}</td>
                  <td className={styles.num}>{row.citaciones}</td>
                  <td className={styles.num}>{row.partidos_jugados}</td>
                  <td className={styles.num}>{row.partidos_titular}</td>
                  <td className={styles.num}>{row.minutos.toLocaleString()}</td>
                  <td className={styles.pctCell}>
                    <PctChip value={row.pct_minutos_jugados} />
                  </td>
                  <td className={styles.num}>{row.goles}</td>
                  <td className={styles.num}>{row.amarillas}</td>
                  <td className={styles.num}>{row.rojas}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Header({
  widget,
  matchesCount,
  showUncited,
  onToggleShowUncited,
  totalRows,
  visibleRows,
}: {
  widget: TeamReportWidget;
  matchesCount: number;
  showUncited: boolean;
  onToggleShowUncited: (next: boolean) => void;
  totalRows: number;
  visibleRows: number;
}) {
  const hiddenCount = totalRows - visibleRows;
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
      <div className={styles.headerControls}>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={showUncited}
            onChange={(e) => onToggleShowUncited(e.target.checked)}
          />
          <span>
            Mostrar jugadores sin convocatoria
            {!showUncited && hiddenCount > 0 && (
              <span className={styles.toggleHint}> ({hiddenCount})</span>
            )}
          </span>
        </label>
        <span className={styles.matchesTag}>
          {matchesCount} partido{matchesCount === 1 ? "" : "s"}
        </span>
      </div>
    </header>
  );
}

interface ThProps {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
  sticky?: boolean;
  /** Header is rendered but not clickable — used for "Partidos equipo"
   *  which is the same value on every row (no meaningful sort). */
  disabled?: boolean;
}

function Th({ label, k, sortKey, sortDir, onSort, align = "right", sticky, disabled }: ThProps) {
  const active = !disabled && k === sortKey;
  const classes = [
    align === "left" ? styles.thLeft : styles.thRight,
    sticky ? styles.sticky : "",
    disabled ? styles.thDisabled : styles.thClickable,
  ].filter(Boolean).join(" ");
  return (
    <th
      className={classes}
      onClick={disabled ? undefined : () => onSort(k)}
      aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
    >
      <span className={styles.thLabel}>{label}</span>
      {active && (
        <span className={styles.thArrow} aria-hidden="true">
          {sortDir === "asc" ? "▲" : "▼"}
        </span>
      )}
    </th>
  );
}

function PctChip({ value }: { value: number }) {
  const { bg, fg } = pctColor(value);
  return (
    <span
      className={styles.pctChip}
      style={{ background: bg, color: fg }}
    >
      {value.toFixed(2)} %
    </span>
  );
}
