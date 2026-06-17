"use client";

import React, { useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type {
  TeamLeaderboardPayload,
  TeamReportWidget,
} from "@/lib/types";

import ShowNoDataToggle from "./ShowNoDataToggle";
import styles from "./TeamLeaderboard.module.css";

interface HoverTip {
  name: string;
  value: string;
  date: string | null;
  x: number;
  y: number;
}

interface Props {
  widget: TeamReportWidget;
}

type Aggregator = TeamLeaderboardPayload["aggregator"];

const AGGREGATOR_LABELS: Record<Aggregator, string> = {
  sum: "Total",
  avg: "Promedio",
  max: "Máximo",
  min: "Mínimo",
  latest: "Última toma",
};

const SELECTOR_ORDER: Aggregator[] = ["latest", "avg", "max", "min", "sum"];

// Field-by-field palette for multi_field mode. Same order as
// TeamHorizontalComparison so the two read consistently when stacked
// on the same page.
const FIELD_COLORS = [
  "#dc2626",
  "#0ea5e9",
  "#16a34a",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
];

type LeaderboardRow = TeamLeaderboardPayload["rows"][number];
type SingleRow = Extract<LeaderboardRow, { value: number }>;
type MultiRow = Extract<LeaderboardRow, { values: Record<string, number | null> }>;
const isMultiRow = (row: LeaderboardRow): row is MultiRow => "values" in row;

/** A player "has data" in single-field mode when they recorded at least
 *  one reading in the window. Zero-sample players (rendered as "—" /
 *  "Sin datos") are the "sin datos" rows hidden by default. */
const singleRowHasData = (row: SingleRow): boolean => (row.samples ?? 0) > 0;

/** Top-N podium ranking (mode="single") or grouped bars per field
 *  (mode="multi_field"). The mode flips both the row shape and the
 *  rendering — see the discriminated row type above. */
export default function TeamLeaderboard({ widget }: Props) {
  const data = widget.data as TeamLeaderboardPayload;
  const isMultiField = data.mode === "multi_field";

  // Per-chart aggregator override. Defaults to whatever the layout
  // configured (`data.aggregator`). Multi-field rows don't carry
  // per-aggregate breakdowns, so the selector is single-mode only.
  const [pickedAgg, setPickedAgg] = useState<Aggregator | null>(null);
  const effectiveAgg: Aggregator = pickedAgg ?? data.aggregator;
  // Hide zero-sample players from single-field views. Off by default so
  // the podium / bars stay focused on players with readings. Multi-field
  // mode shows "—" per field and isn't filtered.
  const [showNoData, setShowNoData] = useState(false);

  // When the user picks a different aggregator, derive a new view of
  // `data` with rebuilt rows, ranking, and team-avg reference line.
  // Empty `aggregates` (older payload) falls back to `value` so the
  // chart stays usable even if the backend hasn't been redeployed.
  const effectiveData = useMemo<TeamLeaderboardPayload>(() => {
    if (isMultiField || effectiveAgg === data.aggregator) return data;

    type SingleRow = Extract<LeaderboardRow, { value: number }>;
    const isSingle = (r: LeaderboardRow): r is SingleRow => "value" in r;

    const rebuiltSingles = (data.rows ?? []).filter(isSingle).map((row) => {
      const next = row.aggregates?.[effectiveAgg];
      return {
        ...row,
        value: typeof next === "number" ? next : 0,
        // Mark zero-sample rows so renderers can still show "—" if needed.
        _hasAgg: typeof next === "number",
      } as SingleRow & { _hasAgg: boolean };
    });
    rebuiltSingles.sort((a, b) =>
      data.order === "asc" ? a.value - b.value : b.value - a.value,
    );
    const rebuilt = rebuiltSingles.map((row, i) => ({ ...row, rank: i + 1 }));

    // Replace any auto-injected "Promedio equipo" reference line with one
    // that matches the visible aggregator. Manually-configured lines
    // (limits, targets) pass through untouched.
    const refLines = (data.reference_lines ?? []).filter(
      (rl) => rl.label !== "Promedio equipo",
    );
    const numericValues = rebuilt
      .filter((r) => (r as unknown as { _hasAgg: boolean })._hasAgg)
      .map((r) => r.value);
    if (numericValues.length > 0) {
      const teamAvg =
        numericValues.reduce((acc, v) => acc + v, 0) / numericValues.length;
      // Heuristic: only add the team-avg line back if it was present
      // in the original payload (so we don't silently introduce one).
      const hadAvgLine = (data.reference_lines ?? []).some(
        (rl) => rl.label === "Promedio equipo",
      );
      if (hadAvgLine) {
        refLines.push({
          value: Math.round(teamAvg * 10000) / 10000,
          label: "Promedio equipo",
          color: "#6b7280",
        });
      }
    }

    return {
      ...data,
      aggregator: effectiveAgg,
      rows: rebuilt,
      reference_lines: refLines,
    };
  }, [data, effectiveAgg, isMultiField]);

  if (data.empty || (data.rows ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header
          widget={widget}
          data={data}
          pickedAgg={pickedAgg}
          onPickAgg={setPickedAgg}
          showAggSelector={!isMultiField && hasAggregateBreakdown(data)}
          showToggle={false}
        />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  if (isMultiField) {
    return (
      <MultiFieldView
        widget={widget}
        data={data}
        pickedAgg={pickedAgg}
        onPickAgg={setPickedAgg}
      />
    );
  }

  if (data.style === "vertical_bars") {
    return (
      <VerticalBarsView
        widget={widget}
        data={effectiveData}
        pickedAgg={pickedAgg}
        onPickAgg={setPickedAgg}
        showAggSelector={hasAggregateBreakdown(data)}
        showNoData={showNoData}
        onToggleShowNoData={setShowNoData}
      />
    );
  }

  const unit = effectiveData.field?.unit ? ` ${effectiveData.field.unit}` : "";

  const singleRows = effectiveData.rows.filter(
    (r): r is SingleRow => !isMultiRow(r),
  );
  const visibleSingles = showNoData
    ? singleRows
    : singleRows.filter(singleRowHasData);
  const hiddenCount = singleRows.length - visibleSingles.length;
  const hiddenByFilter =
    !showNoData && singleRows.length > 0 && visibleSingles.length === 0;

  return (
    <div className={styles.widget}>
      <Header
        widget={widget}
        data={effectiveData}
        pickedAgg={pickedAgg}
        onPickAgg={setPickedAgg}
        showAggSelector={hasAggregateBreakdown(data)}
        showToggle
        showNoData={showNoData}
        onToggleShowNoData={setShowNoData}
        hiddenCount={hiddenCount}
      />

      {hiddenByFilter ? (
        <div className={styles.empty}>
          Ningún jugador tiene datos en este período. Activá &quot;Mostrar
          jugadores sin datos&quot; para ver el plantel completo.
        </div>
      ) : (
        <ol className={styles.list}>
          {visibleSingles.map((row) => (
            <li
              key={row.player_id}
              className={`${styles.row} ${podiumClass(row.rank, styles)}`}
            >
              <span className={styles.rank}>#{row.rank}</span>
              <span className={styles.name} title={row.player_name}>
                {row.player_name}
              </span>
              <span className={styles.value}>
                {formatNumber(row.value)}{unit}
              </span>
              <span className={styles.samples}>
                {row.samples} {row.samples === 1 ? "toma" : "tomas"}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** True when at least one row carries an `aggregates` breakdown. Without
 *  it the selector would be a dead control — backend not redeployed. */
function hasAggregateBreakdown(data: TeamLeaderboardPayload): boolean {
  for (const row of data.rows ?? []) {
    if ("aggregates" in row && row.aggregates && Object.keys(row.aggregates).length > 0) {
      return true;
    }
  }
  return false;
}

function VerticalBarsView({
  widget, data, pickedAgg, onPickAgg, showAggSelector,
  showNoData, onToggleShowNoData,
}: {
  widget: TeamReportWidget;
  data: TeamLeaderboardPayload;
  pickedAgg: Aggregator | null;
  onPickAgg: (next: Aggregator | null) => void;
  showAggSelector: boolean;
  showNoData: boolean;
  onToggleShowNoData: (next: boolean) => void;
}) {
  const unit = data.field?.unit ? ` ${data.field.unit}` : "";
  const decimals = typeof data.decimals === "number" ? data.decimals : null;
  // Floating tooltip state — rendered into document.body via a portal so
  // it escapes the chart's overflow clip + follows the cursor.
  const [hover, setHover] = useState<HoverTip | null>(null);

  // Prefer the new array form; fall back to the legacy single line.
  const refLines = React.useMemo(() => {
    if (data.reference_lines && data.reference_lines.length > 0) {
      return data.reference_lines;
    }
    return data.reference_line ? [data.reference_line] : [];
  }, [data.reference_lines, data.reference_line]);

  const refBands = React.useMemo(
    () => data.reference_bands ?? [],
    [data.reference_bands],
  );

  // Y-axis scale. If the resolver provided explicit y_min/y_max, use
  // those (zoom mode — for densities near 1.0, pH, etc.). Otherwise
  // default to [0, dataMax] including every overlay value so nothing
  // gets clipped above the chart.
  const { yMin, yMax } = React.useMemo(() => {
    const explicitMin = typeof data.y_min === "number" ? data.y_min : null;
    const explicitMax = typeof data.y_max === "number" ? data.y_max : null;

    let dataMax = 0;
    for (const row of data.rows) {
      if (!isMultiRow(row) && row.value > dataMax) dataMax = row.value;
    }
    for (const rl of refLines) {
      if (rl.value > dataMax) dataMax = rl.value;
    }
    for (const rb of refBands) {
      if (rb.max !== null && rb.max > dataMax) dataMax = rb.max;
      if (rb.min !== null && rb.min > dataMax) dataMax = rb.min;
    }
    const min = explicitMin ?? 0;
    const max = explicitMax ?? (dataMax > 0 ? dataMax : 1);
    return { yMin: min, yMax: max > min ? max : min + 1 };
  }, [data.y_min, data.y_max, data.rows, refLines, refBands]);

  // % position of a Y-axis value within [yMin, yMax]. Bottom = yMin, top = yMax.
  const yPercent = React.useCallback(
    (v: number) => {
      const clamped = Math.max(yMin, Math.min(yMax, v));
      return ((clamped - yMin) / (yMax - yMin)) * 100;
    },
    [yMin, yMax],
  );

  const singleRows = data.rows.filter((r): r is SingleRow => !isMultiRow(r));
  const visibleSingles = showNoData
    ? singleRows
    : singleRows.filter(singleRowHasData);
  const hiddenCount = singleRows.length - visibleSingles.length;
  const hiddenByFilter =
    !showNoData && singleRows.length > 0 && visibleSingles.length === 0;

  return (
    <div className={styles.widget}>
      <Header
        widget={widget}
        data={data}
        pickedAgg={pickedAgg}
        onPickAgg={onPickAgg}
        showAggSelector={showAggSelector}
        showToggle
        showNoData={showNoData}
        onToggleShowNoData={onToggleShowNoData}
        hiddenCount={hiddenCount}
      />
      {hiddenByFilter ? (
        <div className={styles.empty}>
          Ningún jugador tiene datos en este período. Activá &quot;Mostrar
          jugadores sin datos&quot; para ver el plantel completo.
        </div>
      ) : (
      <div className={styles.vBarsChart}>
        <div className={styles.vBarsArea}>
          {refBands.map((band, i) => {
            // Clamp band edges into the zoomed [yMin, yMax] viewport so
            // a band that extends beyond the chart still renders to the
            // edge instead of being skipped.
            const topPct = band.max !== null ? 100 - yPercent(band.max) : 0;
            const bottomPct = band.min !== null ? yPercent(band.min) : 0;
            const heightPct = Math.max(0, 100 - topPct - bottomPct);
            if (heightPct <= 0) return null;
            return (
              <div
                key={`band-${i}`}
                className={styles.refBand}
                style={{
                  top: `${topPct}%`,
                  height: `${heightPct}%`,
                  background: band.color,
                }}
              >
                {band.label && (
                  <span className={styles.refBandLabel}>{band.label}</span>
                )}
              </div>
            );
          })}
          {refLines.map((line, i) => {
            const top = 100 - yPercent(line.value);
            return (
              <div
                key={`line-${i}`}
                className={styles.refLine}
                style={{ top: `${top}%`, borderColor: line.color }}
              >
                <span
                  className={styles.refLabel}
                  style={{ color: line.color }}
                >
                  {line.label
                    ? `${line.label}: ${formatNumber(line.value, decimals)}${unit}`
                    : `${formatNumber(line.value, decimals)}${unit}`}
                </span>
              </div>
            );
          })}
          {visibleSingles.map((row) => {
            // Bar starts at yMin (the chart's baseline when zoomed). When
            // a value falls BELOW yMin the bar becomes 0 — clamp via the
            // helper. min-height = 1% so a non-zero value is always visible.
            const heightPct = row.value > 0 ? Math.max(1, yPercent(row.value)) : 0;
            // Per-bar date — only known for aggregations that map to a
            // single reading (latest / max / min). Shown in the CSS
            // tooltip below; avg / sum don't carry one.
            const dateKey = data.aggregator as "latest" | "max" | "min";
            const dateIso = row.dates?.[dateKey];
            const dateShort = dateIso ? formatShortDate(dateIso) : null;
            const valueLabel =
              row.value > 0
                ? `${formatNumber(row.value, decimals)}${unit}`
                : "Sin datos";
            return (
              <div
                key={row.player_id}
                className={styles.vBarCol}
                onMouseEnter={(e) =>
                  setHover({
                    name: row.player_name,
                    value: valueLabel,
                    date: dateShort,
                    x: e.clientX,
                    y: e.clientY,
                  })
                }
                onMouseMove={(e) =>
                  setHover((cur) =>
                    cur ? { ...cur, x: e.clientX, y: e.clientY } : cur,
                  )
                }
                onMouseLeave={() => setHover(null)}
              >
                <span className={styles.vBarValue}>
                  {row.value > 0 ? formatNumber(row.value, decimals) : "—"}
                </span>
                <div
                  className={styles.vBar}
                  style={{ height: `${heightPct}%` }}
                />
                <span className={styles.vBarLabel} title={row.player_name}>
                  {shortPlayerName(row.player_name)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      )}
      <FloatingTooltip hover={hover} />
    </div>
  );
}

/** Mouse-following tooltip rendered into document.body so it isn't
 *  clipped by the chart's overflow box. Positioned a few px off the
 *  cursor, with edge-flipping so it doesn't get cut by the viewport. */
function FloatingTooltip({ hover }: { hover: HoverTip | null }) {
  if (hover === null) return null;
  if (typeof document === "undefined") return null;

  const OFFSET_X = 12;
  const OFFSET_Y = 12;
  const TT_W_EST = 220; // rough; only used for edge flipping.
  const TT_H_EST = 56;

  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;

  let left = hover.x + OFFSET_X;
  let top = hover.y + OFFSET_Y;
  if (left + TT_W_EST > vw) left = hover.x - TT_W_EST - OFFSET_X;
  if (top + TT_H_EST > vh) top = hover.y - TT_H_EST - OFFSET_Y;

  return createPortal(
    <div
      className={styles.floatingTooltip}
      style={{ left, top }}
      role="tooltip"
    >
      <div className={styles.floatingTooltipName}>{hover.name}</div>
      <div className={styles.floatingTooltipValue}>{hover.value}</div>
      {hover.date && (
        <div className={styles.floatingTooltipDate}>{hover.date}</div>
      )}
    </div>,
    document.body,
  );
}

function MultiFieldView({
  widget, data, pickedAgg, onPickAgg,
}: {
  widget: TeamReportWidget;
  data: TeamLeaderboardPayload;
  pickedAgg: Aggregator | null;
  onPickAgg: (next: Aggregator | null) => void;
}) {
  const fields = React.useMemo(() => data.fields ?? [], [data.fields]);

  // Per-field max so each bar is sized vs its own metric's team-wide
  // max (different units can't share a scale).
  const maxByField = React.useMemo(() => {
    const out: Record<string, number> = {};
    for (const f of fields) {
      let m = 0;
      for (const row of data.rows) {
        if (!isMultiRow(row)) continue;
        const v = row.values[f.key];
        if (typeof v === "number" && v > m) m = v;
      }
      out[f.key] = m > 0 ? m : 1;
    }
    return out;
  }, [fields, data.rows]);

  return (
    <div className={styles.widget}>
      <Header
        widget={widget}
        data={data}
        pickedAgg={pickedAgg}
        onPickAgg={onPickAgg}
        showAggSelector={false}
        showToggle={false}
      />

      <div className={styles.legend} aria-hidden="true">
        {fields.map((f, i) => (
          <span key={f.key} className={styles.legendItem}>
            <span
              className={styles.legendSwatch}
              style={{ background: FIELD_COLORS[i % FIELD_COLORS.length] }}
            />
            {f.label}{f.unit ? ` (${f.unit})` : ""}
          </span>
        ))}
      </div>

      <div className={styles.multiBody}>
        {data.rows.filter(isMultiRow).map((row) => (
          <div key={row.player_id} className={styles.multiRow}>
            <span className={styles.multiName} title={row.player_name}>
              {row.player_name}
            </span>
            <div className={styles.multiBars}>
              {fields.map((f, i) => {
                const value = row.values[f.key];
                if (typeof value !== "number") {
                  return (
                    <div key={f.key} className={styles.multiBarRow}>
                      <div className={styles.multiBarEmpty}>—</div>
                      <span className={styles.multiBarLabel}>{f.label}</span>
                    </div>
                  );
                }
                const fieldMax = maxByField[f.key] || 1;
                const widthPct = Math.max(2, (value / fieldMax) * 100);
                const color = FIELD_COLORS[i % FIELD_COLORS.length];
                const fieldUnit = f.unit ? ` ${f.unit}` : "";
                return (
                  <div key={f.key} className={styles.multiBarRow}>
                    <div
                      className={styles.multiBar}
                      style={{ width: `${widthPct}%`, background: color }}
                      title={`${f.label} · ${value}${fieldUnit}`}
                    >
                      <span className={styles.multiBarValue}>
                        {formatNumber(value)}{fieldUnit}
                      </span>
                    </div>
                    <span className={styles.multiBarLabel}>{f.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function podiumClass(rank: number, styles: Record<string, string>): string {
  if (rank === 1) return styles.rowGold;
  if (rank === 2) return styles.rowSilver;
  if (rank === 3) return styles.rowBronze;
  return "";
}

function Header({
  widget, data, pickedAgg, onPickAgg, showAggSelector,
  showToggle, showNoData, onToggleShowNoData, hiddenCount,
}: {
  widget: TeamReportWidget;
  data: TeamLeaderboardPayload;
  pickedAgg: Aggregator | null;
  onPickAgg: (next: Aggregator | null) => void;
  showAggSelector: boolean;
  showToggle: boolean;
  showNoData?: boolean;
  onToggleShowNoData?: (next: boolean) => void;
  hiddenCount?: number;
}) {
  const aggLabel = AGGREGATOR_LABELS[data.aggregator] ?? data.aggregator;
  const fieldLabel = data.field
    ? data.field.unit
      ? `${data.field.label} (${data.field.unit})`
      : data.field.label
    : "";
  // Window caption is only meaningful for aggregations that span the
  // whole period (avg / sum). For latest / min / max each bar carries
  // its own date label, so a single window line would be misleading.
  const showWindowCaption =
    data.aggregator === "avg" || data.aggregator === "sum";
  const windowCaption = showWindowCaption ? formatWindowCaption(data.window) : null;
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
        {windowCaption && (
          <span className={styles.windowCaption}>{windowCaption}</span>
        )}
      </div>
      <div className={styles.headerRight}>
        {showAggSelector ? (
          <label className={styles.aggSelectLabel}>
            <span className={styles.aggSelectHint}>Ver</span>
            <select
              className={styles.aggSelect}
              value={pickedAgg ?? data.aggregator}
              onChange={(e) => onPickAgg(e.target.value as Aggregator)}
            >
              {SELECTOR_ORDER.map((k) => (
                <option key={k} value={k}>
                  {AGGREGATOR_LABELS[k]}
                </option>
              ))}
            </select>
          </label>
        ) : (
          fieldLabel && (
            <span className={styles.subtitleTag}>
              {aggLabel} · {fieldLabel}
            </span>
          )
        )}
        {showAggSelector && fieldLabel && (
          <span className={styles.subtitleTag}>{fieldLabel}</span>
        )}
        {showToggle && onToggleShowNoData && (
          <ShowNoDataToggle
            checked={showNoData ?? false}
            onChange={onToggleShowNoData}
            hiddenCount={hiddenCount ?? 0}
          />
        )}
      </div>
    </header>
  );
}

function formatNumber(n: number, decimals?: number | null): string {
  if (typeof decimals === "number") {
    return n.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}

/** Render the window range as a human caption ("Datos del 21 abr al 21
 *  may 2026"). Returns null when both edges are missing — caller skips
 *  the line in that case. */
function formatWindowCaption(
  window: TeamLeaderboardPayload["window"] | undefined,
): string | null {
  if (!window) return null;
  const from = window.from ? formatShortDate(window.from) : null;
  const to = window.to ? formatShortDate(window.to) : null;
  if (from && to) return `Datos del ${from} al ${to}`;
  if (from) return `Datos desde ${from}`;
  if (to) return `Datos hasta ${to}`;
  return null;
}

/** "2026-05-18" → "18 may 2026". Used for window captions + per-bar
 *  tooltip date hints. Falls back to the raw ISO on parse failure. */
function formatShortDate(iso: string): string {
  // Avoid Date(iso) UTC quirks — split + construct locally.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("es-CL", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** Shrink "Lucas Romero Rivera" → "L. Rivera" so 25+ vertical-bar
 *  labels fit without overlapping. Single-word names stay as-is. */
function shortPlayerName(full: string): string {
  const parts = full.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return full;
  const initial = parts[0][0].toUpperCase();
  const lastWord = parts[parts.length - 1];
  return `${initial}. ${lastWord}`;
}
