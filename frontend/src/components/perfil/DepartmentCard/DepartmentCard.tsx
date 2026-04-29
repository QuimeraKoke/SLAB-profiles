"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Line,
  LineChart as RechartsLineChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import type { ExamField, ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./DepartmentCard.module.css";

interface DepartmentCardProps {
  template: ExamTemplate;
  results: ExamResult[];
  playerId: string;
  departmentSlug: string;
}

const PAGE_SIZE = 4;

export default function DepartmentCard({
  template,
  results,
  playerId,
  departmentSlug,
}: DepartmentCardProps) {
  const [page, setPage] = useState(0);

  const fields = template.config_schema?.fields ?? [];
  const sortedResults = useMemo(
    () =>
      [...results].sort(
        (a, b) =>
          new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime(),
      ),
    [results],
  );

  const totalPages = Math.max(1, Math.ceil(sortedResults.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);

  // Reset paging if results shrink unexpectedly.
  useEffect(() => {
    if (page > totalPages - 1) setPage(0);
  }, [page, totalPages]);

  const visibleResults = sortedResults.slice(
    safePage * PAGE_SIZE,
    (safePage + 1) * PAGE_SIZE,
  );

  const addHref = `/perfil/${playerId}/registrar/${template.id}?tab=${encodeURIComponent(departmentSlug)}`;

  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <h4 className={styles.title}>{template.name}</h4>
        <span className={styles.count}>
          {results.length} {results.length === 1 ? "registro" : "registros"}
        </span>
      </header>

      {results.length === 0 ? (
        <div className={styles.empty}>Aún sin registros para esta plantilla.</div>
      ) : (
        <>
          <CardVisualization fields={fields} results={sortedResults} />
          <CardTable fields={fields} results={visibleResults} />
        </>
      )}

      <footer className={styles.footer}>
        {totalPages > 1 ? (
          <div className={styles.pagination}>
            <button
              type="button"
              className={styles.pageBtn}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              aria-label="Página anterior"
            >
              ‹
            </button>
            <span className={styles.pageInfo}>
              {safePage + 1} / {totalPages}
            </span>
            <button
              type="button"
              className={styles.pageBtn}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              aria-label="Página siguiente"
            >
              ›
            </button>
          </div>
        ) : (
          <span />
        )}
        <Link href={addHref} className={styles.addBtn}>
          + Agregar
        </Link>
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visualization (chart strip or sparkline)
// ---------------------------------------------------------------------------

interface VisualizationProps {
  fields: ExamField[];
  /** Newest-first. */
  results: ExamResult[];
}

function CardVisualization({ fields, results }: VisualizationProps) {
  const lineFields = fields.filter((f) => f.chart_type === "line");
  const statFields = fields.filter((f) => f.chart_type === "stat_card");

  if (lineFields.length > 0) {
    return (
      <div className={styles.chartGrid}>
        {lineFields.map((f) => (
          <MiniLineChart key={f.key} field={f} results={results} />
        ))}
      </div>
    );
  }
  if (statFields.length > 0) {
    return <StatStrip fields={statFields.slice(0, 3)} results={results} />;
  }
  return null;
}

function MiniLineChart({
  field,
  results,
}: {
  field: ExamField;
  results: ExamResult[];
}) {
  const data = [...results]
    .reverse()
    .map((r) => ({
      value:
        typeof r.result_data[field.key] === "number"
          ? (r.result_data[field.key] as number)
          : null,
      recorded_at: r.recorded_at,
    }))
    .filter((d) => d.value !== null);

  if (data.length === 0) return null;

  const latest = data[data.length - 1].value!;
  const previous = data.length > 1 ? data[data.length - 2].value! : null;
  const delta = previous !== null ? latest - previous : null;

  return (
    <div className={styles.miniChart}>
      <span className={styles.chartLabel}>{field.label}</span>
      <div className={styles.chartValueRow}>
        <span className={styles.chartValue}>
          {latest.toFixed(2)}
        </span>
        {field.unit && <span className={styles.chartUnit}>{field.unit}</span>}
        {delta !== null && (
          <span className={delta >= 0 ? styles.up : styles.down}>
            {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(2)}
          </span>
        )}
      </div>
      <div className={styles.chartArea}>
        <ResponsiveContainer width="100%" height={40}>
          <RechartsLineChart
            data={data}
            margin={{ top: 4, right: 4, left: 4, bottom: 4 }}
          >
            <Tooltip
              content={<SparkTooltip field={field} />}
              cursor={{ stroke: "#9ca3af", strokeDasharray: "3 3", strokeWidth: 1 }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#6d28d9"
              strokeWidth={1.75}
              dot={false}
              activeDot={{ r: 3, fill: "#6d28d9", stroke: "#ffffff", strokeWidth: 1 }}
              isAnimationActive={false}
            />
          </RechartsLineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface SparkTooltipProps {
  active?: boolean;
  payload?: Array<{ payload?: { value?: number; recorded_at?: string } }>;
  field: ExamField;
}

function SparkTooltip({ active, payload, field }: SparkTooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point || typeof point.value !== "number" || !point.recorded_at) return null;
  return (
    <div className={styles.tooltip}>
      <span className={styles.tooltipDate}>
        {new Date(point.recorded_at).toLocaleDateString(undefined, {
          day: "2-digit",
          month: "short",
          year: "numeric",
        })}
      </span>
      <span className={styles.tooltipValue}>
        {point.value.toFixed(2)}
        {field.unit ? ` ${field.unit}` : ""}
      </span>
    </div>
  );
}

function StatStrip({
  fields,
  results,
}: {
  fields: ExamField[];
  results: ExamResult[];
}) {
  const latest = results[0]?.result_data ?? {};
  const previous = results[1]?.result_data ?? {};

  return (
    <div className={styles.statStrip}>
      {fields.map((f) => {
        const value = latest[f.key];
        const prev = previous[f.key];
        const delta =
          typeof value === "number" && typeof prev === "number"
            ? value - prev
            : null;

        return (
          <div key={f.key} className={styles.statItem}>
            <span className={styles.statLabel}>{f.label}</span>
            <div className={styles.statRow}>
              <span className={styles.statValue}>
                {formatValue(value)}
                {f.unit ? ` ${f.unit}` : ""}
              </span>
              {delta !== null && (
                <span className={delta >= 0 ? styles.up : styles.down}>
                  {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(2)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact table
// ---------------------------------------------------------------------------

interface CardTableProps {
  fields: ExamField[];
  results: ExamResult[];
}

function CardTable({ fields, results }: CardTableProps) {
  const columns = useMemo(() => pickColumns(fields), [fields]);

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Fecha</th>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={r.id}>
              <td className={styles.dateCell}>{formatDate(r.recorded_at)}</td>
              {columns.map((c) => {
                const raw = r.result_data[c.key];
                return (
                  <td key={c.key} title={raw === null || raw === undefined ? "" : String(raw)}>
                    {truncate(formatValue(raw), 36)}
                    {c.unit && raw !== null && raw !== undefined && raw !== "" ? ` ${c.unit}` : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function pickColumns(fields: ExamField[]): ExamField[] {
  const subject = fields.find((f) => f.key === "asunto" || f.key === "objetivo");
  const status = fields.find((f) => f.key === "estado");
  const calculated = fields.filter((f) => f.type === "calculated");
  const otherShort = fields.filter(
    (f) =>
      f !== subject &&
      f !== status &&
      f.type !== "calculated" &&
      f.type !== "date" &&
      !(f.type === "text" && f.multiline),
  );

  const picked: ExamField[] = [];
  if (subject) picked.push(subject);
  if (status) picked.push(status);
  for (const f of calculated) {
    if (picked.length >= 3) break;
    picked.push(f);
  }
  for (const f of otherShort) {
    if (picked.length >= 3) break;
    picked.push(f);
  }
  return picked.slice(0, 3);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + "…";
}
