"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import type { Category } from "@/lib/types";
import styles from "./page.module.css";

type Bucket = "week" | "month";

// Range options per bucket. Each entry is `{n, label}` where `n` is the
// number of buckets to request and `label` is human-facing. The first
// entry per bucket is the default when the user switches buckets and
// the previously-selected N isn't valid for the new bucket.
const RANGE_OPTIONS: Record<Bucket, { n: number; label: string }[]> = {
  week: [
    { n: 12, label: "Últimas 12 semanas" },
    { n: 26, label: "Últimas 26 semanas (~6 meses)" },
    { n: 52, label: "Últimas 52 semanas (~1 año)" },
    { n: 104, label: "Últimas 104 semanas (~2 años)" },
  ],
  month: [
    { n: 6, label: "Últimos 6 meses" },
    { n: 12, label: "Últimos 12 meses" },
    { n: 24, label: "Últimos 24 meses" },
    { n: 36, label: "Últimos 36 meses" },
    { n: 60, label: "Últimos 60 meses (~5 años)" },
  ],
};

interface UsagePayload {
  bucket: Bucket;
  departments: { slug: string; name: string }[];
  series: Array<{ bucket: string } & Record<string, string | number>>;
  templates: {
    slug: string;
    name: string;
    department_slug: string;
    department_name: string;
    count: number;
  }[];
  templates_series: Array<{ bucket: string } & Record<string, string | number>>;
}

// Stable per-department colors. Slug-driven so order changes don't shuffle hues.
const DEPT_COLORS: Record<string, string> = {
  medico: "#ef4444",
  fisico: "#3b82f6",
  nutricional: "#10b981",
  psicosocial: "#a855f7",
  tactico: "#f59e0b",
};
const FALLBACK_COLORS = ["#6366f1", "#14b8a6", "#f43f5e", "#84cc16", "#0ea5e9"];

function colorFor(slug: string, idx: number): string {
  return DEPT_COLORS[slug] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
}

// Build a per-template color: anchor on the department hue, then step
// brightness so multiple templates from the same department are still
// distinguishable inside the stacked bar.
function templateColor(
  templateSlug: string,
  departmentSlug: string,
  positionInDept: number,
  deptIdx: number,
): string {
  const base = colorFor(departmentSlug, deptIdx);
  // Skip mutation for the first template in each dept — the base color
  // is the "primary" reading.
  if (positionInDept === 0) return base;
  // Lighten/darken by stepping luminance. We avoid pulling in a color util
  // by parsing the hex inline.
  const hex = base.replace("#", "");
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  // Alternate lighten / darken so we get visual contrast either side.
  const step = positionInDept * 18;
  const delta = positionInDept % 2 === 1 ? step : -step;
  const clamp = (n: number) => Math.max(0, Math.min(255, n));
  const toHex = (n: number) => clamp(n).toString(16).padStart(2, "0");
  return `#${toHex(r + delta)}${toHex(g + delta)}${toHex(b + delta)}`;
}

function formatBucketLabel(iso: string, bucket: Bucket): string {
  const d = new Date(iso + "T00:00:00");
  if (bucket === "month") {
    return d.toLocaleDateString("es-CL", { month: "short", year: "2-digit" });
  }
  return d.toLocaleDateString("es-CL", { day: "2-digit", month: "short" });
}

export default function UsoPage() {
  const { user } = useAuth();
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [bucket, setBucket] = useState<Bucket>("week");
  const [rangeN, setRangeN] = useState<number>(RANGE_OPTIONS.week[0].n);
  const [data, setData] = useState<UsagePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // When the bucket changes, snap rangeN to the first option for the
  // new bucket (so weeks→months doesn't try to ask for "104 months",
  // and vice versa). Picking from the same bucket keeps the user's
  // choice intact.
  const handleBucketChange = (next: Bucket) => {
    setBucket(next);
    const valid = RANGE_OPTIONS[next].some((o) => o.n === rangeN);
    if (!valid) setRangeN(RANGE_OPTIONS[next][0].n);
  };

  // Load categories once, then auto-select Primer Equipo if present.
  useEffect(() => {
    let cancelled = false;
    api<Category[]>("/categories")
      .then((cats) => {
        if (cancelled) return;
        setCategories(cats);
        const primer = cats.find((c) => c.name === "Primer Equipo");
        if (primer) setCategoryId(primer.id);
      })
      .catch(() => {
        if (!cancelled) setCategories([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Refetch whenever filters change.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ bucket, n: String(rangeN) });
    if (categoryId) params.set("category_id", categoryId);
    api<UsagePayload>(`/admin/usage?${params}`)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Error al cargar uso");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bucket, categoryId, rangeN]);

  const chartData = useMemo(() => {
    if (!data) return [];
    return data.series.map((s) => ({ ...s, label: formatBucketLabel(s.bucket, data.bucket) }));
  }, [data]);

  // Per-template color, derived once per payload. Computed at the page
  // level so the legend, tooltip, and bars all see the same palette.
  const templateColorBySlug = useMemo(() => {
    const map: Record<string, string> = {};
    if (!data) return map;
    const seenInDept: Record<string, number> = {};
    for (const t of data.templates) {
      const deptIdx = data.departments.findIndex((d) => d.slug === t.department_slug);
      const posInDept = seenInDept[t.department_slug] ?? 0;
      map[t.slug] = templateColor(
        t.slug,
        t.department_slug,
        posInDept,
        deptIdx >= 0 ? deptIdx : 0,
      );
      seenInDept[t.department_slug] = posInDept + 1;
    }
    return map;
  }, [data]);

  const templatesChartData = useMemo(() => {
    if (!data) return [];
    return data.templates_series.map((s) => ({
      ...s,
      label: formatBucketLabel(s.bucket, data.bucket),
    }));
  }, [data]);

  const totalForPeriod = useMemo(() => {
    if (!data) return 0;
    let t = 0;
    for (const s of data.series) {
      for (const dept of data.departments) {
        const v = s[dept.slug];
        if (typeof v === "number") t += v;
      }
    }
    return t;
  }, [data]);

  if (!user?.is_superuser) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>
          Esta página es solo para administradores.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Uso de la aplicación</h1>
        <p className={styles.subtitle}>
          Cantidad de registros guardados, agrupados por departamento.
        </p>
      </header>

      <div className={styles.controls}>
        <label className={styles.field}>
          <span className={styles.label}>Categoría</span>
          <select
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            <option value="">Todas</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Agrupar por</span>
          <select
            value={bucket}
            onChange={(e) => handleBucketChange(e.target.value as Bucket)}
          >
            <option value="week">Semana</option>
            <option value="month">Mes</option>
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Rango</span>
          <select
            value={String(rangeN)}
            onChange={(e) => setRangeN(Number(e.target.value))}
          >
            {RANGE_OPTIONS[bucket].map((o) => (
              <option key={o.n} value={String(o.n)}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <div className={styles.totalTag}>
          {totalForPeriod.toLocaleString("es-CL")} registros
        </div>
      </div>

      <div className={styles.chartCard}>
        {error ? (
          <div className={styles.empty}>{error}</div>
        ) : loading && !data ? (
          <div className={styles.empty}>Cargando…</div>
        ) : !data || data.departments.length === 0 ? (
          <div className={styles.empty}>
            Sin registros en este período.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis
                dataKey="label"
                tick={{ fill: "#6b7280", fontSize: 12 }}
              />
              <YAxis
                tick={{ fill: "#6b7280", fontSize: 12 }}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  background: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {data.departments.map((d, idx) => (
                <Bar
                  key={d.slug}
                  dataKey={d.slug}
                  name={d.name}
                  stackId="a"
                  fill={colorFor(d.slug, idx)}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>Registros por plantilla</h2>
        <span className={styles.sectionHint}>
          Mismo filtro y período que el gráfico superior. Color por departamento.
        </span>
      </div>

      <div className={styles.chartCard}>
        {!data || data.templates.length === 0 ? (
          <div className={styles.empty}>
            Sin registros en este período.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={420}>
            <BarChart
              data={templatesChartData}
              margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis
                dataKey="label"
                tick={{ fill: "#6b7280", fontSize: 12 }}
              />
              <YAxis
                tick={{ fill: "#6b7280", fontSize: 12 }}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  background: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                iconSize={10}
              />
              {data.templates.map((t) => (
                <Bar
                  key={t.slug}
                  dataKey={t.slug}
                  name={t.name}
                  stackId="t"
                  fill={templateColorBySlug[t.slug]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
