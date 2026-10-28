"use client";

/**
 * Evaluaciones físicas: one row per player, one column per test grouped like
 * the club's sheet (Fuerza, Neuromuscular, Carrera, Cambio de dirección,
 * Resistencia). Each cell is the player's LAST reading, with a dot in the
 * colour of the category's band it falls in.
 *
 * Renders nothing for a category without bands (the Primer Equipo): its
 * Centro de mando stays as it was.
 */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Gauge } from "lucide-react";

import { api } from "@/lib/api";
import type { CCEvalCell, CCEvaluationGrid } from "./types";
import styles from "./EvaluationGrid.module.css";

/** A reading older than this is shown faded: still the last one, but stale. */
const DIAS_VIGENTE = 180;

export default function EvaluationGrid({ categoryId }: { categoryId: string }) {
  const [data, setData] = useState<CCEvaluationGrid | null>(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    api<CCEvaluationGrid>(`/command-center/evaluations?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setData(d); })
      // Secondary card: a failure leaves the rest of the page usable.
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [categoryId]);

  if (!data || data.groups.length === 0) return null;

  return (
    <section className={styles.card} aria-labelledby="eval-grid-title">
      <div className={styles.head}>
        <Gauge size={16} aria-hidden="true" />
        <div>
          <div id="eval-grid-title" className={styles.title}>Evaluaciones físicas</div>
          <div className={styles.subtitle}>
            Último test de cada jugador, según las bandas de la categoría
          </div>
        </div>
      </div>

      <ul className={styles.legend} aria-label="Bandas">
        {data.legend.map((b) => (
          <li key={b.label}>
            <span className={styles.dot} style={{ background: b.color }} aria-hidden="true" />
            {b.label}
          </li>
        ))}
        <li className={styles.legendStale}>Atenuado: test de hace más de 6 meses</li>
      </ul>

      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th rowSpan={2} className={`${styles.sticky} ${styles.playerHead}`} scope="col">
                Jugador
              </th>
              {data.groups.map((g) => (
                <th key={g.name} colSpan={g.columns.length} scope="colgroup"
                  className={styles.group}>
                  {g.name}
                </th>
              ))}
            </tr>
            <tr>
              {data.groups.map((g) => g.columns.map((c, i) => (
                <th key={c.key} scope="col"
                  className={`${styles.col} ${i === 0 ? styles.groupStart : ""}`}>
                  {c.label}
                  <span className={styles.unit}>{c.unit}</span>
                </th>
              )))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.player_id}>
                <th scope="row" className={styles.sticky}>
                  <Link href={`/perfil/${r.player_id}?tab=fisico`} className={styles.player}>
                    {r.name}
                  </Link>
                  {r.position && <span className={styles.position}>{r.position}</span>}
                </th>
                {data.groups.map((g) => g.columns.map((c, i) => (
                  <Cell key={c.key} cell={r.cells[c.key]} now={now}
                    first={i === 0} unit={c.unit} />
                )))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.rows.length === 0 && (
        <p className={styles.empty}>La categoría no tiene jugadores.</p>
      )}
    </section>
  );
}

function Cell({ cell, now, first, unit }: {
  cell: CCEvalCell | undefined;
  now: number;
  first: boolean;
  unit: string;
}) {
  const cls = `${styles.cell} ${first ? styles.groupStart : ""}`;
  if (!cell) {
    return <td className={cls}><span className={styles.none} aria-label="Sin test">—</span></td>;
  }
  const dias = (now - new Date(cell.date).getTime()) / 86_400_000;
  const vieja = dias > DIAS_VIGENTE;
  const titulo = `${cell.band ?? "Sin banda"} · ${fmtFecha(cell.date)}`;
  return (
    <td className={cls} title={titulo}>
      <span className={`${styles.value} ${vieja ? styles.stale : ""}`}>
        <span className={styles.dot}
          style={{ background: cell.color ?? "transparent" }} aria-hidden="true" />
        {fmt(cell.value)}
        <span className={styles.srOnly}>{` ${unit}, ${titulo}`}</span>
      </span>
    </td>
  );
}

function fmt(v: number): string {
  return v.toLocaleString("es-CL", { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2 });
}

function fmtFecha(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
