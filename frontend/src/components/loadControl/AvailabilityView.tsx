"use client";

/**
 * Kinesia y lesiones — "¿Quién está en readaptación o clínica?" (question 5).
 * As the club's brief asks: the short list of players NOT available, a colour
 * per status (with its name — never colour alone), since when and the expected
 * return; then the season's injury history, folded. "Sin informes largos": the
 * detail lives in the player's Lesiones tab, one click away.
 */

import Link from "next/link";
import React, { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { type AvailabilityPayload, shortDate } from "@/lib/loadControl";

import styles from "./loadControl.module.css";
import { PlayerName } from "@/components/loadControl/PlayerPhotos";
import ScopeBadge from "./ScopeBadge";

const HISTORY_LIMIT = 8;

function returnText(days: number | null, expected: string | null) {
  if (!expected || days == null) return <span className={styles.muted}>Sin fecha estimada de retorno</span>;
  if (days < 0) return <span className={styles.overdue}>Retorno estimado {shortDate(expected)} · vencido hace {-days} día{days === -1 ? "" : "s"}</span>;
  if (days === 0) return <span>Retorno estimado <strong>hoy</strong></span>;
  return <span>Retorno estimado {shortDate(expected)} · faltan <strong>{days}</strong> día{days === 1 ? "" : "s"}</span>;
}

export default function AvailabilityView({ microcycleId, day }: { microcycleId: string; day?: string | null }) {
  const [data, setData] = useState<AvailabilityPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<AvailabilityPayload>(`/load-control/microcycles/${microcycleId}/availability${day ? `?day=${day}` : ""}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar la disponibilidad."); });
    return () => { cancelled = true; };
  }, [microcycleId, day]);

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <p className={styles.muted}>Cargando…</p>;

  const history = showAll ? data.history : data.history.slice(0, HISTORY_LIMIT);

  return (
    <>
      <section className={styles.card} aria-labelledby="av-sum">
        <div className={styles.cardHead}>
          <h2 id="av-sum" className={styles.h2}>Estado del plantel</h2>
          <span className={styles.cardMeta}><ScopeBadge kind="day" /> <span className={styles.muted}>{data.players} jugadores</span></span>
        </div>
        <div className={styles.countGrid}>
          {data.counts.map((c) => (
            <div key={c.status} className={`${styles.stat} ${styles[`status_${c.status}`]}`}>
              <span className={styles.statName}>{c.label}</span>
              <span className={styles.statPair}>{c.n}</span>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.card} aria-labelledby="av-out">
        <h2 id="av-out" className={styles.h2}>No disponibles ({data.unavailable.length})</h2>
        {data.unavailable.length === 0
          ? <p className={styles.muted}>Todo el plantel está disponible.</p>
          : data.unavailable.map((r) => {
            const e = r.episode;
            return (
              <div key={r.player_id} className={styles.outRow}>
                <span className={styles.playerName}>
                  <Link href={`/perfil/${r.player_id}?tab=lesiones`}><PlayerName id={r.player_id} name={r.name}><strong>{r.name}</strong></PlayerName></Link>
                  <span className={styles.muted}>{r.position}</span>
                </span>
                <span>{e ? e.title : <span className={styles.muted}>Sin episodio abierto registrado</span>}</span>
                <span>
                  <span className={`${styles.statusPill} ${styles[`status_${r.status}`]}`}>{r.status_label}</span>
                  {e && <span className={styles.muted}> · desde {shortDate(e.diagnosed_at)} ({e.days_out} días)</span>}
                </span>
                <span>{e ? returnText(e.days_to_return, e.expected_return) : null}</span>
              </div>
            );
          })}
      </section>

      <details className={styles.card}>
        <summary className={styles.h2} style={{ cursor: "pointer", minHeight: 28 }}>
          Historial de lesiones de la temporada ({data.history.length})
        </summary>
        {data.history.length === 0
          ? <p className={styles.muted}>Sin lesiones cerradas esta temporada.</p>
          : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr><th scope="col">Jugador</th><th scope="col">Lesión</th><th scope="col">Gravedad</th>
                    <th scope="col">Desde</th><th scope="col">Hasta</th><th scope="col">Días fuera</th></tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.episode_id}>
                      <th scope="row"><Link href={`/perfil/${h.player_id}?tab=lesiones`}><PlayerName id={h.player_id} name={h.name} /></Link></th>
                      <td style={{ textAlign: "left" }}>{h.title}</td>
                      <td style={{ textAlign: "left" }}>{h.severity ?? "—"}</td>
                      <td className={styles.num}>{shortDate(h.started)}</td>
                      <td className={styles.num}>{h.returned ? shortDate(h.returned) : "—"}</td>
                      <td className={styles.num}>{h.days_out ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {data.history.length > HISTORY_LIMIT && (
          <button type="button" className={styles.secondary} aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
            {showAll ? "Ver menos" : `Ver ${data.history.length - HISTORY_LIMIT} lesiones más`}
          </button>
        )}
      </details>

      <p className={styles.provenance}>
        Datos usados: estado actual de cada jugador del equipo y su episodio de lesión abierto más reciente
        (el mismo que muestra el Daily). Días fuera desde el diagnóstico; el retorno es la fecha estimada que cargó
        el cuerpo médico. Historial: lesiones cerradas que empezaron esta temporada.
      </p>
    </>
  );
}
