"use client";

/**
 * Carga GPS — "¿Cumplieron lo planificado?" for one day or the microcycle so
 * far. Laid out as the club's brief asks ("Anatomía de una buena pantalla"):
 * filters → squad vs target in cards → one row per player, ordered by what
 * they did → "datos usados". (The per-player alert list was taken out on the
 * staff's request, 2026-11-03: the cards' counts and the coloured player rows
 * already show who left the band.) Every number reads real vs target (the staff's order, 2026-11-03), then Δ% with the band in
 * WORDS — colour never alone. A player with no GPS is "sin datos", never −100%.
 */

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  BAND_WORD, type EvalCell, type Evaluation, fmt, type McDetail, shortDate, signedPct,
} from "@/lib/loadControl";

import styles from "./loadControl.module.css";

interface Props {
  microcycleId: string;
  day: string | null;            // null = accumulated
  sparring: boolean | null;      // null = club default
  matches: boolean;
  onFilters: (f: { day?: string | null; sparring?: boolean | null; matches?: boolean }) => void;
}

const ACC = "acumulado";

function bandClass(c: EvalCell | undefined) {
  return styles[`band_${c?.band ?? "none"}`];
}

export default function EvaluationView({ microcycleId, day, sparring, matches, onFilters }: Props) {
  const [detail, setDetail] = useState<McDetail | null>(null);
  const [data, setData] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  // Local calendar date (not UTC: at 22:00 in Santiago UTC is already tomorrow).
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

  // Until the URL says otherwise: the last day with a plan up to today.
  const effectiveDay = useMemo(() => {
    if (day !== null || !detail) return day;
    const played = detail.days.filter((d) => d.kind !== "rest" && d.date <= today);
    return played.length ? played[played.length - 1].date : ACC;
  }, [day, detail, today]);

  useEffect(() => {
    if (!detail || effectiveDay === null) return;
    let cancelled = false;
    const sp = new URLSearchParams();
    if (effectiveDay !== ACC) sp.set("day", effectiveDay);
    if (sparring !== null) sp.set("sparring", String(sparring));
    if (!matches) sp.set("matches", "false");
    api<Evaluation>(`/load-control/microcycles/${microcycleId}/evaluation?${sp}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo calcular la carga."); });
    return () => { cancelled = true; };
  }, [detail, microcycleId, effectiveDay, sparring, matches]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!detail || !data) return <p className={styles.muted}>Calculando…</p>;

  // Prev / next through the microcycle's days (rest days skipped).
  const dayList = detail.days.filter((d) => d.kind !== "rest").map((d) => d.date);
  const pos = effectiveDay === ACC ? dayList.length : dayList.indexOf(effectiveDay ?? "");
  const prevDay = pos > 0 ? dayList[pos - 1] : null;
  const nextDay = pos >= 0 && pos < dayList.length - 1 ? dayList[pos + 1] : null;
  const dayLabel = (iso: string) => {
    const d = detail.days.find((x) => x.date === iso);
    return d ? `${d.weekday} ${shortDate(d.date)} · ${d.md_label || "—"}` : iso;
  };

  const metrics = data.metrics;
  const isAcc = data.mode === "accumulated";
  const off = metrics.filter((m) => data.summary[m.key]?.band && data.summary[m.key].band !== "ok");
  const list = (ms: typeof metrics) => {
    const parts = ms.map((m) => `${m.short} (${signedPct(data.summary[m.key].pct)})`);
    return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} y ${parts[parts.length - 1]}` : parts[0];
  };
  const over = off.filter((m) => (data.summary[m.key].pct ?? 0) > 0);
  const under = off.filter((m) => (data.summary[m.key].pct ?? 0) < 0);
  const conclusion = data.players.length === 0
    ? "Sin datos GPS para este día."
    : (off.length === 0
      ? "En promedio, el plantel quedó en objetivo en todas las métricas."
      : `En promedio, el plantel quedó ${[
          over.length ? `por encima del objetivo en ${list(over)}` : "",
          under.length ? `por debajo en ${list(under)}` : "",
        ].filter(Boolean).join(", y ")}.`);
  const players = showAll ? data.players : data.players.slice(0, 12);
  const pv = data.provenance;
  const whenText = isAcc
    ? `acumulado de la semana ${pv.microcycle} (${data.days.length} día${data.days.length === 1 ? "" : "s"}${matches ? ", con partido" : ", sin partido"})`
    : `semana ${pv.microcycle} · ${shortDate(data.day!)} (${data.days[0]?.md_label || "—"})`;

  return (
    <>
      <div className={styles.controls}>
        <button type="button" className={styles.secondary} disabled={!prevDay}
          onClick={() => prevDay && onFilters({ day: prevDay })}
          aria-label={prevDay ? `Día anterior: ${dayLabel(prevDay)}` : "No hay día anterior"}>
          ‹ Día anterior
        </button>
        <label className={styles.label}>
          Día
          <select className={styles.select} value={effectiveDay ?? ACC}
            onChange={(e) => onFilters({ day: e.target.value })}>
            {detail.days.filter((d) => d.kind !== "rest").map((d) => (
              <option key={d.date} value={d.date}>{d.weekday} {shortDate(d.date)} · {d.md_label || "—"}</option>
            ))}
            <option value={ACC}>Acumulado de la semana</option>
          </select>
        </label>
        <button type="button" className={styles.secondary} disabled={!nextDay}
          onClick={() => nextDay && onFilters({ day: nextDay })}
          aria-label={nextDay ? `Día siguiente: ${dayLabel(nextDay)}` : "No hay día siguiente"}>
          Día siguiente ›
        </button>
        <label className={styles.toggle}>
          <input type="checkbox" checked={pv.include_sparring}
            onChange={(e) => onFilters({ sparring: e.target.checked })} />
          Incluir sparring
        </label>
        {isAcc && (
          <label className={styles.toggle}>
            <input type="checkbox" checked={matches} onChange={(e) => onFilters({ matches: e.target.checked })} />
            Incluir partidos
          </label>
        )}
      </div>

      <section className={styles.card} aria-labelledby="ev-res">
        <div className={styles.cardHead}>
          <h2 id="ev-res" className={styles.h2}>¿Cumplieron lo planificado? · {isAcc ? "Acumulado" : (data.days[0]?.md_label || "Día")}</h2>
          <span className={styles.muted}>Promedio por jugador · real vs objetivo</span>
        </div>
        <p style={{ margin: 0, fontSize: "0.95rem" }}>{conclusion}</p>
        <div className={styles.summaryGrid}>
          {metrics.map((m) => {
            const s = data.summary[m.key];
            return (
              <div key={m.key} className={`${styles.stat} ${bandClass(s)}`}>
                <span className={styles.statName}>{m.label}</span>
                <span className={styles.statPair}>{fmt(s?.real)} vs {fmt(s?.target)}</span>
                <span className={styles.statPct}>
                  {s?.pct == null ? "sin objetivo" : `${signedPct(s.pct)} · ${BAND_WORD[s.band!]}`}
                </span>
                {s?.n ? (
                  <span className={styles.statCounts}>
                    Jugadores: {s.counts.ok} en objetivo · {s.counts.leve} leve · {s.counts.grave} grave
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
        <div className={styles.legend}>
          <span>En objetivo: ±{data.bands.ok}%</span>
          <span>Alerta leve: {data.bands.ok}–{data.bands.mild}%</span>
          <span>Alerta grave: más de {data.bands.mild}% (bajo o sobre)</span>
        </div>
      </section>

      <section className={styles.card} aria-labelledby="ev-pl">
        <div className={styles.cardHead}>
          <h2 id="ev-pl" className={styles.h2}>Jugadores ({data.players.length})</h2>
          <span className={styles.muted}>Ordenados por {metrics[0]?.short ?? "lo que hicieron"} · real vs objetivo</span>
        </div>
        <div className={styles.players}>
          {players.map((p) => (
            <div key={p.player_id} className={styles.playerRow}>
              <span className={styles.playerName}>
                <strong>{p.name}</strong>
                <span className={styles.muted}>
                  {p.group} · {fmt(p.minutes)} min
                  {isAcc ? ` · ${p.days} de ${p.days_planned} días` : ""}
                  {p.sparring ? " · con sparring" : ""}{p.compensacion ? " · con compensación" : ""}
                </span>
              </span>
              {metrics.map((m) => {
                const c = p.cells[m.key];
                return (
                  <span key={m.key} className={`${styles.cell} ${bandClass(c)}`}>
                    <span>{m.short}</span>
                    <span>{c.real == null ? "sin datos" : `${fmt(c.real)} vs ${c.target == null ? "—" : fmt(c.target)}`}</span>
                    <span className={styles.cellPct}>{c.pct == null ? (c.target == null ? "sin objetivo" : "—") : signedPct(c.pct)}</span>
                  </span>
                );
              })}
            </div>
          ))}
        </div>
        {data.players.length > 12 && (
          <button type="button" className={styles.secondary} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Ver menos" : `Ver los ${data.players.length} jugadores`}
          </button>
        )}
      </section>

      <p className={styles.provenance}>
        Datos usados: {whenText} · {pv.players} jugadores con GPS
        {pv.include_sparring ? `, sparring sumado (${pv.players_with_sparring} jugadores)` : ", sin sparring"}
        {pv.duplicates_dropped ? ` · ${pv.duplicates_dropped} filas duplicadas de la planilla contadas una vez` : ""}
        {" · "}objetivo = referencia de partido {pv.reference_frozen ? "fija (semana publicada)" : "(vista previa: la semana no está publicada)"}
        {pv.reference_window ? ` del ${shortDate(pv.reference_window.start)} al ${shortDate(pv.reference_window.end)}` : ""} × % del plan
        {pv.fallback_groups.length ? ` · ${pv.fallback_groups.join(", ")} usa el promedio del equipo` : ""}
        {isAcc ? " · cada jugador se compara sólo en los días con GPS" : ""}.
        Sin dato se muestra “sin datos”, no cero.
      </p>
    </>
  );
}
