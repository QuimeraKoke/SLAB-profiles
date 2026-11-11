"use client";

/**
 * "Ejecutado vs planificado", per player, for one metric: Δ% of real against
 * the target, sorted from the most over (+x %) to the most under (−x %) — who
 * is over-trained and who under-trained.
 *
 *   Diario   ONE day: that day's GPS against that day's target.
 *   Semanal  the week so far (`load_control.evaluation`, accumulated): each
 *            player's GPS summed over the days he has GPS, against the sum of
 *            his targets on THOSE days — a missed session is "3 de 5 días",
 *            never "−40 %".
 *
 * Diverging encoding: orange = over the plan, blue = under, grey = within
 * the club's "en objetivo" band (±band_ok_pct). Every bar carries its value.
 */

import React, { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/lib/api";
import { type Evaluation, shortDate, signedPct } from "@/lib/loadControl";

import styles from "./loadControl.module.css";

const OVER = "#eb6834";
const UNDER = "#2a78d6";
const IN_BAND = "#98a2b3";
const INK = "#475467";

/** Y-axis label: the player's name (no photo: the staff asked to keep this chart clean). */
function NameTick({ x = 0, y = 0, payload, names }: { x?: number; y?: number; payload?: { value: string }; names: Record<string, string> }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} dy={4} textAnchor="end" fontSize={12} fill={INK}>{names[payload?.value ?? ""] ?? ""}</text>
    </g>
  );
}

export type LoadView = "day" | "week";

interface Props {
  microcycleId: string;
  day: string;
  view: LoadView;
  onView: (view: LoadView) => void;
  metric: string | null;
  onMetric: (key: string) => void;
}

export default function DayLoadChart({ microcycleId, day, view, onView, metric, onMetric }: Props) {
  const [data, setData] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const qs = view === "day" ? `?day=${day}` : "";
    api<Evaluation>(`/load-control/microcycles/${microcycleId}/evaluation${qs}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la carga."); });
    return () => { cancelled = true; };
  }, [microcycleId, day, view]);

  const weekly = view === "week";
  const title = weekly ? "Ejecutado vs planificado de la semana" : "Ejecutado vs planificado del día";
  const toggle = (
    <div className={styles.controls}>
      <div role="group" aria-label="Vista de la carga" className={styles.segmented}>
        <button type="button" aria-pressed={!weekly} onClick={() => onView("day")}>Diario</button>
        <button type="button" aria-pressed={weekly} onClick={() => onView("week")}>Semanal</button>
      </div>
      {weekly && data?.mode === "accumulated" && (
        <span className={styles.muted}>
          {data.days.length > 0
            ? `Acumulado de ${data.days.length} día${data.days.length === 1 ? "" : "s"} con carga planificada (${shortDate(data.days[0].date)} – ${shortDate(data.days[data.days.length - 1].date)})`
            : "La semana todavía no tiene días con carga"}
        </span>
      )}
    </div>
  );
  const head = (
    <div className={styles.cardHead}>
      <h2 className={styles.h2}>{title}</h2>
    </div>
  );
  if (error) return <>{toggle}<section className={styles.card}>{head}<div className={styles.error} role="alert">{error}</div></section></>;
  if (!data) return <>{toggle}<section className={styles.card}>{head}<p className={styles.muted}>Cargando…</p></section></>;

  const m = data.metrics.find((x) => x.key === metric) ?? data.metrics[0];
  const ok = data.bands.ok;
  const bars = data.players
    .map((p) => ({ id: p.player_id, name: p.name, pct: p.cells[m.key]?.pct ?? null, real: p.cells[m.key]?.real, target: p.cells[m.key]?.target, days: p.days, planned: p.days_planned }))
    .filter((b): b is { id: string; name: string; pct: number; real: number | null; target: number | null; days: number; planned: number } => b.pct != null)
    .sort((a, b) => b.pct - a.pct);
  // Symmetric axis (0 in the middle: over vs under reads at a glance), with
  // room past the longest bar for its label; steps of 20 so ticks stay round.
  const lim = Math.max(ok * 2, Math.ceil((Math.max(0, ...bars.map((b) => Math.abs(b.pct))) + 8) / 20) * 20);
  const planned = data.provenance.planned !== false;
  const isMatch = data.days[0]?.kind === "official" || data.days[0]?.kind === "friendly";

  return (
    <>
    {toggle}
    <section className={styles.card} aria-labelledby="dl-title">
      <div className={styles.cardHead}>
        <h2 id="dl-title" className={styles.h2}>{title}</h2>
        <span className={styles.muted}>
          {weekly ? `Semana ${data.provenance.microcycle}` : data.days[0]?.md_label || ""} · {bars.length} jugadores
        </span>
      </div>
      <div className={styles.segmented} style={{ flexWrap: "wrap" }} role="group" aria-label="Métrica">
        {data.metrics.map((x) => (
          <button key={x.key} type="button" aria-pressed={x.key === m.key} onClick={() => onMetric(x.key)}>
            {x.short || x.label}
          </button>
        ))}
      </div>
      {!planned ? (
        <p className={styles.muted}>
          Esta semana no está planificada: sin objetivo {weekly ? "semanal" : "del día"} no hay con qué comparar.
        </p>
      ) : bars.length === 0 ? (
        <p className={styles.muted}>
          {weekly
            ? data.days.length === 0 ? "La semana todavía no empieza." : "Nadie tiene GPS y objetivo en lo que va de la semana."
            : data.days[0]?.kind === "rest" ? "Día de descanso." : isMatch ? "Día de partido sin GPS contra objetivo." : "Nadie tiene GPS y objetivo este día."}
        </p>
      ) : (
        <div style={{ width: "100%", height: bars.length * 28 + 40 }} role="img"
          aria-label={`${m.label}: porcentaje sobre o bajo lo planificado ${weekly ? "en la semana" : "del día"} por jugador, del más sobre al más bajo.`}>
          <ResponsiveContainer>
            <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 56, left: 8, bottom: 4 }} barCategoryGap={4}>
              <CartesianGrid horizontal={false} stroke="#eaecf0" />
              <XAxis type="number" tick={{ fontSize: 11, fill: INK }} tickFormatter={(v) => `${v}%`}
                domain={[-lim, lim]} ticks={[-lim, -lim / 2, 0, lim / 2, lim]} allowDataOverflow={false} />
              <YAxis type="category" dataKey="id" width={150} interval={0}
                tick={<NameTick names={Object.fromEntries(bars.map((b) => [b.id, b.name]))} />} />
              <ReferenceLine x={0} stroke="#475467" />
              <ReferenceLine x={ok} stroke="#d0d5dd" strokeDasharray="3 3" />
              <ReferenceLine x={-ok} stroke="#d0d5dd" strokeDasharray="3 3" />
              <Tooltip cursor={{ fill: "#f2f4f7" }}
                labelFormatter={(id) => bars.find((b) => b.id === id)?.name ?? ""}
                formatter={(v, _n, item) => {
                  const p = item.payload as { real: number | null; target: number | null; days: number; planned: number };
                  const span = weekly ? ` · ${p.days} de ${p.planned} días` : "";
                  return [`${signedPct(typeof v === "number" ? v : null)} · real ${p.real ?? "—"} / objetivo ${p.target ?? "—"}${m.unit ? ` ${m.unit}` : ""}${span}`, m.label];
                }} />
              <Bar dataKey="pct" radius={4} isAnimationActive={false}>
                {bars.map((b) => <Cell key={b.id} fill={Math.abs(b.pct) <= ok ? IN_BAND : b.pct > 0 ? OVER : UNDER} />)}
                <LabelList dataKey="pct" position="right" formatter={(v) => signedPct(typeof v === "number" ? v : null)}
                  style={{ fontSize: 11, fill: "#101828" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className={styles.legend}>
        <span><span aria-hidden="true" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: OVER, marginRight: 4 }} />Sobre lo planificado</span>
        <span><span aria-hidden="true" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: IN_BAND, marginRight: 4 }} />En objetivo (±{ok} %)</span>
        <span><span aria-hidden="true" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: UNDER, marginRight: 4 }} />Bajo lo planificado</span>
      </div>
    </section>
    </>
  );
}
