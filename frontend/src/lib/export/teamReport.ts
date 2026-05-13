/**
 * Excel export for /reportes/[deptSlug].
 *
 * Walks the layout currently rendered on the page and serializes each
 * widget into its own sheet. Per request: client-side only, exports
 * what's on screen — filters already applied server-side mean the
 * payload is the source of truth; we just transcribe it to spreadsheet.
 *
 * Design choices:
 *  - One sheet per widget. Sheet name = sanitized widget title (Excel
 *    caps at 31 chars, no `[]:*?/\\` allowed) + a numeric suffix to keep
 *    duplicates apart.
 *  - First sheet is "Resumen" with filter context (period, position,
 *    selected players, generated-at) so the user can re-derive how the
 *    file was produced months later.
 *  - Arrays of arrays via `XLSX.utils.aoa_to_sheet` — keeps every
 *    serializer dead simple and lets us prepend metadata rows naturally.
 *  - Numbers stay as numbers (not strings) so Excel formulas keep
 *    working downstream.
 */

import type {
  TeamActiveRecordsPayload,
  TeamActivityCoveragePayload,
  TeamDistributionPayload,
  TeamGoalProgressPayload,
  TeamHorizontalComparisonPayload,
  TeamLeaderboardPayload,
  TeamReportSection,
  TeamRosterMatrixPayload,
  TeamStatusCountsPayload,
  TeamTrendLinePayload,
  TeamWidgetData,
} from "@/lib/types";

// Imported lazily by callers; we only use the type here so TS doesn't
// pull the runtime module into a server bundle.
import type * as XLSXType from "xlsx";

import {
  type AOA,
  buildFilename as sharedBuildFilename,
  formatDateTime,
  formatScalar,
  uniqueSheetName,
} from "./shared";

export interface ExportMeta {
  departmentName: string;
  categoryName: string;
  /** Active filter snapshot, used to populate the Resumen sheet. */
  filters: {
    positionLabel: string;       // e.g. "Defensores" or "Todas"
    playerNames: string[];       // empty array = "Todo el plantel"
    dateFrom: string;            // YYYY-MM-DD
    dateTo: string;              // YYYY-MM-DD
  };
  /** When the user clicked "Descargar". Local time, formatted. */
  generatedAt: Date;
}

/** Build an `XLSX.WorkBook` from a layout + filter metadata. The caller
 *  is responsible for handing it to `XLSX.writeFile` (or similar). */
export function buildWorkbook(
  XLSX: typeof XLSXType,
  sections: TeamReportSection[],
  meta: ExportMeta,
): XLSXType.WorkBook {
  const wb = XLSX.utils.book_new();

  // -- Resumen sheet ---------------------------------------------------
  const resumen: AOA = [
    ["Reporte por departamento"],
    [],
    ["Departamento", meta.departmentName],
    ["Categoría", meta.categoryName],
    ["Generado", formatDateTime(meta.generatedAt)],
    [],
    ["— Filtros aplicados —"],
    ["Posición", meta.filters.positionLabel || "Todas"],
    [
      "Jugadores",
      meta.filters.playerNames.length === 0
        ? "Todo el plantel"
        : meta.filters.playerNames.join(", "),
    ],
    ["Desde", meta.filters.dateFrom || "—"],
    ["Hasta", meta.filters.dateTo || "—"],
  ];
  const resumenSheet = XLSX.utils.aoa_to_sheet(resumen);
  XLSX.utils.book_append_sheet(wb, resumenSheet, "Resumen");

  // -- One sheet per widget --------------------------------------------
  const usedNames = new Set<string>(["Resumen"]);
  for (const section of sections) {
    for (const widget of section.widgets) {
      const sheetData = serializeWidget(widget.data, widget.title);
      if (sheetData === null) continue;
      const name = uniqueSheetName(widget.title || "Widget", usedNames);
      usedNames.add(name);
      const sheet = XLSX.utils.aoa_to_sheet(sheetData);
      XLSX.utils.book_append_sheet(wb, sheet, name);
    }
  }

  return wb;
}

// ---------------------------------------------------------------------------
// Per-chart-type serializers. Each returns an array-of-arrays that
// becomes the sheet's contents — first row(s) are typically header /
// metadata; everything below is tabular data.
//
// Returning `null` from a serializer means "skip this widget" (e.g.
// unsupported chart_type or fundamentally empty payload). Empty data
// payloads with valid shape still produce a sheet with just a header
// + "Sin datos" row so the user sees the widget represented.
// ---------------------------------------------------------------------------


function serializeWidget(data: TeamWidgetData, title: string): AOA | null {
  // We cast inside each branch because the `UnsupportedPayload` /
  // `EmptyPayload` variants in the TeamWidgetData union widen
  // `chart_type` back to `string`, which prevents TypeScript from
  // narrowing through the switch. The branches themselves are exhaustive
  // over the literal chart_type values that have a dedicated payload.
  switch (data.chart_type) {
    case "team_horizontal_comparison":
      return serializeHorizontalComparison(data as TeamHorizontalComparisonPayload, title);
    case "team_roster_matrix":
      return serializeRosterMatrix(data as TeamRosterMatrixPayload, title);
    case "team_status_counts":
      return serializeStatusCounts(data as TeamStatusCountsPayload, title);
    case "team_trend_line":
      return serializeTrendLine(data as TeamTrendLinePayload, title);
    case "team_distribution":
      return serializeDistribution(data as TeamDistributionPayload, title);
    case "team_active_records":
      return serializeActiveRecords(data as TeamActiveRecordsPayload, title);
    case "team_activity_coverage":
      return serializeActivityCoverage(data as TeamActivityCoveragePayload, title);
    case "team_leaderboard":
      return serializeLeaderboard(data as TeamLeaderboardPayload, title);
    case "team_goal_progress":
      return serializeGoalProgress(data as TeamGoalProgressPayload, title);
    default:
      return null;
  }
}

function serializeGoalProgress(
  data: TeamGoalProgressPayload,
  title: string,
): AOA {
  // Wide: one row per player, columns alternating value + status per goal.
  const header: (string | number | null)[] = ["Jugador"];
  for (const col of data.columns) {
    const opLabel = ({"<=":"≤","<":"<","==":"=",">=":"≥",">":">"} as Record<string, string>)[col.operator] ?? col.operator;
    const colHeader = `${col.field_label} (${opLabel} ${col.target_value}${col.field_unit ? " " + col.field_unit : ""})`;
    header.push(`${colHeader} — valor`);
    header.push(`${colHeader} — estado`);
  }
  const statusLabels: Record<string, string> = {
    achieved: "Cumplido",
    in_progress: "En curso",
    missed: "Vencido",
    no_data: "Sin medición",
  };
  const rows: AOA = [
    [title],
    [
      `Resumen: ${data.summary.achieved} cumplidos · ${data.summary.in_progress} en curso · `
      + `${data.summary.missed} vencidos · ${data.summary.no_data} sin medición`,
    ],
    [],
    header,
  ];
  if (data.empty || data.rows.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const row of data.rows) {
    const out: (string | number | null)[] = [row.player_name];
    for (const col of data.columns) {
      const cell = row.cells[col.key];
      if (!cell) {
        out.push("—", "Sin objetivo");
        continue;
      }
      out.push(cell.current_value, statusLabels[cell.status] ?? cell.status);
    }
    rows.push(out);
  }
  return rows;
}

function serializeLeaderboard(
  data: TeamLeaderboardPayload,
  title: string,
): AOA {
  const fieldLabel = data.field
    ? data.field.unit
      ? `${data.field.label} (${data.field.unit})`
      : data.field.label
    : "";
  const rows: AOA = [
    [title],
    [`Métrica: ${fieldLabel}`],
    [`Agregador: ${data.aggregator} · Orden: ${data.order} · Top ${data.limit}`],
    [],
    ["Posición", "Jugador", "Valor", "Tomas"],
  ];
  if (data.empty || data.rows.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const row of data.rows) {
    rows.push([row.rank, row.player_name, row.value, row.samples]);
  }
  return rows;
}

function serializeActivityCoverage(
  data: TeamActivityCoveragePayload,
  title: string,
): AOA {
  // Wide: one row per player, one column per template. Each cell carries
  // the days-since count + the last-result ISO date so the user can drill
  // into specific delays without going back to the app.
  const header: (string | number | null)[] = ["Jugador"];
  for (const col of data.columns) {
    header.push(`${col.label} — días`);
    header.push(`${col.label} — última toma`);
  }
  const rows: AOA = [
    [title],
    [`Al ${data.as_of}`],
    [`Umbrales: verde ≤ ${data.thresholds.green_max} d · amarillo ≤ ${data.thresholds.yellow_max} d`],
    [],
    header,
  ];
  if (data.empty || data.rows.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const row of data.rows) {
    const out: (string | number | null)[] = [row.player_name];
    for (const col of data.columns) {
      const cell = row.cells[col.key];
      if (!cell || cell.status === "never") {
        out.push("—", "Sin registro");
      } else {
        out.push(cell.days_since, cell.last_iso ?? "");
      }
    }
    rows.push(out);
  }
  return rows;
}

function serializeHorizontalComparison(
  data: TeamHorizontalComparisonPayload,
  title: string,
): AOA {
  // Tidy / long format: one row per (subject, field, reading). Subject is
  // either a player (default) or a position group (when the widget is
  // configured with `group_by: "position"`). Header label flips so the
  // exported sheet is self-describing.
  const isByPosition = data.grouping === "position";
  const subjectHeader = isByPosition ? "Posición" : "Jugador";
  const rows: AOA = [[title], [], [subjectHeader, "Métrica", "Unidad", "Fecha", "Valor"]];
  if (data.empty || (data.rows ?? []).length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  const fieldsByKey = new Map(data.fields.map((f) => [f.key, f]));
  for (const row of data.rows) {
    const subjectName = "player_name" in row ? row.player_name : row.group_name;
    let wroteAny = false;
    for (const field of data.fields) {
      const readings = row.values[field.key] || [];
      for (const r of readings) {
        rows.push([
          subjectName,
          fieldsByKey.get(field.key)?.label ?? field.key,
          field.unit ?? "",
          r.iso,
          r.value,
        ]);
        wroteAny = true;
      }
    }
    if (!wroteAny) {
      rows.push([subjectName, "—", "", "", null]);
    }
  }
  return rows;
}

function serializeRosterMatrix(
  data: TeamRosterMatrixPayload,
  title: string,
): AOA {
  // Wide format mirrors the on-screen matrix: one row per player, one
  // column per metric. Variation (when on) gets its own column right
  // after the value so deltas are easy to scan.
  const variationOn = data.variation !== "off";
  const header: (string | number | null)[] = ["Jugador"];
  for (const col of data.columns) {
    const headerLabel = col.unit ? `${col.label} (${col.unit})` : col.label;
    header.push(headerLabel);
    header.push(`${col.label} — fecha`);
    if (variationOn) {
      header.push(`${col.label} — anterior`);
    }
  }
  const rows: AOA = [[title], [], header];
  if (data.empty || (data.rows ?? []).length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const row of data.rows) {
    const out: (string | number | null)[] = [row.player_name];
    for (const col of data.columns) {
      const cell = row.cells[col.key];
      if (!cell) {
        out.push(null, null);
        if (variationOn) out.push(null);
        continue;
      }
      out.push(cell.value);
      out.push(cell.iso);
      if (variationOn) {
        out.push(cell.previous_value ?? null);
      }
    }
    rows.push(out);
  }
  return rows;
}

function serializeStatusCounts(
  data: TeamStatusCountsPayload,
  title: string,
): AOA {
  // Two sections: summary table on top, per-player detail below.
  const rows: AOA = [
    [title],
    [],
    ["— Resumen por estado —"],
    ["Estado", "Cantidad"],
  ];
  if (data.empty || data.stages.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const stage of data.stages) {
    rows.push([stage.label, stage.count]);
  }
  rows.push(["Total", data.total]);
  rows.push([]);
  rows.push(["— Jugadores por estado —"]);
  rows.push(["Jugador", "Estado"]);
  for (const stage of data.stages) {
    for (const player of stage.players) {
      rows.push([player.name, stage.label]);
    }
  }
  return rows;
}

function serializeTrendLine(
  data: TeamTrendLinePayload,
  title: string,
): AOA {
  // Wide: one row per bucket. In team-wide mode each metric is its own
  // column. In position mode each (position × metric) combo gets its own
  // column so the sheet is still pivotable. Missing values stay blank.
  const isByPosition = data.grouping === "position";
  const groups = isByPosition ? (data.groups ?? []) : [];
  const header: (string | number | null)[] = ["Período", "Fecha"];
  if (isByPosition) {
    for (const g of groups) {
      for (const f of data.fields) {
        const label = f.unit ? `${g.label} · ${f.label} (${f.unit})` : `${g.label} · ${f.label}`;
        header.push(label);
      }
    }
  } else {
    for (const f of data.fields) {
      const label = f.unit ? `${f.label} (${f.unit})` : f.label;
      header.push(label);
    }
  }
  const rows: AOA = [[title], [`Granularidad: ${data.bucket_size === "month" ? "mensual" : "semanal"}`], [], header];
  if (data.empty || data.buckets.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const bucket of data.buckets) {
    const out: (string | number | null)[] = [bucket.label, bucket.iso];
    if (isByPosition) {
      for (const g of groups) {
        const groupValues = bucket.values_by_group?.[g.id];
        for (const f of data.fields) {
          const v = groupValues?.[f.key];
          out.push(typeof v === "number" ? v : null);
        }
      }
    } else {
      for (const f of data.fields) {
        const v = bucket.values?.[f.key];
        out.push(typeof v === "number" ? v : null);
      }
    }
    rows.push(out);
  }
  return rows;
}

function serializeDistribution(
  data: TeamDistributionPayload,
  title: string,
): AOA {
  // Three sections: stats summary, bins, per-player values.
  const rows: AOA = [[title]];
  if (data.field) {
    const unit = data.field.unit ? ` (${data.field.unit})` : "";
    rows.push([`Métrica: ${data.field.label}${unit}`]);
  }
  if (typeof data.roster_size === "number") {
    rows.push([`Plantel filtrado: ${data.roster_size} jugador${data.roster_size === 1 ? "" : "es"}`]);
  }
  rows.push([]);
  rows.push(["— Estadísticas —"]);
  rows.push(["N", data.stats.n ?? null]);
  rows.push(["Media", data.stats.mean ?? null]);
  rows.push(["Mediana", data.stats.median ?? null]);
  rows.push(["Mínimo", data.stats.min ?? null]);
  rows.push(["Máximo", data.stats.max ?? null]);
  rows.push([]);
  rows.push(["— Bins (histograma) —"]);
  rows.push(["Desde", "Hasta", "Cantidad", "Jugadores"]);
  if (data.empty || data.bins.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const bin of data.bins) {
    rows.push([
      bin.low,
      bin.high,
      bin.count,
      bin.players.map((p) => p.name).join(", "),
    ]);
  }
  rows.push([]);
  rows.push(["— Detalle por jugador —"]);
  rows.push(["Jugador", "Valor"]);
  for (const bin of data.bins) {
    for (const p of bin.players) {
      rows.push([p.name, p.value]);
    }
  }
  return rows;
}

function serializeActiveRecords(
  data: TeamActiveRecordsPayload,
  title: string,
): AOA {
  const header: (string | number | null)[] = ["Jugador", "Inicio", "Fin"];
  for (const col of data.columns) {
    header.push(col.unit ? `${col.label} (${col.unit})` : col.label);
  }
  const rows: AOA = [
    [title],
    [`Activos al ${data.as_of}`],
    [`Total: ${data.active_count} / ${data.total}`],
    [],
    header,
  ];
  if (data.empty || data.rows.length === 0) {
    rows.push(["Sin datos"]);
    return rows;
  }
  for (const row of data.rows) {
    const out: (string | number | null)[] = [
      row.player_name,
      row.started_at,
      row.ends_at ?? "Sin fin definido",
    ];
    for (const col of data.columns) {
      const v = row.values[col.key];
      out.push(formatScalar(v));
    }
    rows.push(out);
  }
  return rows;
}

/** Filename: reporte-{deptSlug}-{YYYY-MM-DD}.xlsx */
export function buildFilename(deptSlug: string, generatedAt: Date): string {
  return sharedBuildFilename(["reporte", deptSlug], generatedAt);
}
