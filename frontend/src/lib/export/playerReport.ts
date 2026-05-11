/**
 * Excel export for the per-player profile dashboard
 * (`/perfil/[id]` → department tab).
 *
 * Same approach as `teamReport.ts`: walk the layout currently rendered
 * on screen and serialize each widget to its own sheet. The first sheet
 * carries player + filter context.
 *
 * Per-player chart types covered:
 *   - comparison_table       (rows = fields × columns = readings)
 *   - line_with_selector     (one row per (series, point))
 *   - multi_line             (same shape, multiple series)
 *   - grouped_bar            (one row per (reading, field))
 *   - donut_per_result       (one row per (reading, slice))
 *   - cross_exam_line        (one row per (series, point), cross-template)
 *   - body_map_heatmap       (per-region counts + per-stage breakdown)
 *
 * Unsupported / empty payloads → skipped (no sheet emitted).
 */

import type {
  BodyMapHeatmapPayload,
  ComparisonTablePayload,
  CrossExamLinePayload,
  DashboardSection,
  Department,
  DonutPerResultPayload,
  GroupedBarPayload,
  LineWithSelectorPayload,
  MultiLinePayload,
  WidgetData,
} from "@/lib/types";

import type * as XLSXType from "xlsx";

import {
  type AOA,
  buildFilename as sharedBuildFilename,
  formatDateTime,
  uniqueSheetName,
} from "./shared";

export interface PlayerExportMeta {
  playerName: string;
  department: Department;
  dateFrom: string;
  dateTo: string;
  generatedAt: Date;
}

export function buildPlayerWorkbook(
  XLSX: typeof XLSXType,
  sections: DashboardSection[],
  meta: PlayerExportMeta,
): XLSXType.WorkBook {
  const wb = XLSX.utils.book_new();

  // -- Resumen sheet ---------------------------------------------------
  const resumen: AOA = [
    ["Perfil del jugador — Reporte por departamento"],
    [],
    ["Jugador", meta.playerName],
    ["Departamento", meta.department.name],
    ["Generado", formatDateTime(meta.generatedAt)],
    [],
    ["— Filtro de período —"],
    ["Desde", meta.dateFrom || "—"],
    ["Hasta", meta.dateTo || "—"],
  ];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(resumen), "Resumen");

  // -- Per-widget sheets -----------------------------------------------
  const usedNames = new Set<string>(["Resumen"]);
  for (const section of sections) {
    for (const widget of section.widgets) {
      const aoa = serializeWidget(widget.data, widget.title);
      if (aoa === null) continue;
      const name = uniqueSheetName(widget.title || "Widget", usedNames);
      usedNames.add(name);
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(aoa), name);
    }
  }

  return wb;
}

export function buildPlayerFilename(
  playerName: string,
  deptSlug: string,
  generatedAt: Date,
): string {
  // Segments: "perfil" prefix, player name, dept slug, then the date is
  // appended by the shared helper.
  return sharedBuildFilename(["perfil", playerName, deptSlug], generatedAt);
}

// ---------------------------------------------------------------------------
// Per-chart-type serializers. Each returns the sheet contents as an AOA
// or `null` to skip (unsupported / structurally empty).
// ---------------------------------------------------------------------------


function serializeWidget(data: WidgetData, title: string): AOA | null {
  switch (data.chart_type) {
    case "comparison_table":
      return serializeComparisonTable(data as ComparisonTablePayload, title);
    case "line_with_selector":
      return serializeLineWithSelector(data as LineWithSelectorPayload, title);
    case "multi_line":
      return serializeMultiLine(data as MultiLinePayload, title);
    case "grouped_bar":
      return serializeGroupedBar(data as GroupedBarPayload, title);
    case "donut_per_result":
      return serializeDonutPerResult(data as DonutPerResultPayload, title);
    case "cross_exam_line":
      return serializeCrossExamLine(data as CrossExamLinePayload, title);
    case "body_map_heatmap":
      return serializeBodyMap(data as BodyMapHeatmapPayload, title);
    default:
      return null;
  }
}

function serializeComparisonTable(
  data: ComparisonTablePayload,
  title: string,
): AOA {
  const header: (string | number | null)[] = ["Indicador", "Unidad"];
  for (const col of data.columns) {
    header.push(formatColumnDate(col.recorded_at));
  }
  // Append a "Delta" column at the end summarizing the latest delta value
  // (deltas already line up 1:1 with `values` server-side).
  header.push("Δ último");

  const aoa: AOA = [[title], [], header];
  if (!data.rows.length) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const row of data.rows) {
    const out: (string | number | null)[] = [row.label, row.unit ?? ""];
    for (const v of row.values) {
      out.push(coerceCell(v));
    }
    const lastDelta = row.deltas[row.deltas.length - 1];
    out.push(lastDelta ?? null);
    aoa.push(out);
  }
  return aoa;
}

function serializeLineWithSelector(
  data: LineWithSelectorPayload,
  title: string,
): AOA {
  // Tidy: one row per (field, reading). Lets the user pivot in Excel.
  const aoa: AOA = [[title], [], ["Métrica", "Unidad", "Fecha", "Valor"]];
  const hasAnything = Object.values(data.series).some((pts) => pts.length > 0);
  if (!hasAnything) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const field of data.available_fields) {
    const points = data.series[field.key] || [];
    for (const pt of points) {
      aoa.push([field.label, field.unit ?? "", pt.recorded_at, pt.value]);
    }
  }
  return aoa;
}

function serializeMultiLine(data: MultiLinePayload, title: string): AOA {
  const aoa: AOA = [[title], [], ["Serie", "Unidad", "Fecha", "Valor"]];
  const hasAnything = data.series.some((s) => s.points.length > 0);
  if (!hasAnything) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const series of data.series) {
    for (const pt of series.points) {
      aoa.push([series.label, series.unit ?? "", pt.recorded_at, pt.value]);
    }
  }
  return aoa;
}

function serializeGroupedBar(data: GroupedBarPayload, title: string): AOA {
  // Wide: one row per reading, one column per field. Maps to how the
  // chart shows side-by-side bars per date.
  const header: (string | number | null)[] = ["Fecha"];
  for (const f of data.fields) {
    header.push(f.unit ? `${f.label} (${f.unit})` : f.label);
  }
  const aoa: AOA = [[title], [], header];
  if (!data.groups.length) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const group of data.groups) {
    const out: (string | number | null)[] = [group.recorded_at];
    for (const f of data.fields) {
      const bar = group.bars.find((b) => b.key === f.key);
      out.push(bar?.value ?? null);
    }
    aoa.push(out);
  }
  return aoa;
}

function serializeDonutPerResult(
  data: DonutPerResultPayload,
  title: string,
): AOA {
  // Tidy: one row per (reading, slice). Each row shows the absolute
  // value and the % share so the user can recreate the donut in Excel.
  const aoa: AOA = [
    [title],
    [],
    ["Fecha", "Categoría", "Valor", "% del total"],
  ];
  if (!data.donuts.length) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const donut of data.donuts) {
    if (!donut.slices.length) {
      aoa.push([donut.recorded_at, "(vacío)", 0, 0]);
      continue;
    }
    for (const slice of donut.slices) {
      aoa.push([
        donut.recorded_at,
        slice.label,
        slice.value,
        slice.percentage,
      ]);
    }
  }
  return aoa;
}

function serializeCrossExamLine(
  data: CrossExamLinePayload,
  title: string,
): AOA {
  // Cross-template: include template name so the source is auditable.
  const aoa: AOA = [
    [title],
    [],
    ["Serie", "Plantilla", "Unidad", "Fecha", "Valor"],
  ];
  const hasAnything = data.series.some((s) => s.points.length > 0);
  if (!hasAnything) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const series of data.series) {
    for (const pt of series.points) {
      aoa.push([
        series.label,
        series.template,
        series.unit ?? "",
        pt.recorded_at,
        pt.value,
      ]);
    }
  }
  return aoa;
}

function serializeBodyMap(data: BodyMapHeatmapPayload, title: string): AOA {
  // Two sections: regional totals + per-stage breakdown when present.
  const aoa: AOA = [
    [title],
    [`Plantilla: ${data.field?.label ?? "—"}`],
    [`Resultados contados: ${data.total_results}`],
    [],
    ["— Conteo por región —"],
    ["Región", "Total"],
  ];
  if (data.total_results === 0) {
    aoa.push(["Sin datos"]);
    return aoa;
  }
  for (const item of data.items) {
    aoa.push([item.region, item.count]);
  }
  // Per-stage drill-down (episodic plantillas only).
  if (data.stages.length && Object.keys(data.counts_by_stage).length) {
    aoa.push([]);
    aoa.push(["— Conteo por región y etapa —"]);
    const header: (string | number | null)[] = ["Región"];
    for (const stage of data.stages) header.push(stage.label);
    aoa.push(header);
    const regions = Array.from(new Set(data.items.map((i) => i.region)));
    for (const region of regions) {
      const row: (string | number | null)[] = [region];
      for (const stage of data.stages) {
        row.push(data.counts_by_stage[stage.value]?.[region] ?? 0);
      }
      aoa.push(row);
    }
  }
  return aoa;
}

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

/** Format an ISO datetime as the bare date portion. Keeps comparison
 *  table headers compact ("2026-04-12" instead of full ISO). */
function formatColumnDate(iso: string): string {
  return iso ? iso.slice(0, 10) : "";
}

/** Per-player payloads can carry mixed-type cells in `comparison_table`
 *  (number/string/boolean/null). Reuse the shared coercion logic via a
 *  thin wrapper so booleans render as Sí/No in Spanish. */
function coerceCell(v: number | string | boolean | null): string | number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v ? "Sí" : "No";
  return v;
}
