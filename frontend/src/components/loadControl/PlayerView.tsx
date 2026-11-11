"use client";

/**
 * Jugador — "¿Cómo viene esta persona en todo?" (question 7): one player in
 * the selected week, every panel at once, each section folded/unfolded and
 * linked to its tab. Every number comes from the tab's own service (see
 * `load_control/player_card.py`), so his card and the squad view agree.
 */

import React, { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/lib/api";
import { deltaTone, deltaToneTitle } from "@/lib/deltaTone";
import {
  type Band, type PlayerCard, scoreBand, shortDate, signedPct,
} from "@/lib/loadControl";

import styles from "./loadControl.module.css";
import { usePeriod } from "@/lib/periodWording";
import ScopeBadge from "./ScopeBadge";

const INK = "#475467";
const STATUS_LABEL: Record<string, string> = {
  injured: "Lesionado", recovery: "Recuperación", reintegration: "Return to Train", available: "Disponible",
};
const WEEKDAY = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

interface Props {
  microcycleId: string;
  playerId: string | null;
  onPlayer: (id: string | null) => void;
  onTab: (tab: string) => void;
}

const n1 = (v: number | null | undefined, dec = 0) =>
  v == null ? "—" : v.toLocaleString("es-CL", { maximumFractionDigits: dec, minimumFractionDigits: dec });
const rsi = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2).replace(".", ","));
const dayName = (iso: string) => `${WEEKDAY[new Date(`${iso}T12:00:00`).getDay()]} ${shortDate(iso)}`;

export default function PlayerView({ microcycleId, playerId, onPlayer, onTab }: Props) {
  const per = usePeriod();
  const [roster, setRoster] = useState<{ player_id: string; name: string }[] | null>(null);
  const [card, setCard] = useState<PlayerCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ player_id: string; name: string }[]>(`/load-control/microcycles/${microcycleId}/players`)
      .then((r) => { if (!cancelled) setRoster(r); })
      .catch(() => { if (!cancelled) setRoster([]); });
    return () => { cancelled = true; };
  }, [microcycleId]);

  useEffect(() => {
    if (!playerId) return;
    let cancelled = false;
    api<PlayerCard>(`/load-control/microcycles/${microcycleId}/players/${playerId}`)
      .then((c) => { if (!cancelled) { setCard(c); setError(null); } })
      .catch((e) => { if (!cancelled) { setCard(null); setError(e instanceof ApiError ? e.message : "No se pudo cargar el jugador."); } });
    return () => { cancelled = true; };
  }, [microcycleId, playerId]);

  const pill = (b: Band | null | undefined, text: string) =>
    <span className={`${styles.statusPill} ${styles[`band_${b ?? "none"}`]}`}>{text}</span>;
  const toTab = (tab: string, label: string) => (
    <button type="button" className={styles.linkButton} onClick={() => onTab(tab)}>Ver {label} del plantel</button>
  );

  const picker = (
    <div className={styles.controls}>
      <label className={styles.label}>
        Jugador
        <select className={styles.select} value={playerId ?? ""} onChange={(e) => onPlayer(e.target.value || null)}>
          <option value="">Elige un jugador…</option>
          {(roster ?? []).map((r) => <option key={r.player_id} value={r.player_id}>{r.name}</option>)}
        </select>
      </label>
    </div>
  );

  if (!playerId) return <>{picker}<div className={styles.empty}>Elige un jugador para ver cómo viene en todo.</div></>;
  if (error) return <>{picker}<div className={styles.error} role="alert">{error}</div></>;
  if (!card || card.player.player_id !== playerId) return <>{picker}<p className={styles.muted}>Cargando…</p></>;

  const { player: p, load, wellness: wl, fatigue: fa, minutes: mi, status: st, evaluations: ev, composition: co } = card;
  const fr = fa.row;
  const wk = mi.week, se = mi.season;

  return (
    <>
      {picker}

      {/* Cabecera */}
      <section className={styles.card} aria-label={`Ficha de ${p.name}`}>
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
          {p.photo_url
            // eslint-disable-next-line @next/next/no-img-element
            ? <img src={p.photo_url} alt="" width={96} height={96} style={{ borderRadius: 16, objectFit: "cover", objectPosition: "center top" }} />
            : <div aria-hidden="true" style={{ width: 72, height: 72, borderRadius: 12, background: "#f2f4f7" }} />}
          <div style={{ flex: 1, minWidth: 200 }}>
            <h2 className={styles.h2} style={{ margin: 0 }}>{p.name} <ScopeBadge kind="period" /></h2>
            <div className={styles.muted}>
              {[p.position, p.category, p.age != null ? `${p.age} años` : null].filter(Boolean).join(" · ")}
            </div>
          </div>
          <span className={`${styles.statusPill} ${styles[`status_${p.status}`]}`}>{STATUS_LABEL[p.status] ?? p.status}</span>
        </div>
        <div className={styles.summaryGrid}>
          {[
            [`Minutos ${per.this}`, `${n1(wk.minutes)}'`, wk.matches.length ? `${wk.matches.length} partido(s)` : "sin partidos"],
            [`Entrenamientos ${per.this}`, `${n1(wk.sessions_attended ?? 0)} de ${wk.sessions}`, wk.sessions_form_only ? `${wk.sessions_form_only} sólo con formulario` : ""],
            ["Minutos en la temporada", `${n1(se.minutes)}'`, `${se.match_count} partidos del equipo`],
            ["Entrenamientos en la temporada", `${n1(se.sessions_attended ?? 0)} de ${se.sessions}`, se.attendance_pct != null ? `${se.attendance_pct}%` : ""],
          ].map(([label, value, sub]) => (
            <div key={label} className={`${styles.stat} ${styles.band_none}`}>
              <span className={styles.statName}>{label}</span>
              <span className={styles.statPair}>{value}</span>
              {sub && <span className={styles.statCounts}>{sub}</span>}
            </div>
          ))}
        </div>
      </section>

      {/* Carga GPS */}
      <details open className={styles.card}>
        <summary className={styles.h2}>Carga GPS {per.of} · real vs objetivo</summary>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.gridTable}`}>
            <thead>
              <tr>
                <th scope="col">Día</th>
                {load.metrics.map((m) => <th key={m.key} scope="col">{m.short || m.label}{m.unit ? ` (${m.unit})` : ""}</th>)}
              </tr>
            </thead>
            <tbody>
              {load.days.map((d) => (
                <tr key={d.date}>
                  <th scope="row">{dayName(d.date)} <span className={styles.muted}>{d.md_label}</span></th>
                  {d.kind === "rest"
                    ? <td colSpan={load.metrics.length} className={styles.muted}>Descanso</td>
                    : !d.row
                      ? <td colSpan={load.metrics.length} className={styles.muted}>Sin GPS</td>
                      : load.metrics.map((m) => {
                          const c = d.row!.cells[m.key];
                          return (
                            <td key={m.key}>
                              <div className={styles.num}>{n1(c?.real)} <span className={styles.muted}>/ {n1(c?.target)}</span></div>
                              {c?.pct != null && pill(c.band, signedPct(c.pct))}
                            </td>
                          );
                        })}
                </tr>
              ))}
            </tbody>
            {load.accumulated && (
              <tfoot>
                <tr>
                  <th scope="row">{per.Name} <span className={styles.muted}>({load.accumulated.days} de {load.accumulated.days_planned} días)</span></th>
                  {load.metrics.map((m) => {
                    const c = load.accumulated!.cells[m.key];
                    return (
                      <td key={m.key}>
                        <div className={styles.num}><strong>{n1(c?.real)}</strong> <span className={styles.muted}>/ {n1(c?.target)}</span></div>
                        {c?.pct != null && pill(c.band, signedPct(c.pct))}
                      </td>
                    );
                  })}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
        {toTab("carga", "la carga")}
      </details>

      {/* Check-in / out */}
      <details open className={styles.card}>
        <summary className={styles.h2}>Check-in / out</summary>
        {wl.days.every((d) => !d.row) ? <p className={styles.muted}>No respondió formularios {per.this}.</p> : (
          <div className={styles.tableWrap}>
            <table className={`${styles.table} ${styles.gridTable}`}>
              <thead>
                <tr>
                  <th scope="col">Día</th>
                  {wl.items.map((i) => <th key={i.key} scope="col">{i.label}</th>)}
                  <th scope="col">Total</th><th scope="col">Min</th><th scope="col">RPE</th><th scope="col">UA</th>
                  <th scope="col">Molestias / síntomas</th>
                </tr>
              </thead>
              <tbody>
                {wl.days.map((d) => (
                  <tr key={d.date}>
                    <th scope="row">{dayName(d.date)}</th>
                    {!d.row
                      ? <td colSpan={wl.items.length + 5} className={styles.muted}>Sin respuesta</td>
                      : <>
                          {wl.items.map((i) => {
                            const v = d.row!.scores[i.key];
                            const b = wl.low != null ? scoreBand(v, wl.low) : null;
                            return <td key={i.key}>{v == null ? "—" : pill(b, String(v))}</td>;
                          })}
                          <td className={styles.num}>{n1(d.row.total_bienestar)}</td>
                          <td className={styles.num}>{n1(d.row.duracion_min)}</td>
                          <td className={styles.num}>{n1(d.row.rpe)}</td>
                          <td className={styles.num}>{n1(d.row.ua)}</td>
                          <td>{[...d.row.pain.map((z) => `Molestia: ${z}`), ...d.row.symptoms.map((z) => `Síntoma: ${z}`)].join(" · ") || "—"}</td>
                        </>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {toTab("bienestar", "el check-in / out")}
      </details>

      {/* Fatiga */}
      <details open className={styles.card}>
        <summary className={styles.h2}>Fatiga post-partido</summary>
        {!fa.match || !fr ? <p className={styles.muted}>No tiene saltos del último partido medido.</p> : (
          <>
            <p className={styles.muted}>
              Último partido medido: vs {fa.match.rival ?? "—"} · {shortDate(fa.match.date)}
              {fa.match.source === "propuesta" ? " (fecha propuesta)" : ""}
            </p>
            <div className={styles.summaryGrid}>
              <div className={`${styles.stat} ${styles.band_none}`}>
                <span className={styles.statName}>Basal (últimos {fa.params.baseline_n} PRE)</span>
                <span className={styles.statPair}>{rsi(fr.basal)}</span>
              </div>
              <div className={`${styles.stat} ${styles[`band_${fr.golpe_band ?? "none"}`]}`}>
                <span className={styles.statName}>Golpe · PRE {rsi(fr.pre)} → POST {rsi(fr.post)}</span>
                <span className={styles.statPair}>{signedPct(fr.golpe_pct)}</span>
              </div>
              <div className={`${styles.stat} ${styles[`band_${fr.llega_band ?? "none"}`]}`}>
                <span className={styles.statName}>
                  Recuperación{fa.next_match ? ` · MD-1 vs ${fa.next_match.rival ?? "—"}` : ""}
                </span>
                <span className={styles.statPair}>
                  {fr.llega_state === "measured" ? `${rsi(fr.next_pre)} (${signedPct(fr.llega_pct)})`
                    : fr.llega_state === "missing" ? "No saltó" : "Aún no se mide"}
                </span>
              </div>
              <div className={`${styles.stat} ${styles[`band_${fr.season_drift_band ?? "none"}`]}`}>
                <span className={styles.statName}>Basal en la temporada</span>
                <span className={styles.statPair}>{signedPct(fr.season_drift_pct)}</span>
              </div>
            </div>
          </>
        )}
        {fa.trend && fa.trend.points.length > 1 && (
          <div className={styles.chartBoxSmall} role="img" aria-label={`RSI PRE, POST y basal de ${p.name} en la temporada.`}>
            <ResponsiveContainer>
              <LineChart data={fa.trend.points.map((x) => ({ ...x, tick: shortDate(x.date) }))} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="#eaecf0" />
                <XAxis dataKey="tick" tick={{ fontSize: 11, fill: INK }} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11, fill: INK }} />
                <Tooltip formatter={(v, name) => [typeof v === "number" ? rsi(v) : "—", name]} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="pre" name="PRE (MD-1)" stroke="#2a78d6" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line dataKey="post" name="POST (MD+1)" stroke="#eb6834" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line dataKey="basal" name="Basal" stroke="#475467" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {toTab("fatiga", "la fatiga")}
      </details>

      {/* Estado */}
      <details open={st.status !== "available" || st.history.length > 0} className={styles.card}>
        <summary className={styles.h2}>Kinesia y lesiones</summary>
        {st.card?.episode ? (
          <p>
            <strong>{st.card.episode.title}</strong>{st.card.episode.body_part ? ` · ${st.card.episode.body_part}` : ""} ·{" "}
            {st.card.episode.stage_label} · desde {shortDate(st.card.episode.diagnosed_at)} ({st.card.episode.days_out} días) ·{" "}
            {st.card.episode.expected_return ? `retorno estimado ${shortDate(st.card.episode.expected_return)}` : "sin fecha estimada de retorno"}
          </p>
        ) : <p className={styles.muted}>{st.status === "available" ? "Disponible." : "Sin episodio abierto registrado."}</p>}
        {st.history.length > 0 && (
          <ul className={styles.provenance}>
            {st.history.map((h) => (
              <li key={h.episode_id}>
                {h.title}{h.body_part ? ` (${h.body_part})` : ""} · {shortDate(h.started)}
                {h.days_out != null ? ` · ${h.days_out} días fuera` : ""}
              </li>
            ))}
          </ul>
        )}
        {toTab("lesiones", "Kinesia y lesiones")}
      </details>

      {/* Evaluaciones */}
      <details open className={styles.card}>
        <summary className={styles.h2}>Evaluaciones físicas · último test vs el anterior</summary>
        {!ev.row ? <p className={styles.muted}>Sin evaluaciones con bandas en su categoría.</p> : (
          <div className={styles.tableWrap}>
            <table className={`${styles.table} ${styles.gridTable}`}>
              <thead>
                <tr><th scope="col">Cualidad</th><th scope="col">Test</th><th scope="col">Último</th><th scope="col">Banda</th><th scope="col">vs anterior</th></tr>
              </thead>
              <tbody>
                {ev.groups.flatMap((g) => g.columns.map((c, i) => {
                  const cell = ev.row!.cells[c.key];
                  const tone = deltaTone(cell?.delta, c.direction);
                  return (
                    <tr key={c.key}>
                      {i === 0 && <th scope="rowgroup" rowSpan={g.columns.length}>{g.name}</th>}
                      <td>{c.label}</td>
                      <td className={styles.num}>{cell ? `${n1(cell.value, 2)} ${c.unit}` : "—"}
                        {cell && <div className={styles.muted} style={{ fontSize: "0.72rem" }}>{shortDate(cell.date)} {cell.date.slice(2, 4)}</div>}</td>
                      <td>{cell?.band
                        ? <><span className={styles.dot} style={{ background: cell.color ?? "transparent", display: "inline-block", width: 10, height: 10, borderRadius: 999, marginRight: 6 }} aria-hidden="true" />{cell.band}</>
                        : "—"}</td>
                      <td>{cell?.prev && cell.delta != null
                        ? <span className={`${styles.delta} ${styles[`tone_${tone}`] ?? ""}`} title={deltaToneTitle(tone)}>
                            {cell.delta > 0 ? "▲" : cell.delta < 0 ? "▼" : "="} {cell.delta_pct != null ? `${Math.abs(cell.delta_pct)}%` : ""}
                            <span className={styles.muted}> (antes {n1(cell.prev.value, 2)}, {shortDate(cell.prev.date)} {cell.prev.date.slice(2, 4)})</span>
                          </span>
                        : <span className={styles.muted}>—</span>}</td>
                    </tr>
                  );
                }))}
              </tbody>
            </table>
          </div>
        )}
        {toTab("evaluaciones", "las evaluaciones")}
      </details>

      {/* Composición */}
      <details open className={styles.card}>
        <summary className={styles.h2}>Composición corporal</summary>
        {!co?.player ? <p className={styles.muted}>Sin evaluaciones antropométricas.</p> : (
          <>
            <p className={styles.muted}>
              Última medición {shortDate(co.player.last.date)} {co.player.last.date.slice(2, 4)}
              {co.player.prev ? ` · anterior ${shortDate(co.player.prev.date)} ${co.player.prev.date.slice(2, 4)}` : ""}
            </p>
            <div className={styles.summaryGrid}>
              {co.metrics.map((m) => {
                const d = co.player!.delta[m.key];
                const zero = d != null && Math.abs(d) < 10 ** -m.decimals / 2;
                const tone = d == null ? "neutral" : zero ? "flat" : deltaTone(d, m.direction);
                return (
                  <div key={m.key} className={`${styles.stat} ${styles.band_none}`}>
                    <span className={styles.statName}>{m.label}{m.unit ? ` ${m.unit}` : ""}</span>
                    <span className={styles.statPair}>{n1(co.player!.last[m.key] as number | null, m.decimals)}</span>
                    <span className={`${styles.delta} ${styles[`tone_${tone}`] ?? ""}`}>
                      {d == null ? "sin anterior" : zero ? "= sin cambio" : `${d > 0 ? "▲ +" : "▼ "}${n1(d, m.decimals)} vs anterior`}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
        {toTab("composicion", "la composición")}
      </details>
    </>
  );
}
