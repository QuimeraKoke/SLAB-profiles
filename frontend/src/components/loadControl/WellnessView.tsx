"use client";

/**
 * Check-in / out — "¿Cómo llega el jugador, cómo se siente, qué le molesta,
 * cómo se va?" (question 4). As the club's brief lays it out: first who
 * reported low wellness or pain that day, each with its score; then a simple
 * evolution over the microcycle — check-in bars per item (1–5) with the two
 * totals as lines (bienestar /25, muscular /10), and check-out minutes and RPE.
 *
 * The club's check-out chart puts minutes and RPE on two y-axes; here they are
 * two small charts aligned by day instead (one scale per chart — two scales on
 * one chart make the crossing points mean nothing).
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api, ApiError } from "@/lib/api";
import {
  fmt, type McDetail, scoreBand, shortDate, type WellnessPayload,
} from "@/lib/loadControl";

import styles from "./loadControl.module.css";
import { PlayerName } from "@/components/loadControl/PlayerPhotos";

// Validated categorical slots 1–5 for the items, 7 and 6 for the totals
// (dataviz reference palette, light mode).
const ITEM_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"];
const TOTAL_COLOR = "#6250d6";
const MUSCLE_COLOR = "#008300";
const INK = "#475467";

interface Props {
  microcycleId: string;
  day: string | null;
  playerId: string | null;
  onFilters: (f: { day?: string | null; player?: string | null }) => void;
  /** The page navigates the days (Centro de mando): hide this view's own. */
  hideDayNav?: boolean;
}

export default function WellnessView({ microcycleId, day, playerId, onFilters, hideDayNav = false }: Props) {
  const [detail, setDetail] = useState<McDetail | null>(null);
  const [data, setData] = useState<WellnessPayload | null>(null);
  const [roster, setRoster] = useState<{ player_id: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  // "Ver más": long lists show their first rows only.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [today] = useState(() => {
    const t = new Date();
    return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
  });

  useEffect(() => {
    let cancelled = false;
    api<McDetail>(`/load-control/microcycles/${microcycleId}`)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la semana."); });
    return () => { cancelled = true; };
  }, [microcycleId]);

  // Until the URL says otherwise: the last day of the microcycle up to today.
  const effectiveDay = useMemo(() => {
    if (day || !detail) return day;
    const past = detail.days.filter((d) => d.date <= today);
    return (past.length ? past[past.length - 1] : detail.days[0])?.date ?? null;
  }, [day, detail, today]);

  useEffect(() => {
    if (!detail || !effectiveDay) return;
    let cancelled = false;
    const sp = new URLSearchParams({ day: effectiveDay });
    if (playerId) sp.set("player_id", playerId);
    api<WellnessPayload>(`/load-control/microcycles/${microcycleId}/wellness?${sp}`)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
        // The squad list for the player picker comes from the group view.
        if (!playerId) setRoster([...(d.rows ?? []), ...(d.missing ?? [])]
          .map((r) => ({ player_id: r.player_id, name: r.name }))
          .sort((a, b) => a.name.localeCompare(b.name)));
      })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar el check-in / out."); });
    return () => { cancelled = true; };
  }, [detail, microcycleId, effectiveDay, playerId]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!detail || !data) return <p className={styles.muted}>Cargando…</p>;

  const dayList = detail.days.map((d) => d.date);
  const pos = dayList.indexOf(effectiveDay ?? "");
  const prevDay = pos > 0 ? dayList[pos - 1] : null;
  const nextDay = pos >= 0 && pos < dayList.length - 1 ? dayList[pos + 1] : null;
  const dayInfo = (iso: string) => detail.days.find((d) => d.date === iso);
  const dayLabel = (iso: string) => {
    const d = dayInfo(iso);
    return d ? `${d.weekday} ${shortDate(d.date)} · ${d.md_label || "—"}` : iso;
  };
  const tick = (iso: string) => {
    const d = dayInfo(iso);
    return d ? `${d.weekday} ${d.md_label || ""}`.trim() : iso;
  };
  const itemLabel = (k: string) => data.items.find((i) => i.key === k)?.label ?? k;
  const who = playerId ? (roster.find((r) => r.player_id === playerId)?.name ?? "Jugador") : "Plantel";
  const chartData = data.series.map((r) => ({ ...r, tick: tick(r.date) }));
  const selected = data.series.find((r) => r.date === effectiveDay);

  const LIMIT = { flagged: 8 } as const;
  const visible = <T,>(key: keyof typeof LIMIT, list: T[]) => (open[key] ? list : list.slice(0, LIMIT[key]));
  const moreButton = (key: keyof typeof LIMIT, total: number, what: string) => (total > LIMIT[key] ? (
    <button type="button" className={styles.secondary} aria-expanded={!!open[key]}
      onClick={() => setOpen((o) => ({ ...o, [key]: !o[key] }))}>
      {open[key] ? "Ver menos" : `Ver ${total - LIMIT[key]} ${total - LIMIT[key] === 1 ? what.replace(/es$|s$/, "") : what} más`}
    </button>
  ) : null);
  const flagged = data.flagged ?? [];
  const rows = data.rows ?? [];
  const noIn = data.no_checkin ?? [];
  const noOut = data.no_checkout ?? [];

  // "Sueño 4" — one compact chip per item, coloured by the club's bands.
  const inlineChip = (k: string, v: number | null) => {
    const b = scoreBand(v, data.low);
    return (
      <span key={k} className={`${styles.inlineChip} ${styles[`band_${b ?? "none"}`]}`}>
        {itemLabel(k)} <strong>{v == null ? "—" : fmt(v)}</strong>
      </span>
    );
  };
  const outLine = (r: (typeof rows)[number]) => [
    r.checkout
      ? [r.duracion_min != null && `${fmt(r.duracion_min)} min`, r.rpe != null && `esfuerzo ${fmt(r.rpe)}`,
        r.ua != null && `UA ${fmt(r.ua)}`].filter(Boolean).join(" · ") || "check-out sin datos"
      : "sin check-out",
    r.peso != null ? `${fmt(r.peso)} kg` : null,
  ].filter(Boolean).join(" · ");
  const pendingList = (list: typeof noIn, what: string) => (
    list.length === 0
      ? <p className={styles.muted}>Todos respondieron el {what}.</p>
      : (
        <ul className={styles.pendingList}>
          {list.map((w) => (
            <li key={w.player_id}>
              <PlayerName id={w.player_id} name={w.name} size={24}>
                <span>{w.name}{w.position && <span className={styles.posTag}> {w.position}</span>}</span>
              </PlayerName>
              {w.trained && <span className={styles.trainedTag}>entrenó</span>}
            </li>
          ))}
        </ul>
      )
  );

  return (
    <>
      <div className={styles.controls}>
        {!hideDayNav && <>
        <button type="button" className={styles.secondary} disabled={!prevDay}
          onClick={() => prevDay && onFilters({ day: prevDay })}
          aria-label={prevDay ? `Día anterior: ${dayLabel(prevDay)}` : "No hay día anterior"}>
          ‹ Día anterior
        </button>
        <label className={styles.label}>
          Día
          <select className={styles.select} value={effectiveDay ?? ""} onChange={(e) => onFilters({ day: e.target.value })}>
            {detail.days.map((d) => <option key={d.date} value={d.date}>{dayLabel(d.date)}</option>)}
          </select>
        </label>
        <button type="button" className={styles.secondary} disabled={!nextDay}
          onClick={() => nextDay && onFilters({ day: nextDay })}
          aria-label={nextDay ? `Día siguiente: ${dayLabel(nextDay)}` : "No hay día siguiente"}>
          Día siguiente ›
        </button>
        </>}
        <label className={styles.label}>
          Ver
          <select className={styles.select} value={playerId ?? ""} onChange={(e) => onFilters({ player: e.target.value || null })}>
            <option value="">Todo el plantel</option>
            {roster.map((r) => <option key={r.player_id} value={r.player_id}>{r.name}</option>)}
          </select>
        </label>
      </div>

      <section className={styles.card} aria-labelledby="wl-flag">
        <div className={styles.cardHead}>
          <h2 id="wl-flag" className={styles.h2}>Bienestar bajo, molestias y síntomas · {effectiveDay ? dayLabel(effectiveDay) : ""}</h2>
          {data.answered && (
            <span className={styles.muted}>
              Check-in {data.answered.checkin} de {data.players} · check-out {data.answered.checkout} de {data.players}
            </span>
          )}
        </div>
        {flagged.length === 0
          ? <p className={styles.muted}>Nadie reportó bienestar bajo (≤ {data.low}), molestias ni síntomas.</p>
          : (
            <div role="table" aria-label="Bienestar bajo, molestias y síntomas" className={styles.flagTable}>
              <div role="row" className={`${styles.flagGrid} ${styles.flagHead}`}>
                <span role="columnheader">Jugador</span>
                <span role="columnheader">Bienestar (/25)</span>
                <span role="columnheader">Ítems bajos (≤ {data.low})</span>
                <span role="columnheader">Molestia</span>
                <span role="columnheader">Síntoma</span>
              </div>
              {visible("flagged", flagged).map((f) => (
                <div key={f.player_id} role="row" className={styles.flagGrid}>
                  <span role="cell">
                    <PlayerName id={f.player_id} name={f.name}>
                      <span><strong>{f.name}</strong>{f.position && <span className={styles.posTag}> {f.position}</span>}</span>
                    </PlayerName>
                  </span>
                  <span role="cell" className={styles.flagNum} data-label="Bienestar">
                    {f.total_bienestar == null ? "—" : fmt(f.total_bienestar)}
                  </span>
                  <span role="cell" className={styles.chips5} data-label="Ítems bajos">
                    {f.lows.length ? f.lows.map((l) => inlineChip(l.key, l.value)) : <span className={styles.muted}>—</span>}
                  </span>
                  <span role="cell" className={f.pain.length ? styles.painText : styles.muted} data-label="Molestia">
                    {f.pain.length ? f.pain.join(" · ") : "—"}
                  </span>
                  <span role="cell" className={f.symptoms.length ? styles.symptomText : styles.muted} data-label="Síntoma">
                    {f.symptoms.length ? f.symptoms.join(" · ") : "—"}
                  </span>
                </div>
              ))}
            </div>
          )}
        {moreButton("flagged", flagged.length, "jugadores")}
      </section>

      {!playerId && (
        <section className={styles.card} aria-labelledby="wl-rows">
          <div className={styles.cardHead}>
            <h2 id="wl-rows" className={styles.h2}>Por jugador · {effectiveDay ? dayLabel(effectiveDay) : ""}</h2>
            <span className={styles.muted}>{rows.length} jugador{rows.length === 1 ? "" : "es"} · 1–2 rojo · 3 amarillo · 4–5 verde</span>
          </div>
          {rows.length === 0
            ? <p className={styles.muted}>Nadie respondió el check-in ni el check-out este día.</p>
            : (
              <ul className={styles.answerList}>
                {rows.map((r) => (
                  <li key={r.player_id} className={styles.answerRow}>
                    <PlayerName id={r.player_id} name={r.name} size={36}>
                      <span className={styles.answerBody}>
                        <span>
                          <strong>{r.name}</strong>
                          {r.position && <span className={styles.posTag}> {r.position}</span>}
                        </span>
                        <span className={styles.chips5}>
                          {r.checkin
                            ? data.items.map((it) => inlineChip(it.key, r.scores[it.key]))
                            : <span className={styles.muted}>sin check-in</span>}
                        </span>
                        <span className={styles.muted}>{outLine(r)}</span>
                        {(r.pain.length > 0 || r.symptoms.length > 0) && (
                          <span className={styles.painText}>
                            <span aria-hidden="true">⚠ </span>
                            {[...r.pain, ...r.symptoms].join(", ")}
                          </span>
                        )}
                      </span>
                    </PlayerName>
                  </li>
                ))}
              </ul>
            )}
        </section>
      )}

      {!playerId && (
        <section className={styles.card} aria-labelledby="wl-pending">
          <div className={styles.cardHead}>
            <h2 id="wl-pending" className={styles.h2}>Sin responder · {effectiveDay ? dayLabel(effectiveDay) : ""}</h2>
            <span className={styles.muted}>Plantel de la semana · primero los que entrenaron ese día</span>
          </div>
          <div className={styles.pendingGrid}>
            <div>
              <h3 className={styles.h3}>Check-in ({noIn.length})</h3>
              {pendingList(noIn, "check-in")}
            </div>
            <div>
              <h3 className={styles.h3}>Check-out ({noOut.length})</h3>
              {pendingList(noOut, "check-out")}
            </div>
          </div>
        </section>
      )}

      <section className={styles.card} aria-labelledby="wl-in">
        <div className={styles.cardHead}>
          <h2 id="wl-in" className={styles.h2}>Cómo llegan, día a día · {who}</h2>
          <span className={styles.muted}>Check-in</span>
        </div>
        <div className={styles.chartBox} role="img"
          aria-label={`Check-in de ${who} por día: promedio de cada ítem de 1 a 5, total bienestar sobre 25 y total muscular sobre 10.`}>
          <ResponsiveContainer>
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barCategoryGap="18%">
              <CartesianGrid vertical={false} stroke="#eaecf0" />
              <XAxis dataKey="tick" tick={{ fontSize: 11, fill: INK }} tickLine={false} axisLine={{ stroke: "#d0d5dd" }} />
              <YAxis domain={[0, 25]} ticks={[0, 5, 10, 15, 20, 25]} tick={{ fontSize: 11, fill: INK }} tickLine={false} axisLine={false} />
              <Tooltip formatter={(v, n) => [typeof v === "number" ? v.toFixed(1).replace(".", ",") : "—", n]}
                labelFormatter={(l) => String(l)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {data.items.map((it, i) => (
                <Bar key={it.key} dataKey={it.key} name={it.label} fill={ITEM_COLORS[i]} radius={[4, 4, 0, 0]} />
              ))}
              <Line dataKey="total_bienestar" name="Total bienestar (/25)" stroke={TOTAL_COLOR} strokeWidth={2}
                dot={{ r: 4 }} connectNulls={false} />
              <Line dataKey="total_muscular" name="Total muscular (/10)" stroke={MUSCLE_COLOR} strokeWidth={2}
                dot={{ r: 4 }} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p className={styles.provenance}>
          Barras: promedio de cada ítem de 1 a 5 (5 es lo mejor). Líneas: suma de los 5 ítems (máximo 25) y fatiga + daño
          muscular (máximo 10). Un día sin respuestas queda vacío, no en cero.
        </p>
      </section>

      <section className={styles.card} aria-labelledby="wl-out">
        <div className={styles.cardHead}>
          <h2 id="wl-out" className={styles.h2}>Cómo se van · {who}</h2>
          <span className={styles.muted}>Check-out</span>
        </div>
        <div className={styles.chartGrid}>
          <div>
            <p className={styles.muted}>Duración de la sesión (min)</p>
            <div className={styles.chartBoxSmall} role="img" aria-label={`Minutos promedio por día de ${who}.`}>
              <ResponsiveContainer>
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#eaecf0" />
                  <XAxis dataKey="tick" tick={{ fontSize: 11, fill: INK }} tickLine={false} axisLine={{ stroke: "#d0d5dd" }} />
                  <YAxis tick={{ fontSize: 11, fill: INK }} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v) => [typeof v === "number" ? `${Math.round(v)} min` : "—", "Duración"]} />
                  <Bar dataKey="duracion_min" name="Duración" fill={ITEM_COLORS[0]} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div>
            <p className={styles.muted}>Esfuerzo percibido (RPE, 0–10)</p>
            <div className={styles.chartBoxSmall} role="img" aria-label={`RPE promedio por día de ${who}.`}>
              <ResponsiveContainer>
                <LineChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#eaecf0" />
                  <XAxis dataKey="tick" tick={{ fontSize: 11, fill: INK }} tickLine={false} axisLine={{ stroke: "#d0d5dd" }} />
                  <YAxis domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} tick={{ fontSize: 11, fill: INK }} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v) => [typeof v === "number" ? v.toFixed(1).replace(".", ",") : "—", "RPE"]} />
                  <Line dataKey="rpe" name="RPE" stroke={ITEM_COLORS[1]} strokeWidth={2} dot={{ r: 4 }} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
        {selected && (
          <p className={styles.provenance}>
            {effectiveDay ? dayLabel(effectiveDay) : ""}: {fmt(selected.duracion_min as number | null)} min promedio ·
            RPE {selected.rpe == null ? "—" : String(selected.rpe).replace(".", ",")} · UA {fmt(selected.ua as number | null)}
            {" "}(UA = minutos × RPE).
          </p>
        )}
      </section>

      <p className={styles.provenance}>
        Datos usados: formularios de check-in y check-out del plantel de la semana {detail.number} ({data.players} jugadores que
        entrenaron o respondieron esa semana). Día en hora de Chile; si alguien respondió dos veces el mismo día, cuenta la
        última. Bienestar bajo = un ítem ≤ {data.low}. Molestia = la zona que anotó en el check-in o el check-out;
        síntoma = lo que anotó en “Síntomas” (fiebre, resfriado…). “Sin responder” lista al plantel de la semana sin el
        formulario ese día; “entrenó” = tiene GPS ese día.
      </p>
    </>
  );
}
