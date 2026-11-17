"use client";

/**
 * Disponibilidad — "¿Cómo llega cada jugador a entrenar hoy?". One row per
 * player of the week's squad with what each tab says about him for the day:
 * status, today's check-in, the last match and his load (7 vs 28 days). No
 * verdict: the coach decides who trains and how hard. Every number is a tab's
 * own (backend `load_control/day_status.py`), with the club's bands, and each
 * band is said in words too — never colour alone.
 */

import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { type Band, type DayStatusPayload, type DayStatusRow, shortDate } from "@/lib/loadControl";

import styles from "./loadControl.module.css";
import own from "./DayStatusView.module.css";
import { PlayerName } from "@/components/loadControl/PlayerPhotos";
import ScopeBadge from "./ScopeBadge";

export type DayStatusFilter =
  | "molestia" | "bienestar" | "sintoma" | "sin_checkin" | "partido" | "sobre_plan" | "bajo_plan";

const FILTERS: { id: DayStatusFilter; label: string; count: keyof DayStatusPayload["counts"]; band: Band;
  test: (r: DayStatusRow) => boolean }[] = [
  { id: "molestia", label: "Molestia en el check-in", count: "pain", band: "grave",
    test: (r) => !!r.checkin?.pain.length },
  { id: "bienestar", label: "Bienestar bajo", count: "low", band: "leve",
    test: (r) => !!r.checkin?.lows.length },
  { id: "sintoma", label: "Síntoma (enfermedad)", count: "symptoms", band: "leve",
    test: (r) => !!r.checkin?.symptoms.length },
  { id: "partido", label: "Golpe fuerte del partido", count: "hit", band: "grave",
    test: (r) => r.match?.golpe_band === "grave" || r.match?.llega_band === "grave" },
  { id: "sobre_plan", label: "Sobre lo planificado", count: "load_over", band: "grave",
    test: (r) => !!r.load?.over },
  { id: "bajo_plan", label: "Bajo lo planificado", count: "load_under", band: "leve",
    test: (r) => !!r.load?.under },
  { id: "sin_checkin", label: "Sin check-in", count: "no_checkin", band: "leve",
    test: (r) => !r.checkin },
];
export const DAY_STATUS_FILTERS = new Set<string>(FILTERS.map((f) => f.id));

const pct = (p: number | null) =>
  p == null ? "—" : `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toLocaleString("es-CL", { maximumFractionDigits: 1 })} %`;

const BAND_WORD: Record<Band, string> = { ok: "normal", leve: "atención", grave: "alerta" };

function Pill({ band, children, title }: { band: Band | null | undefined; children: React.ReactNode; title?: string }) {
  return <span className={`${own.pill} ${styles[`band_${band ?? "none"}`]}`} title={title}>{children}</span>;
}

interface Props {
  microcycleId: string;
  day?: string | null;
  filter: DayStatusFilter | null;
  onFilter: (f: DayStatusFilter | null) => void;
  /** Heading of the signals card (Resumen already shows "Disponibles"). */
  heading?: string;
}

export default function DayStatusView({ microcycleId, day, filter, onFilter, heading }: Props) {
  const [data, setData] = useState<DayStatusPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<DayStatusPayload>(`/load-control/microcycles/${microcycleId}/day-status${day ? `?day=${day}` : ""}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la disponibilidad."); });
    return () => { cancelled = true; };
  }, [microcycleId, day]);

  const active = FILTERS.find((f) => f.id === filter) ?? null;
  const rows = useMemo(() => {
    if (!data) return [];
    return active ? data.rows.filter((r) => r.status === "available" && active.test(r)) : data.rows;
  }, [data, active]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <p className={styles.muted}>Cargando…</p>;

  const { counts, rules } = data;
  const available = rows.filter((r) => r.status === "available");
  const out = rows.filter((r) => r.status !== "available");
  const lr = rules.load;

  return (
    <>
      <section className={styles.card} aria-labelledby="ds-head">
        <div className={styles.cardHead}>
          <h2 id="ds-head" className={styles.h2}>
            {heading ?? `Disponibles: ${counts.available} de ${counts.players}`}
          </h2>
          <span className={styles.cardMeta}><ScopeBadge kind="day" /></span>
        </div>
        <p className={own.lead}>
          Toca una señal para ver solo a esos jugadores. Cada señal sale de su pestaña, con los umbrales del club.
        </p>
        <div className={own.filters} role="group" aria-label="Filtrar por señal">
          {FILTERS.map((f) => {
            const n = counts[f.count];
            const on = filter === f.id;
            return (
              <button key={f.id} type="button" aria-pressed={on} disabled={!n && !on}
                className={`${own.filter} ${n ? styles[`band_${f.band}`] : styles.band_none} ${on ? own.filterOn : ""}`}
                onClick={() => onFilter(on ? null : f.id)}>
                <span className={own.filterN}>{n}</span>
                <span className={own.filterLabel}>{f.label}</span>
              </button>
            );
          })}
        </div>
        {active && (
          <p className={own.lead}>
            Mostrando: <strong>{active.label.toLowerCase()}</strong> ·{" "}
            <button type="button" className={styles.linkButton} onClick={() => onFilter(null)}>Ver todo el plantel</button>
          </p>
        )}
      </section>

      <section className={styles.card} aria-labelledby="ds-table">
        <div className={styles.cardHead}>
          <h2 id="ds-table" className={styles.h2}>Cómo llega cada jugador</h2>
          <span className={styles.muted}>
            {data.match ? <>Último partido: vs {data.match.rival ?? "—"} · {shortDate(data.match.date)}</> : "Sin partido medido"}
          </span>
        </div>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${own.table}`}>
            <thead>
              <tr>
                <th scope="col">Jugador</th>
                <th scope="col">Check-in de hoy</th>
                <th scope="col">Último partido</th>
                <th scope="col">Carga vs lo planificado{lr.planned ? " (semana)" : ""}</th>
              </tr>
            </thead>
            <tbody>
              {available.map((r) => <Row key={r.player_id} r={r} planned={lr.planned} />)}
              {out.length > 0 && (
                <tr className={own.groupRow}>
                  <th scope="rowgroup" colSpan={4}>No disponibles ({out.length})</th>
                </tr>
              )}
              {out.map((r) => <Row key={r.player_id} r={r} planned={lr.planned} />)}
              {rows.length === 0 && (
                <tr><td colSpan={4} className={styles.muted}>Ningún jugador con esa señal.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <details className={styles.card}>
        <summary className={styles.h2} style={{ cursor: "pointer", minHeight: 28 }}>Cómo se lee</summary>
        <ul className={own.legend}>
          <li><strong>Check-in de hoy:</strong> bienestar de 5 a 25 (sueño, fatiga, estrés, ánimo y daño muscular,
            de 1 a 5 cada uno). Se marca cada ítem de {rules.wellness_low} o menos, las molestias por zona y los síntomas.</li>
          <li><strong>Último partido:</strong> minutos jugados y cuánto cambió su salto del día del partido al
            día siguiente. Si cae {Math.abs(rules.jump.grave_at)} % o más, es golpe fuerte (alerta); una caída
            menor es atención. Cuando ya saltó antes del partido siguiente, también se ve si recuperó.</li>
          <li><strong>Carga vs lo planificado:</strong> lo que hizo en la semana hasta hoy contra el objetivo de su
            posición (el % del día por la referencia de partido, como en Carga GPS), sumando solo los días en que
            tiene GPS. En rango hasta ±{lr.band_ok} %; hasta ±{lr.band_mild} %, atención; más allá, alerta.
            Se muestran las métricas fuera de rango. {lr.planned ? "" : "Esta semana no está planificada: sin plan no hay objetivo con qué comparar."}</li>
        </ul>
      </details>
    </>
  );
}

function Row({ r, planned }: { r: DayStatusRow; planned: boolean }) {
  const c = r.checkin, m = r.match, l = r.load;
  const outRow = r.status !== "available";
  return (
    <tr className={outRow ? own.outRow : undefined}>
      <th scope="row">
        <span className={own.who}>
          <Link href={`/perfil/${r.player_id}`}><PlayerName id={r.player_id} name={r.name}><strong>{r.name}</strong></PlayerName></Link>
          <span className={styles.muted}>{r.position}</span>
          {outRow && (
            <span className={own.injury}>
              <span className={`${styles.statusPill} ${styles[`status_${r.status}`]}`}>{r.status_label}</span>
              {r.injury && (
                <span className={styles.muted}>
                  {r.injury.body_part ?? r.injury.title}{r.injury.days_out != null && ` · día ${r.injury.days_out}`}
                </span>
              )}
            </span>
          )}
        </span>
      </th>
      <td>
        {!c ? <span className={styles.muted}>Sin check-in</span> : (
          <span className={own.cell}>
            <span><strong>{c.total ?? "—"}</strong><span className={styles.muted}>/25</span></span>
            {c.pain.map((z) => <Pill key={z} band="grave">Molestia: {z}</Pill>)}
            {c.symptoms.map((s) => <Pill key={s} band="leve">Síntoma: {s}</Pill>)}
            {c.lows.map((x) => <Pill key={x.key} band="leve">{x.label} {x.value}</Pill>)}
          </span>
        )}
      </td>
      <td>
        {!m ? <span className={styles.muted}>—</span> : (
          <span className={own.cell}>
            {m.minutes != null && <span>{m.minutes}&prime;</span>}
            {m.golpe_pct != null && (
              <Pill band={m.golpe_band} title="Cambio del salto: día del partido → día siguiente">
                Salto {pct(m.golpe_pct)}{m.golpe_band && m.golpe_band !== "ok" ? ` · ${BAND_WORD[m.golpe_band]}` : ""}
              </Pill>
            )}
            {m.llega_pct != null && (
              <Pill band={m.llega_band} title="Salto antes del partido siguiente vs. antes de este">
                Recuperó {pct(m.llega_pct)}
              </Pill>
            )}
          </span>
        )}
      </td>
      <td>
        {!planned ? <span className={styles.muted}>Semana sin planificar</span>
          : !l ? <span className={styles.muted}>Sin GPS esta semana</span> : (
          <span className={own.cell}>
            {l.off.length === 0
              ? <Pill band="ok">En rango</Pill>
              : l.off.map((m) => (
                <Pill key={m.key} band={m.band} title={`${m.label}: ${pct(m.pct)} vs lo planificado`}>
                  {m.short} {pct(m.pct)}
                </Pill>
              ))}
            <span className={styles.muted}>{l.days} de {l.days_planned} día{l.days_planned === 1 ? "" : "s"} con GPS</span>
          </span>
        )}
      </td>
    </tr>
  );
}
