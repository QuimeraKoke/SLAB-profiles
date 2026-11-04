"use client";

/**
 * Composición corporal — "¿Cómo evoluciona músculo, grasa, Σ pliegues?"
 * (question 9). The club's own artifact is the spec: a squad table (last
 * reading + change vs the previous one, tap a player), and per player every
 * metric last vs previous, one metric over time and every measurement.
 * Green = favourable (more muscle, less fat); the weight stays grey.
 */

import React, { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/lib/api";
import { deltaTone, deltaToneTitle } from "@/lib/deltaTone";
import { type CompMetric, type CompositionPayload, shortDate } from "@/lib/loadControl";

import styles from "./loadControl.module.css";

const INK = "#475467";

interface Props {
  categoryId: string;
  playerId: string | null;
  metric: string | null;
  sort: string | null;
  onFilters: (f: { player?: string | null; metric?: string | null; sort?: string | null }) => void;
}

const num = (v: unknown, dec: number) =>
  typeof v === "number" ? v.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec }) : "—";
const longDate = (iso: string) => `${shortDate(iso)} ${iso.slice(2, 4)}`;

function Delta({ d, m }: { d: number | null | undefined; m: CompMetric }) {
  if (d == null) return <span className={styles.muted}>—</span>;
  const zero = Math.abs(d) < 10 ** -m.decimals / 2;
  const tone = zero ? "flat" : deltaTone(d, m.direction);
  return (
    <span className={`${styles.delta} ${styles[`tone_${tone}`] ?? ""}`} title={deltaToneTitle(tone)}>
      {zero ? "=" : `${d > 0 ? "▲ +" : "▼ "}${num(d, m.decimals)}`}
    </span>
  );
}

export default function CompositionView({ categoryId, playerId, metric, sort, onFilters }: Props) {
  const [data, setData] = useState<CompositionPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const sp = new URLSearchParams({ category_id: categoryId });
    if (playerId) sp.set("player_id", playerId);
    api<CompositionPayload>(`/load-control/composition?${sp}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la composición."); });
    return () => { cancelled = true; };
  }, [categoryId, playerId]);

  const byKey = useMemo(() => Object.fromEntries((data?.metrics ?? []).map((m) => [m.key, m])), [data]);
  const [sortKey, sortDir] = (sort ?? "").split(":");
  const rows = useMemo(() => {
    if (!data) return [];
    if (!sortKey) return data.rows;
    const val = (r: CompositionPayload["rows"][number]) =>
      sortKey === "name" ? r.name : sortKey === "date" ? r.last.date : (r.last[sortKey] as number | null);
    return [...data.rows].sort((a, b) => {
      const va = val(a), vb = val(b);
      if (va == null) return 1;
      if (vb == null) return -1;
      const c = typeof va === "string" ? va.localeCompare(vb as string, "es") : (va as number) - (vb as number);
      return sortDir === "desc" ? -c : c;
    });
  }, [data, sortKey, sortDir]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <p className={styles.muted}>Cargando…</p>;
  if (data.rows.length === 0)
    return <div className={styles.empty}>Esta categoría no tiene evaluaciones antropométricas cargadas.</div>;

  const sortBy = (key: string) =>
    onFilters({ sort: sortKey !== key ? `${key}:asc` : sortDir === "asc" ? `${key}:desc` : null });
  const head = (key: string, label: React.ReactNode) => (
    <th scope="col" aria-sort={sortKey === key ? (sortDir === "desc" ? "descending" : "ascending") : "none"}>
      <button type="button" className={styles.linkButton} style={{ textDecoration: "none", fontWeight: 600 }}
        onClick={() => sortBy(key)}>
        {label}{sortKey === key ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );
  const metricLabel = (m: CompMetric) => `${m.label}${m.unit ? ` ${m.unit}` : ""}`;

  const p = data.player;
  if (p) {
    const sel = byKey[metric ?? ""] ?? data.metrics[0];
    const series = p.measurements.map((x) => ({ tick: longDate(x.date), v: x[sel.key] as number | null }));
    const groupMean = data.mean[sel.key];
    return (
      <>
        <div className={styles.controls}>
          <button type="button" className={styles.secondary} onClick={() => onFilters({ player: null, metric: null })}>
            ‹ Todo el plantel
          </button>
          <strong>{p.name}</strong>
          <span className={styles.muted}>
            {p.measurements.length} mediciones · última {longDate(p.last.date)}
            {p.last.talla != null && ` · ${num(p.last.talla, 1)} cm`}
          </span>
        </div>

        <section className={styles.card} aria-labelledby="co-last">
          <div className={styles.cardHead}>
            <h2 id="co-last" className={styles.h2}>Última evaluación</h2>
          </div>
          <div className={styles.tableWrap}>
            <table className={`${styles.table} ${styles.gridTable}`}>
              <thead>
                <tr>
                  <th scope="col">Métrica</th>
                  <th scope="col">Último</th>
                  <th scope="col">vs anterior{p.prev && <span className={styles.muted}> ({longDate(p.prev.date)})</span>}</th>
                  <th scope="col">vs primera{p.measurements.length > 1 && <span className={styles.muted}> ({longDate(p.first.date)})</span>}</th>
                  <th scope="col">Promedio del plantel</th>
                </tr>
              </thead>
              <tbody>
                {data.metrics.map((m) => (
                  <tr key={m.key}>
                    <th scope="row">{metricLabel(m)}</th>
                    <td className={styles.num}><strong>{num(p.last[m.key], m.decimals)}</strong></td>
                    <td><Delta d={p.delta[m.key]} m={m} /></td>
                    <td><Delta d={p.delta_first[m.key]} m={m} /></td>
                    <td className={styles.num}>{num(data.mean[m.key], m.decimals)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={styles.provenance}>
            Verde = favorable (más músculo, menos grasa y pliegues); rojo = desfavorable. El peso va en gris porque
            depende de qué cambió.
          </p>
        </section>

        <section className={styles.card} aria-labelledby="co-trend">
          <div className={styles.cardHead}>
            <h2 id="co-trend" className={styles.h2}>{metricLabel(sel)} en el tiempo</h2>
          </div>
          <div className={styles.segmented} style={{ flexWrap: "wrap" }} role="group" aria-label="Métrica">
            {data.metrics.map((m) => (
              <button key={m.key} type="button" aria-pressed={m.key === sel.key}
                onClick={() => onFilters({ metric: m.key })}>
                {metricLabel(m)}
              </button>
            ))}
          </div>
          {series.filter((s) => s.v != null).length < 2 ? (
            <p className={styles.muted}>Se necesitan al menos dos mediciones para ver la evolución.</p>
          ) : (
            <div className={styles.chartBox} role="img" aria-label={`${metricLabel(sel)} de ${p.name} en cada medición.`}>
              <ResponsiveContainer>
                <LineChart data={series} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#eaecf0" />
                  <XAxis dataKey="tick" tick={{ fontSize: 11, fill: INK }} />
                  <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11, fill: INK }} />
                  <Tooltip formatter={(v) => [num(v, sel.decimals), metricLabel(sel)]} />
                  {groupMean != null && (
                    <ReferenceLine y={groupMean} stroke="#98a2b3" strokeDasharray="5 4"
                      label={{ value: "promedio plantel", position: "insideTopRight", fontSize: 11, fill: INK }} />
                  )}
                  <Line dataKey="v" name={metricLabel(sel)} stroke="#2a78d6" strokeWidth={2} dot={{ r: 4 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className={styles.card} aria-labelledby="co-all">
          <div className={styles.cardHead}>
            <h2 id="co-all" className={styles.h2}>Todas las mediciones</h2>
            <span className={styles.muted}>{p.measurements.length}</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={`${styles.table} ${styles.gridTable}`}>
              <thead>
                <tr>
                  <th scope="col">Fecha</th><th scope="col">Talla cm</th>
                  {data.metrics.map((m) => <th key={m.key} scope="col">{metricLabel(m)}</th>)}
                </tr>
              </thead>
              <tbody>
                {[...p.measurements].reverse().map((x) => (
                  <tr key={x.date}>
                    <th scope="row">{longDate(x.date)}</th>
                    <td className={styles.num}>{num(x.talla, 1)}</td>
                    {data.metrics.map((m) => <td key={m.key} className={styles.num}>{num(x[m.key], m.decimals)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <Footer />
      </>
    );
  }

  return (
    <>
      <section className={styles.card} aria-labelledby="co-squad">
        <div className={styles.cardHead}>
          <h2 id="co-squad" className={styles.h2}>Composición corporal del plantel</h2>
          <span className={styles.muted}>{data.rows.length} jugadores con mediciones</span>
        </div>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.gridTable}`}>
            <thead>
              <tr>
                {head("name", "Jugador")}
                {head("date", "Última medición")}
                {data.squad_keys.map((k) => <React.Fragment key={k}>{head(k, metricLabel(byKey[k]))}</React.Fragment>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.player_id}>
                  <th scope="row">
                    <button type="button" className={styles.linkButton} onClick={() => onFilters({ player: r.player_id })}>{r.name}</button>
                  </th>
                  <td>{longDate(r.last.date)}</td>
                  {data.squad_keys.map((k) => (
                    <td key={k}>
                      <div className={styles.num}><strong>{num(r.last[k], byKey[k].decimals)}</strong></div>
                      <Delta d={r.delta[k]} m={byKey[k]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Promedio del plantel</th>
                <td />
                {data.squad_keys.map((k) => <td key={k} className={styles.num}>{num(data.mean[k], byKey[k].decimals)}</td>)}
              </tr>
            </tfoot>
          </table>
        </div>
        <p className={styles.provenance}>
          Bajo cada valor, el cambio contra su medición anterior. Verde = favorable (más músculo, menos grasa y pliegues),
          rojo = desfavorable; el peso va en gris. Toca un jugador para ver su evolución; toca un encabezado para ordenar.
        </p>
      </section>
      <Footer />
    </>
  );
}

function Footer() {
  return (
    <p className={styles.provenance}>
      Datos usados: evaluación antropométrica pentacompartimental de Nutrición (MM = masa muscular, MA = masa adiposa,
      IMO = índice músculo/óseo, Σ 6 pliegues en mm). Promedio del plantel = media de la última medición de cada jugador.
    </p>
  );
}
