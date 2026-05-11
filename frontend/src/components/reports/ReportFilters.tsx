"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

import DateRangeControl, {
  defaultDateRange,
  type DatePreset,
  type DateRange,
  type DateRangeValue,
} from "@/components/common/DateRangeControl";
import type { PlayerSummary, Position } from "@/lib/types";

import styles from "./ReportFilters.module.css";

// Re-export so callers that import via this module don't need to chase
// the constant through two files.
export { DATE_WINDOW_MAX_DAYS } from "@/components/common/DateRangeControl";

export interface ReportFiltersValue {
  positionId: string;
  playerIds: string[];
  preset: DatePreset;
  date: DateRange;
}

interface Props {
  positions: Position[];
  players: PlayerSummary[];
  value: ReportFiltersValue;
  onChange: (next: ReportFiltersValue) => void;
}

/** Filter bar for /reportes/[deptSlug]: position dropdown + player
 * multi-select + date-range picker. Stateless on its own — caller owns
 * the value and decides when to refetch. */
export default function ReportFilters({
  positions, players, value, onChange,
}: Props) {
  return (
    <div className={styles.bar}>
      {positions.length > 0 && (
        <label className={styles.field}>
          <span className={styles.label}>Posición</span>
          <select
            value={value.positionId}
            onChange={(e) => onChange({ ...value, positionId: e.target.value })}
          >
            <option value="">Todas</option>
            {positions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}{p.abbreviation ? ` (${p.abbreviation})` : ""}
              </option>
            ))}
          </select>
        </label>
      )}

      <PlayerMultiSelect
        players={players}
        selected={value.playerIds}
        onChange={(ids) => onChange({ ...value, playerIds: ids })}
      />

      <DateRangeControl
        variant="compact"
        value={{ preset: value.preset, date: value.date }}
        onChange={(next) => onChange({ ...value, preset: next.preset, date: next.date })}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------

interface PlayerMultiSelectProps {
  players: PlayerSummary[];
  selected: string[];
  onChange: (ids: string[]) => void;
}

function PlayerMultiSelect({ players, selected, onChange }: PlayerMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onPointer(e: PointerEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return players;
    return players.filter((p) =>
      `${p.first_name} ${p.last_name}`.toLowerCase().includes(q),
    );
  }, [players, search]);

  const buttonText = selected.length === 0
    ? "Todo el plantel"
    : selected.length === 1
      ? playerName(players, selected[0]) ?? `1 jugador`
      : `${selected.length} jugadores`;

  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((x) => x !== id));
    } else {
      onChange([...selected, id]);
    }
  }

  return (
    <div className={`${styles.field} ${styles.playerField}`} ref={wrapperRef}>
      <span className={styles.label}>Jugadores</span>
      <button
        type="button"
        className={styles.playerButton}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={styles.playerButtonText}>{buttonText}</span>
        <span className={styles.playerButtonCaret}>▾</span>
      </button>
      {open && (
        <div className={styles.playerDropdown}>
          <input
            className={styles.playerSearchInput}
            type="text"
            placeholder="Buscar jugador…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
          <div className={styles.playerActions}>
            <button
              type="button"
              className={styles.playerActionButton}
              onClick={() => onChange(players.map((p) => p.id))}
            >
              Seleccionar todos
            </button>
            <button
              type="button"
              className={styles.playerActionButton}
              onClick={() => onChange([])}
            >
              Limpiar
            </button>
          </div>
          <div className={styles.playerList}>
            {filtered.length === 0 ? (
              <div className={styles.playerEmpty}>Sin coincidencias</div>
            ) : (
              filtered.map((p) => (
                <label key={p.id} className={styles.playerOption}>
                  <input
                    type="checkbox"
                    checked={selected.includes(p.id)}
                    onChange={() => toggle(p.id)}
                  />
                  <span>{p.first_name} {p.last_name}</span>
                </label>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function playerName(players: PlayerSummary[], id: string): string | null {
  const p = players.find((x) => x.id === id);
  return p ? `${p.first_name} ${p.last_name}` : null;
}

/** Default value matching "Últimos 30 días". Exported so the page can
 * initialize state without duplicating the date math. */
export function defaultFilters(): ReportFiltersValue {
  const base = defaultDateRange();
  return {
    positionId: "",
    playerIds: [],
    preset: base.preset,
    date: base.date,
  };
}
// Re-export the underlying types so callers needing finer-grained imports
// (e.g. picking just the preset literal type) don't pierce the
// DateRangeControl module path.
export type { DatePreset, DateRange, DateRangeValue };
