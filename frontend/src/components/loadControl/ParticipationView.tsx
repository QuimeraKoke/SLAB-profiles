"use client";

/**
 * Minutos y entrenamientos — "¿Cuánto jugó y a cuántas sesiones fue?" (question 6).
 * Never "asistencia": in football that is the pass for a goal (COMET even has
 * an `asistencias` field), so the staff read it wrong. Here it is "entrenamientos".
 *
 * why someone carries little load. One row per player with simple bars —
 * minutes (and % of the team's minutes) and attendance — and a red light only
 * where there is a problem, once the club sets its attendance threshold.
 */

import Link from "next/link";
import React, { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { fmt, type ParticipationPayload, shortDate } from "@/lib/loadControl";

import styles from "./loadControl.module.css";
import { PlayerName } from "@/components/loadControl/PlayerPhotos";
import ScopeBadge from "./ScopeBadge";

const LIMIT = 15;

interface Props {
  microcycleId: string;
}

function Bar({ pct, low }: { pct: number | null; low?: boolean }) {
  return (
    <span className={styles.barTrack} aria-hidden="true">
      <span className={`${styles.barFill} ${low ? styles.barFillLow : ""}`}
        style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%`, display: "block" }} />
    </span>
  );
}

export default function ParticipationView({ microcycleId }: Props) {
  const [data, setData] = useState<ParticipationPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<ParticipationPayload>(`/load-control/microcycles/${microcycleId}/participation?scope=microcycle`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar minutos y entrenamientos."); });
    return () => { cancelled = true; };
  }, [microcycleId]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <p className={styles.muted}>Cargando…</p>;

  const comet = data.matches.filter((m) => m.source === "comet").length;
  const gps = data.matches.length - comet;
  const perMatch = data.scope === "microcycle" && data.matches.length > 0 && data.matches.length <= 4;
  const rows = showAll ? data.rows : data.rows.slice(0, LIMIT);

  return (
    <>
      <section className={styles.card} aria-labelledby="pa-t">
        <div className={styles.cardHead}>
          <h2 id="pa-t" className={styles.h2}>Minutos y entrenamientos por jugador ({data.rows.length})</h2>
          <span className={styles.cardMeta}><ScopeBadge kind="period" /></span>
        </div>
        <p className={styles.muted} style={{ margin: "0 0 8px" }}>
          {data.matches.length} partido{data.matches.length === 1 ? "" : "s"} · {data.sessions} sesiones del equipo
          {" "}({shortDate(data.start)} – {shortDate(data.end)}) · ordenados por minutos jugados
          {data.matches.length > 4 && " · el detalle por partido aparece con 4 partidos o menos"}
        </p>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Jugador</th>
                {perMatch && data.matches.map((m) => (
                  <th key={m.date} scope="col" title={m.source === "gps" ? "Minutos del GPS (sin ficha COMET)" : "Ficha COMET"}>
                    {shortDate(m.date)}{m.opponent ? ` · ${m.opponent}` : ""}{m.source === "gps" ? " (GPS)" : ""}
                  </th>
                ))}
                <th scope="col" style={{ textAlign: "left" }}>Minutos</th>
                <th scope="col">Convocado · titular</th>
                <th scope="col" style={{ textAlign: "left" }}>Entrenamientos</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.player_id}>
                  <th scope="row">
                    <Link href={`/perfil/${r.player_id}`}><PlayerName id={r.player_id} name={r.name} /></Link>
                    {r.status !== "available" && (
                      <> <span className={`${styles.statusPill} ${styles[`status_${r.status}`]}`}>{r.status_label}</span></>
                    )}
                  </th>
                  {perMatch && r.matches.map((m, i) => (
                    <td key={data.matches[i].date} className={styles.num}>{m == null ? "—" : `${m.minutes}′`}</td>
                  ))}
                  <td>
                    <span className={styles.barCell}>
                      <span className={styles.num}>{fmt(r.minutes)} min{r.minutes_pct != null ? ` · ${r.minutes_pct}%` : ""}</span>
                      <Bar pct={r.minutes_pct} />
                    </span>
                  </td>
                  <td className={styles.num}>{r.called_up} · {r.starts}</td>
                  <td>
                    <span className={styles.barCell}>
                      <span className={styles.num}>
                        {r.sessions_attended}/{data.sessions}{r.attendance_pct != null ? ` · ${r.attendance_pct}%` : ""}
                        {r.attendance_low && <strong className={styles.overdue}> · pocos entrenamientos</strong>}
                      </span>
                      <Bar pct={r.attendance_pct} low={r.attendance_low} />
                      {r.sessions_attended > 0 && (
                        <span className={styles.muted} style={{ fontSize: "0.72rem" }}>
                          {r.sessions_gps} con GPS{r.sessions_form_only ? ` · ${r.sessions_form_only} sólo con formulario` : ""}
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.rows.length > LIMIT && (
          <button type="button" className={styles.secondary} aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Ver menos" : `Ver ${data.rows.length - LIMIT} jugadores más`}
          </button>
        )}
      </section>

      <p className={styles.provenance}>
        Datos usados: partidos del equipo — {comet} con ficha COMET (minutos oficiales){gps ? ` y ${gps} sin ficha, con los minutos del GPS del partido (tope ${data.match_minutes})` : ""}.
        % de minutos = minutos ÷ ({data.match_minutes} × partidos del período). Entrenamientos = sesiones del equipo (días con GPS de
        entrenamiento de al menos {data.session_min_players} jugadores; los partidos oficiales y amistosos no son sesión) en las
        que el jugador tiene cualquier señal: GPS de entrenamiento de cualquier fuente (su equipo, sparring, Primer Equipo) o
        el check-in / check-out de ese día.
        {data.attendance_low_pct == null
          ? " Sin semáforo de entrenamientos: falta que el club defina el umbral."
          : ` Pocos entrenamientos = menos de ${data.attendance_low_pct}% de las sesiones.`}
        {" "}Titular sólo se sabe por la ficha COMET.
      </p>
    </>
  );
}
