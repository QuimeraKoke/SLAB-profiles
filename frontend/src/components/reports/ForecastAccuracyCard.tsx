"use client";

import React, { useEffect, useState } from "react";
import { Target } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import styles from "./ForecastAccuracyCard.module.css";

interface Sample {
  player: string;
  title: string;
  first_expected: string;
  actual: string;
  error_days: number;
}
interface Payload {
  episodes: number;
  bias_days: number | null;
  mae_days: number | null;
  samples: Sample[];
}

interface Props {
  deptSlug: string;
  categoryId: string;
  dateFrom?: string;
  dateTo?: string;
}

function fmtDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-CL", { day: "numeric", month: "short" });
}

/** §3.2 — return-prognosis accuracy on the Médico report: signed bias
 *  (systematic optimism/pessimism) + MAE + the biggest misses. */
export default function ForecastAccuracyCard({ deptSlug, categoryId, dateFrom, dateTo }: Props) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
    });
    const p = new URLSearchParams({ category_id: categoryId });
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    api<Payload>(`/reports/${deptSlug}/forecast-accuracy?${p.toString()}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [deptSlug, categoryId, dateFrom, dateTo]);

  const bias = data?.bias_days ?? null;
  const biasNote =
    bias === null ? "" :
    bias > 1 ? "Pronósticos optimistas (retornos más tardíos)" :
    bias < -1 ? "Pronósticos pesimistas (retornos más tempranos)" :
    "Bien calibrados";

  return (
    <section className={styles.card}>
      <header className={styles.header}>
        <h3 className={styles.title}>
          <Target size={16} aria-hidden="true" /> Precisión de pronóstico de retorno
        </h3>
        <p className={styles.sub}>Retorno real vs. pronóstico al diagnóstico</p>
      </header>

      {loading ? (
        <div className={styles.muted}>Cargando…</div>
      ) : error ? (
        <div className={styles.muted}>{error}</div>
      ) : !data || data.episodes === 0 ? (
        <div className={styles.muted}>
          Sin episodios con pronóstico y retorno registrado en el período. Marcá
          &quot;Disponible para citar&quot; en los episodios para alimentar este KPI.
        </div>
      ) : (
        <>
          <div className={styles.stats}>
            <div className={styles.stat}>
              <span className={styles.statValue}>
                {bias! > 0 ? "+" : ""}{bias}<span className={styles.unit}> días</span>
              </span>
              <span className={styles.statLabel}>Sesgo</span>
              <span className={styles.statNote}>{biasNote}</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statValue}>
                {data.mae_days}<span className={styles.unit}> días</span>
              </span>
              <span className={styles.statLabel}>Error medio (MAE)</span>
              <span className={styles.statNote}>{data.episodes} episodio(s)</span>
            </div>
          </div>

          <table className={styles.table}>
            <thead>
              <tr>
                <th>Jugador</th>
                <th>Pronóstico</th>
                <th>Real</th>
                <th className={styles.right}>Desvío</th>
              </tr>
            </thead>
            <tbody>
              {data.samples.slice(0, 8).map((s, i) => (
                <tr key={i}>
                  <td>
                    <div className={styles.player}>{s.player}</div>
                    <div className={styles.epTitle}>{s.title}</div>
                  </td>
                  <td>{fmtDay(s.first_expected)}</td>
                  <td>{fmtDay(s.actual)}</td>
                  <td className={`${styles.right} ${s.error_days > 0 ? styles.late : s.error_days < 0 ? styles.early : ""}`}>
                    {s.error_days > 0 ? "+" : ""}{s.error_days} d
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
