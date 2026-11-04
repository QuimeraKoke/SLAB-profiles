"use client";

/**
 * Resumen — "¿Cómo está el plantel hoy / esta semana?" (question 1). One
 * sentence on top, a traffic-light card per question (each opens its tab),
 * then "Para revisar": every flag the tabs raise, per player, worst first.
 * Deterministic, no LLM — see `load_control/summary.py`.
 */

import React, { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { type Band, type SummaryPayload, shortDate, signedPct } from "@/lib/loadControl";

import styles from "./loadControl.module.css";

const KIND_LABEL = { estado: "Estado", fatiga: "Fatiga", carga: "Carga", checkin: "Check-in" } as const;
const LIMIT = 10;

interface Props {
  microcycleId: string;
  onTab: (tab: string, extra?: Record<string, string | null>) => void;
}

export default function SummaryView({ microcycleId, onTab }: Props) {
  const [data, setData] = useState<SummaryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<SummaryPayload>(`/load-control/microcycles/${microcycleId}/summary`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar el resumen."); });
    return () => { cancelled = true; };
  }, [microcycleId]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <p className={styles.muted}>Cargando…</p>;

  const { load, fatigue: fa, wellness: wl, availability: av } = data.cards;
  const pill = (b: Band | null | undefined, text: string) =>
    <span className={`${styles.statusPill} ${styles[`band_${b ?? "none"}`]}`}>{text}</span>;
  const worstOf = (c: Record<Band, number>): Band | null => (c.grave ? "grave" : c.leve ? "leve" : c.ok ? "ok" : null);
  const notAvailable = av.players - av.available;
  const review = showAll ? data.review : data.review.slice(0, LIMIT);

  const card = (tab: string, band: Band | null | undefined, title: string, value: string, sub: React.ReactNode) => (
    <button type="button" onClick={() => onTab(tab)} className={`${styles.stat} ${styles[`band_${band ?? "none"}`]}`}
      style={{ border: 0, textAlign: "left", cursor: "pointer", font: "inherit" }} aria-label={`${title}: ${value}. Abrir pestaña.`}>
      <span className={styles.statName}>{title}</span>
      <span className={styles.statPair}>{value}</span>
      <span className={styles.statCounts}>{sub}</span>
    </button>
  );

  return (
    <>
      <section className={styles.card} aria-labelledby="su-sentence">
        <h2 id="su-sentence" className={styles.h2} style={{ fontSize: "1.05rem", lineHeight: 1.45 }}>{data.sentence}</h2>
        <div className={styles.summaryGrid}>
          {card("carga", load.worst?.band, `Carga de la semana (${load.days} días)`,
            load.worst ? `${load.worst.label} ${signedPct(load.worst.pct)}` : "Sin GPS",
            <>{load.short} para compensar · {load.over} pasados</>)}
          {card("fatiga", worstOf(fa.counts),
            fa.state === "recuperacion" ? "Recuperación del partido" : "Golpe del último partido",
            fa.match ? `${fa.counts.grave} en rojo de ${fa.measured}` : "Sin saltos",
            fa.match ? <>vs {fa.match.rival ?? "—"} · {shortDate(fa.match.date)}{fa.match.source === "propuesta" ? " (fecha propuesta)" : ""}</> : "—")}
          {card("bienestar", wl.pain ? "grave" : wl.flagged ? "leve" : wl.day ? "ok" : null,
            wl.day ? `Check-in del ${shortDate(wl.day)}` : "Check-in",
            wl.day ? `${wl.pain} con molestias` : "Sin respuestas",
            wl.answered ? <>{wl.answered.checkin} respondieron · {wl.missing} entrenaron sin responder</> : "—")}
          {card("lesiones", notAvailable ? "leve" : "ok", "Disponibles",
            `${av.available} de ${av.players}`,
            av.counts.filter((c) => c.status !== "available" && c.n).map((c) => `${c.n} ${c.label.toLowerCase()}`).join(" · ") || "todos disponibles")}
        </div>
        <div className={styles.legend}>
          {load.metrics.map((m) => <span key={m.key}>{m.label}: {pill(m.band, signedPct(m.pct))}</span>)}
        </div>
      </section>

      <section className={styles.card} aria-labelledby="su-review">
        <div className={styles.cardHead}>
          <h2 id="su-review" className={styles.h2}>Para revisar</h2>
          <span className={styles.muted}>{data.review.length} jugadores · primero lo de salud</span>
        </div>
        {data.review.length === 0 ? <p className={styles.muted}>Nadie para revisar esta semana.</p> : (
          <div className={styles.players}>
            {review.map((r) => (
              <div key={r.player_id} className={styles.flagRow}>
                <span className={styles.playerName}>
                  <button type="button" className={styles.linkButton} onClick={() => onTab("jugador", { jugador: r.player_id })}>
                    <strong>{r.name}</strong>
                  </button>
                </span>
                <span style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  {r.flags.map((f, i) => (
                    <span key={i} className={`${styles.statusPill} ${styles[`band_${f.level}`]}`} style={{ whiteSpace: "normal" }}>
                      {KIND_LABEL[f.kind]} · {f.text}
                    </span>
                  ))}
                </span>
              </div>
            ))}
          </div>
        )}
        {data.review.length > LIMIT && (
          <button type="button" className={styles.secondary} aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Ver menos" : `Ver ${data.review.length - LIMIT} más`}
          </button>
        )}
      </section>

      <details className={styles.card}>
        <summary className={styles.h2}>Cómo se calcula</summary>
        <ul className={styles.provenance}>
          <li>Carga: la semana hasta hoy ({load.days} días con plan) contra el objetivo de cada posición; semáforo ±8 % / ±12 %.
            “Para compensar” = {load.rules.short_min_metrics} o más métricas bajo −{load.rules.below_pct} %; “pasado” = alguna sobre
            +{load.rules.over_pct} % (reglas del artifact del club).</li>
          <li>Fatiga: el último partido con saltos; rojo = −5 % o menos (golpe = POST vs PRE; recuperación = MD-1 siguiente vs PRE).</li>
          <li>Check-in: el último día de la semana con respuestas; molestias = zona marcada en el check-in o check-out.</li>
          <li>Disponibles: estado actual de cada jugador (Kinesia y lesiones).</li>
          <li>Sin IA: la frase y la lista salen de estas mismas reglas. Toca una tarjeta para abrir su pestaña, o un nombre para su ficha.</li>
        </ul>
      </details>
    </>
  );
}
