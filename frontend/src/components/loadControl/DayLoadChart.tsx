"use client";

/**
 * "Ejecutado vs planificado" of ONE day, per player, for one metric: Δ% of
 * real against the day's target, sorted from the most over (+x %) to the
 * most under (−x %) — who is over-trained and who under-trained that day.
 * Data: the Carga GPS evaluation of the day (`load_control.evaluation`).
 *
 * Diverging encoding: orange = over the plan, blue = under, grey = within
 * the club's "en objetivo" band (±band_ok_pct). Every bar carries its value.
 */

import React, { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/lib/api";
import { type Evaluation, signedPct } from "@/lib/loadControl";

import { usePlayerPhoto } from "./PlayerPhotos";
import styles from "./loadControl.module.css";

const OVER = "#eb6834";
const UNDER = "#2a78d6";
const IN_BAND = "#98a2b3";
const INK = "#475467";

const AV = 18;

/** Y-axis label: the player's photo (if any) left of his name. */
function PhotoTick({ x = 0, y = 0, payload, names }: { x?: number; y?: number; payload?: { value: string }; names: Record<string, string> }) {
  const id = payload?.value ?? "";
  const photo = usePlayerPhoto(id);
  const clip = `av-${id}`;
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={photo ? -AV - 6 : 0} dy={4} textAnchor="end" fontSize={12} fill={INK}>{names[id] ?? ""}</text>
      {photo && (
        <>
          <clipPath id={clip}><circle cx={-AV / 2 - 2} cy={0} r={AV / 2} /></clipPath>
          <image href={photo} x={-AV - 2} y={-AV / 2} width={AV} height={AV} clipPath={`url(#${clip})`}
            preserveAspectRatio="xMidYMid slice" />
        </>
      )}
    </g>
  );
}

interface Props {
  microcycleId: string;
  day: string;
  metric: string | null;
  onMetric: (key: string) => void;
}

export default function DayLoadChart({ microcycleId, day, metric, onMetric }: Props) {
  const [data, setData] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Evaluation>(`/load-control/microcycles/${microcycleId}/evaluation?day=${day}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la carga del día."); });
    return () => { cancelled = true; };
  }, [microcycleId, day]);

  const head = (
    <div className={styles.cardHead}>
      <h2 className={styles.h2}>Ejecutado vs planificado del día</h2>
    </div>
  );
  if (error) return <section className={styles.card}>{head}<div className={styles.error} role="alert">{error}</div></section>;
  if (!data) return <section className={styles.card}>{head}<p className={styles.muted}>Cargando…</p></section>;

  const m = data.metrics.find((x) => x.key === metric) ?? data.metrics[0];
  const ok = data.bands.ok;
  const bars = data.players
    .map((p) => ({ id: p.player_id, name: p.name, pct: p.cells[m.key]?.pct ?? null, real: p.cells[m.key]?.real, target: p.cells[m.key]?.target }))
    .filter((b): b is { id: string; name: string; pct: number; real: number | null; target: number | null } => b.pct != null)
    .sort((a, b) => b.pct - a.pct);
  const planned = data.provenance.planned !== false;
  const isMatch = data.days[0]?.kind === "official" || data.days[0]?.kind === "friendly";

  return (
    <section className={styles.card} aria-labelledby="dl-title">
      <div className={styles.cardHead}>
        <h2 id="dl-title" className={styles.h2}>Ejecutado vs planificado del día</h2>
        <span className={styles.muted}>{data.days[0]?.md_label || ""} · {bars.length} jugadores</span>
      </div>
      <div className={styles.segmented} style={{ flexWrap: "wrap" }} role="group" aria-label="Métrica">
        {data.metrics.map((x) => (
          <button key={x.key} type="button" aria-pressed={x.key === m.key} onClick={() => onMetric(x.key)}>
            {x.short || x.label}
          </button>
        ))}
      </div>
      {!planned ? (
        <p className={styles.muted}>Esta semana no está planificada: sin objetivo del día no hay con qué comparar.</p>
      ) : bars.length === 0 ? (
        <p className={styles.muted}>
          {data.days[0]?.kind === "rest" ? "Día de descanso." : isMatch ? "Día de partido sin GPS contra objetivo." : "Nadie tiene GPS y objetivo este día."}
        </p>
      ) : (
        <div style={{ width: "100%", height: bars.length * 28 + 40 }} role="img"
          aria-label={`${m.label}: porcentaje sobre o bajo lo planificado por jugador, del más sobre al más bajo.`}>
          <ResponsiveContainer>
            <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 56, left: 8, bottom: 4 }} barCategoryGap={4}>
              <CartesianGrid horizontal={false} stroke="#eaecf0" />
              <XAxis type="number" tick={{ fontSize: 11, fill: INK }} tickFormatter={(v) => `${v}%`}
                domain={[(min: number) => Math.min(-ok * 2, Math.floor(min / 10) * 10), (max: number) => Math.max(ok * 2, Math.ceil(max / 10) * 10)]} />
              <YAxis type="category" dataKey="id" width={174} interval={0}
                tick={<PhotoTick names={Object.fromEntries(bars.map((b) => [b.id, b.name]))} />} />
              <ReferenceLine x={0} stroke="#475467" />
              <ReferenceLine x={ok} stroke="#d0d5dd" strokeDasharray="3 3" />
              <ReferenceLine x={-ok} stroke="#d0d5dd" strokeDasharray="3 3" />
              <Tooltip cursor={{ fill: "#f2f4f7" }}
                labelFormatter={(id) => bars.find((b) => b.id === id)?.name ?? ""}
                formatter={(v, _n, item) => {
                  const p = item.payload as { real: number | null; target: number | null };
                  return [`${signedPct(typeof v === "number" ? v : null)} · real ${p.real ?? "—"} / objetivo ${p.target ?? "—"}${m.unit ? ` ${m.unit}` : ""}`, m.label];
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
  );
}
