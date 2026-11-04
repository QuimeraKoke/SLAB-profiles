"use client";

/**
 * Fatiga post-partido — what the coach plans the player's week with: how hard
 * the last match hit him and how he arrives at the next one. Three jumps in a
 * row: PRE (MD-1) → POST (MD+1) → next match's PRE (MD-1).
 *
 * Two states (the staff, 2026-11-03):
 *  · Fatiga — only PRE and POST exist yet (the next MD-1 is not measured):
 *    the match's hit, POST vs PRE.
 *  · Recuperación de la fatiga — the next PRE exists: did he get back to where
 *    he was before the match?
 * Both painted with the club's own traffic light (`rsi_alert`).
 */

import Link from "next/link";
import React, { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/lib/api";
import { type Band, type FatigueMatch, type FatiguePayload, type FatigueRow, shortDate, signedPct } from "@/lib/loadControl";

import styles from "./loadControl.module.css";

const BAND_FILL: Record<Band, string> = { ok: "#16a34a", leve: "#d97706", grave: "#dc2626" };
const INK = "#475467";
const GOLPE_LABEL: Record<Band, string> = { grave: "Fuerte", leve: "Moderado", ok: "Sin golpe" };
const LLEGA_LABEL: Record<Band, string> = { grave: "No recuperado", leve: "Parcial", ok: "Recuperado" };

interface Props {
  microcycleId: string;
  matchDate: string | null;
  playerId: string | null;
  onFilters: (f: { match?: string | null; player?: string | null }) => void;
}

const rsi = (v: number | null) => (v == null ? "—" : v.toFixed(2).replace(".", ","));
const matchName = (m: FatigueMatch) => `${m.rival ?? "partido"} · ${shortDate(m.date)}`;

/** His last matches as a sawtooth in real RSI: PRE (gray) → POST (club colour)
 *  per match, then the next MD-1 when measured; dashed line = his basal. */
function Sawtooth({ r, recovery }: { r: FatigueRow; recovery: boolean }) {
  type P = { v: number; fill: string; gap: boolean };
  const pts: P[] = [];
  r.recent.forEach((m, k) => {
    if (m.pre != null) pts.push({ v: m.pre, fill: "#667085", gap: k > 0 });
    if (m.post != null) pts.push({ v: m.post, fill: m.golpe_band ? BAND_FILL[m.golpe_band] : "#667085", gap: m.pre == null });
  });
  if (recovery && r.next_pre != null)
    pts.push({ v: r.next_pre, fill: r.llega_band ? BAND_FILL[r.llega_band] : "#667085", gap: false });
  if (pts.length < 2) return <span className={styles.muted}>—</span>;
  const vals = [...pts.map((p) => p.v), ...(r.basal != null ? [r.basal] : [])];
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const W = 150, H = 36, step = (W - 12) / Math.max(pts.length - 1, 1);
  const x = (k: number) => 6 + k * step;
  const y = (v: number) => 5 + ((hi - v) / span) * (H - 10);
  return (
    <svg width={W} height={H} aria-hidden="true" style={{ display: "block" }}>
      {r.basal != null && <line x1={0} x2={W} y1={y(r.basal)} y2={y(r.basal)} stroke="#d0d5dd" strokeDasharray="3 3" />}
      <polyline points={pts.map((p, k) => `${x(k)},${y(p.v)}`).join(" ")} fill="none" stroke="#98a2b3" strokeWidth={1.5} />
      {pts.map((p, k) => (
        <circle key={k} cx={x(k)} cy={y(p.v)} r={3.5} fill={p.fill} stroke="#fff" strokeWidth={1.5} />
      ))}
    </svg>
  );
}

/** What to do with him this week, from the club's own traffic light: the
 *  latest jump decides (the next MD-1 when measured, else the match's hit);
 *  arriving low vs his basal and a sinking season basal are added as reasons.
 *  No invented thresholds — the same `rsi_alert` bands as the sheets. */
function suggestion(r: FatigueRow, recovery: boolean, graveAt: number): { band?: Band | null; label: string; why: string[] } {
  const why: string[] = [];
  const band = recovery ? r.llega_band : r.golpe_band;
  if (r.pre_vs_basal != null && r.pre_vs_basal <= graveAt) why.push(`llegó bajo al partido (${signedPct(r.pre_vs_basal)} vs basal)`);
  if (r.season_drift_band && r.season_drift_band !== "ok") why.push(`basal ${signedPct(r.season_drift_pct)} en la temporada`);
  if (band == null) {
    if (recovery && r.llega_state === "missing") return { band: null, label: "Medir", why: ["no saltó el MD-1", ...why] };
    return { band: null, label: "Sin dato", why: ["no tiene POST", ...why] };
  }
  const base = band === "grave" ? "Cuidar" : band === "leve" ? "Vigilar" : "Normal";
  const reason = recovery
    ? (band === "grave" ? "no recuperó su salto" : band === "leve" ? "recuperación parcial" : "volvió a su nivel")
    : (band === "grave" ? "golpe fuerte: bajar carga al inicio de la semana" : band === "leve" ? "golpe moderado" : "");
  // A sinking season basal turns "Normal" into "Vigilar": fatigue piling up.
  const finalBand: Band = band === "ok" && r.season_drift_band === "grave" ? "leve" : band;
  return { band: finalBand, label: finalBand === band ? base : "Vigilar", why: [reason, ...why].filter(Boolean) };
}

export default function FatigueView({ microcycleId, matchDate, playerId, onFilters }: Props) {
  const [data, setData] = useState<FatiguePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const sp = new URLSearchParams();
    if (matchDate) sp.set("match_date", matchDate);
    if (playerId) sp.set("player_id", playerId);
    api<FatiguePayload>(`/load-control/microcycles/${microcycleId}/fatigue?${sp}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la fatiga."); });
    return () => { cancelled = true; };
  }, [microcycleId, matchDate, playerId]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <p className={styles.muted}>Cargando…</p>;
  if (!data.match) return <div className={styles.empty}>Aún no hay saltos de partidos de este equipo en la temporada.</div>;

  const m = data.match;
  const next = data.next_match;
  const recovery = next != null;          // state 2: the next MD-1 is measured
  const alert = data.params.rsi_alert;
  const c = data.summary.counts;
  const missing = data.rows.filter((r) => r.llega_state === "missing").length;
  const pill = (b: Band | null, text: string) =>
    <span className={`${styles.statusPill} ${styles[`band_${b ?? "none"}`]}`}>{text}</span>;

  const stats: { band: Band | null; label: string; n: number }[] = recovery
    ? [{ band: "grave", label: "No recuperados", n: c.llega.grave },
       { band: "leve", label: "Recuperación parcial", n: c.llega.leve },
       { band: "ok", label: "Recuperados", n: c.llega.ok },
       { band: null, label: "No saltaron el MD-1", n: missing }]
    : [{ band: "grave", label: "Golpe fuerte", n: c.golpe.grave },
       { band: "leve", label: "Golpe moderado", n: c.golpe.leve },
       { band: "ok", label: "Sin golpe", n: c.golpe.ok },
       { band: null, label: "Sin salto POST", n: data.summary.players - data.summary.golpe_n }];

  return (
    <>
      <div className={styles.controls}>
        <button type="button" className={styles.secondary} disabled={!data.prev_match}
          onClick={() => data.prev_match && onFilters({ match: data.prev_match.date, player: null })}
          aria-label={data.prev_match ? `Partido anterior: ${matchName(data.prev_match)}` : "No hay partido anterior"}>
          ‹ Partido anterior
        </button>
        <span>
          <strong>vs {m.rival ?? "—"}</strong> · {shortDate(m.date)}
          {m.event_id && <> · <Link href={`/partidos/${m.event_id}`}>ver partido</Link></>}
        </span>
        <button type="button" className={styles.secondary} disabled={!next}
          onClick={() => next && onFilters({ match: next.date, player: null })}
          aria-label={next ? `Partido siguiente: ${matchName(next)}` : "No hay partido siguiente medido"}>
          Partido siguiente ›
        </button>
      </div>
      {m.source === "propuesta" && (
        <p className={styles.provenance}>
          <strong className={styles.overdue}>Fecha propuesta</strong>: la pestaña {m.tab} de la planilla aún no está
          confirmada por el club como este partido.
        </p>
      )}

      <section className={styles.card} aria-labelledby="fa-main">
        <div className={styles.cardHead}>
          <h2 id="fa-main" className={styles.h2}>
            {recovery ? `Recuperación: cómo llegan al partido vs ${next.rival ?? "—"} (${shortDate(next.date)})`
              : "Fatiga: cuánto les pegó el partido"}
          </h2>
          <span className={styles.muted}>
            {recovery ? "PRE → POST → MD-1 del partido siguiente" : "PRE (MD-1) → POST (MD+1) · el MD-1 del próximo partido aún no se mide"}
          </span>
        </div>

        <div className={styles.summaryGrid}>
          {stats.map((s) => (
            <div key={s.label} className={`${styles.stat} ${styles[`band_${s.band ?? "none"}`]}`}>
              <span className={styles.statName}>{s.label}</span>
              <span className={styles.statPair}>{s.n}</span>
            </div>
          ))}
        </div>

        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.gridTable}`}>
            <thead>
              <tr>
                <th scope="col" rowSpan={2}>Jugador</th>
                <th scope="col" rowSpan={2} title={`Promedio de sus últimos ${data.params.baseline_n} saltos PRE antes del partido`}>Basal</th>
                <th scope="colgroup" colSpan={4} className={`${styles.groupHead} ${styles.groupStart}`}>Último partido</th>
                {recovery && <th scope="colgroup" colSpan={2} className={`${styles.groupHead} ${styles.groupStart}`}>Recuperación</th>}
                <th scope="col" rowSpan={2} className={styles.groupStart} title="Gris = PRE (MD-1); color = POST (MD+1) con el semáforo del golpe; último punto = MD-1 siguiente; punteada = su basal">Tendencia</th>
                <th scope="col" rowSpan={2}>Sugerencia</th>
              </tr>
              <tr>
                <th scope="col" className={styles.groupStart}>Min</th><th scope="col">PRE</th><th scope="col">POST</th><th scope="col">Golpe</th>
                {recovery && <><th scope="col" className={styles.groupStart}>Nuevo PRE</th><th scope="col">Estado</th></>}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => {
                const sug = suggestion(r, recovery, alert.grave_at);
                return (
                  <tr key={r.player_id}>
                    <th scope="row">
                      <button type="button" className={styles.linkButton} onClick={() => onFilters({ player: r.player_id })}>{r.name}</button>
                    </th>
                    <td className={styles.num}>{rsi(r.basal)}</td>
                    <td className={`${styles.num} ${styles.groupStart}`}>{r.minutes == null ? "—" : `${r.minutes}'`}</td>
                    <td className={styles.num}>{rsi(r.pre)}</td>
                    <td className={styles.num}>{rsi(r.post)}</td>
                    <td>{r.golpe_band ? pill(r.golpe_band, `${GOLPE_LABEL[r.golpe_band]} ${signedPct(r.golpe_pct)}`) : <span className={styles.muted}>—</span>}</td>
                    {recovery && (
                      <>
                        <td className={`${styles.num} ${styles.groupStart}`}>{rsi(r.next_pre)}</td>
                        <td>{r.llega_band ? pill(r.llega_band, `${LLEGA_LABEL[r.llega_band]} ${signedPct(r.llega_pct)}`)
                          : <span className={styles.muted}>No saltó</span>}</td>
                      </>
                    )}
                    <td className={styles.groupStart} title={r.recent.map((m) => `${shortDate(m.date)}: ${rsi(m.pre)} → ${rsi(m.post)}`).join("\n")}>
                      <Sawtooth r={r} recovery={recovery} />
                    </td>
                    <td>
                      {sug.band !== undefined && pill(sug.band, sug.label)}
                      {sug.why.length > 0 && <div className={styles.muted} style={{ fontSize: "0.75rem", marginTop: 2 }}>{sug.why.join(" · ")}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className={styles.legend}>
          <span>{pill("ok", "Verde")} {alert.ok_from}% o más</span>
          <span>{pill("leve", "Amarillo")} entre {alert.ok_from}% y {alert.grave_at}%</span>
          <span>{pill("grave", "Rojo")} {alert.grave_at}% o menos</span>
          <span>
            {recovery ? "Golpe = POST vs PRE · Recuperación = MD-1 siguiente vs PRE (¿volvió a su nivel previo al partido?) · Últimos partidos: gris = PRE, color = POST, punteada = su basal"
              : "Golpe = POST vs PRE del partido · Últimos partidos: gris = PRE, color = POST, punteada = su basal"}
          </span>
        </div>
      </section>

      {data.trend && (
        <section className={styles.card} aria-labelledby="fa-trend">
          <div className={styles.cardHead}>
            <h2 id="fa-trend" className={styles.h2}>Temporada de {data.trend.name}</h2>
            <button type="button" className={styles.secondary} onClick={() => onFilters({ player: null })}>Cerrar</button>
          </div>
          <div className={styles.chartBox} role="img" aria-label={`RSI PRE, POST y basal de ${data.trend.name} a lo largo de la temporada.`}>
            <ResponsiveContainer>
              <LineChart data={data.trend.points.map((p) => ({ ...p, tick: shortDate(p.date) }))}
                margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#eaecf0" />
                <XAxis dataKey="tick" tick={{ fontSize: 11, fill: INK }} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11, fill: INK }} />
                <Tooltip formatter={(v, n) => [typeof v === "number" ? v.toFixed(2).replace(".", ",") : "—", n]} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="pre" name="PRE (MD-1)" stroke="#2a78d6" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line dataKey="post" name="POST (MD+1)" stroke="#eb6834" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line dataKey="basal" name={`Basal (últimos ${data.params.baseline_n} PRE)`} stroke="#475467" strokeWidth={2}
                  strokeDasharray="5 4" dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className={styles.provenance}>Método: {data.trend.method}. Sólo saltos del mismo método (R-CMJ y CMJ no se comparan).</p>
        </section>
      )}

      <p className={styles.provenance}>
        Datos usados: planillas de control de salto del club (mejor de 2 intentos; RSI = altura del rebote ÷ tiempo de
        contacto en R-CMJ, RSI mod en CMJ). Minutos de la ficha COMET o, si no hay, del GPS del partido. Basal = promedio
        de sus últimos {data.params.baseline_n} saltos PRE. Toca un nombre para ver su temporada.
      </p>
    </>
  );
}
