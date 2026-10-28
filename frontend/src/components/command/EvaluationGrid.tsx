"use client";

/**
 * Evaluaciones físicas: one row per player, one column per test grouped like
 * the club's sheet (Fuerza, Neuromuscular, Carrera, Cambio de dirección,
 * Resistencia). Each cell is the player's LAST reading, with a dot in the
 * colour of the category's band it falls in.
 *
 * Two views (`?eval=resumen` | detalle): the summary collapses each group to
 * the mean band level of its tests (1 = Muy deficiente … 7 = Elite — seconds,
 * centimetres and kilos only average once they are levels) plus an overall
 * one. Every column sorts (`?eval_orden=<key>:<asc|desc>`); the first click
 * puts the best on top. A last row gives the category's mean.
 *
 * Renders nothing for a category without bands (the Primer Equipo): its
 * Centro de mando stays as it was.
 */

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, Gauge } from "lucide-react";

import { api } from "@/lib/api";
import type { CCEvalCell, CCEvalColumn, CCEvalScore, CCEvaluationGrid } from "./types";
import styles from "./EvaluationGrid.module.css";

/** A reading older than this is shown faded: still the last one, but stale. */
const DIAS_VIGENTE = 180;

type Row = CCEvaluationGrid["rows"][number];
type Orden = { key: string; dir: "asc" | "desc" };

export default function EvaluationGrid({ categoryId }: { categoryId: string }) {
  const [data, setData] = useState<CCEvaluationGrid | null>(null);
  const [now] = useState(() => Date.now());
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const resumen = params.get("eval") === "resumen";
  const orden = parseOrden(params.get("eval_orden"));

  useEffect(() => {
    let cancelled = false;
    api<CCEvaluationGrid>(`/command-center/evaluations?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setData(d); })
      // Secondary card: a failure leaves the rest of the page usable.
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [categoryId]);

  const write = (patch: Record<string, string | null>) => {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v) sp.set(k, v);
      else sp.delete(k);
    }
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  // First click: best on top (desc — levels and, for "down" tests, the
  // tie-break already flips). Second: the other way. Third: back to roster order.
  const sortBy = (key: string) => {
    if (orden?.key !== key) write({ eval_orden: `${key}:desc` });
    else if (orden.dir === "desc") write({ eval_orden: `${key}:asc` });
    else write({ eval_orden: null });
  };

  const columns = useMemo(() => data?.groups.flatMap((g) => g.columns) ?? [], [data]);
  const rows = useMemo(() => {
    if (!data) return [];
    if (!orden) return data.rows;
    if (orden.key === "name") {
      // First click (desc) reads A→Z, the order people expect first.
      const az = [...data.rows].sort((a, b) => a.name.localeCompare(b.name, "es"));
      return orden.dir === "desc" ? az : az.reverse();
    }
    const col = columns.find((c) => c.key === orden.key);
    const key = (r: Row) => sortKey(r, orden.key, col);
    // Players without the value go last, whichever the direction.
    return [...data.rows].sort((a, b) => {
      const ka = key(a), kb = key(b);
      if (ka === null && kb === null) return 0;
      if (ka === null) return 1;
      if (kb === null) return -1;
      const d = ka[0] - kb[0] || ka[1] - kb[1];
      return orden.dir === "desc" ? -d : d;
    });
  }, [data, orden, columns]);

  if (!data || data.groups.length === 0) return null;

  const legendFor = (score: CCEvalScore | null | undefined) =>
    score ? data.legend[Math.min(data.legend.length, Math.max(1, Math.round(score.value))) - 1]
      : undefined;

  const head = (key: string, label: React.ReactNode, cls: string, title?: string) => {
    const on = orden?.key === key;
    const Icon = !on ? ArrowUpDown : orden.dir === "desc" ? ArrowDown : ArrowUp;
    return (
      <th key={key} scope="col" className={cls}
        aria-sort={on ? (orden.dir === "desc" ? "descending" : "ascending") : "none"}>
        <button type="button" className={styles.sortBtn} onClick={() => sortBy(key)}
          title={title ?? "Ordenar"}>
          {label}
          <Icon size={11} aria-hidden="true" className={on ? styles.sortOn : styles.sortIcon} />
        </button>
      </th>
    );
  };

  // Category means, over the players who have the value.
  const media = (vals: (number | null | undefined)[]) => {
    const v = vals.filter((x): x is number => typeof x === "number");
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };

  return (
    <section className={styles.card} aria-labelledby="eval-grid-title">
      <div className={styles.head}>
        <Gauge size={16} aria-hidden="true" />
        <div className={styles.headText}>
          <div id="eval-grid-title" className={styles.title}>Evaluaciones físicas</div>
          <div className={styles.subtitle}>
            {resumen
              ? "Nivel promedio por cualidad · 1 = Muy deficiente … 7 = Elite"
              : "Último test de cada jugador, según las bandas de la categoría"}
          </div>
        </div>
        <div className={styles.toggle} role="group" aria-label="Vista">
          {([["resumen", "Resumen"], ["detalle", "Detalle"]] as const).map(([v, label]) => (
            <button key={v} type="button" aria-pressed={resumen === (v === "resumen")}
              className={resumen === (v === "resumen") ? styles.toggleOn : styles.toggleBtn}
              onClick={() => write({ eval: v === "resumen" ? "resumen" : null, eval_orden: null })}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <ul className={styles.legend} aria-label="Bandas">
        {data.legend.map((b, i) => (
          <li key={b.label}>
            <span className={styles.dot} style={{ background: b.color }} aria-hidden="true" />
            {resumen ? `${i + 1} · ` : ""}{b.label}
          </li>
        ))}
        {!resumen && <li className={styles.legendStale}>Atenuado: test de hace más de 6 meses</li>}
      </ul>

      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            {resumen ? (
              <tr>
                {head("name", "Jugador", `${styles.sticky} ${styles.playerHead}`, "Ordenar por nombre")}
                {data.groups.map((g) => head(`g:${g.name}`, g.name, `${styles.col} ${styles.groupStart}`))}
                {head("overall", "Promedio", `${styles.col} ${styles.groupStart} ${styles.overallHead}`)}
              </tr>
            ) : (
              <>
                <tr>
                  <th rowSpan={2} className={`${styles.sticky} ${styles.playerHead}`} scope="col"
                    aria-sort={orden?.key === "name" ? (orden.dir === "desc" ? "descending" : "ascending") : "none"}>
                    <button type="button" className={styles.sortBtn} onClick={() => sortBy("name")}>
                      Jugador
                    </button>
                  </th>
                  {data.groups.map((g) => (
                    <th key={g.name} colSpan={g.columns.length} scope="colgroup" className={styles.group}>
                      {g.name}
                    </th>
                  ))}
                </tr>
                <tr>
                  {data.groups.map((g) => g.columns.map((c, i) => head(
                    c.key,
                    <>{c.label}<span className={styles.unit}>{c.unit}</span></>,
                    `${styles.col} ${i === 0 ? styles.groupStart : ""}`,
                  )))}
                </tr>
              </>
            )}
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.player_id}>
                <th scope="row" className={styles.sticky}>
                  <Link href={`/perfil/${r.player_id}?tab=fisico`} className={styles.player}>
                    {r.name}
                  </Link>
                  {r.position && <span className={styles.position}>{r.position}</span>}
                </th>
                {resumen ? (
                  <>
                    {data.groups.map((g) => (
                      <Score key={g.name} score={r.groups[g.name]} band={legendFor(r.groups[g.name])} />
                    ))}
                    <Score score={r.overall} band={legendFor(r.overall)} strong />
                  </>
                ) : data.groups.map((g) => g.columns.map((c, i) => (
                  <Cell key={c.key} cell={r.cells[c.key]} now={now} first={i === 0} unit={c.unit} />
                )))}
              </tr>
            ))}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr className={styles.footRow}>
                <th scope="row" className={styles.sticky}>Promedio categoría</th>
                {resumen ? (
                  <>
                    {data.groups.map((g) => {
                      const m = media(rows.map((r) => r.groups[g.name]?.value));
                      const s = m === null ? null : { value: m, n: 0 };
                      return <Score key={g.name} score={s} band={legendFor(s)} />;
                    })}
                    {(() => {
                      const m = media(rows.map((r) => r.overall?.value));
                      const s = m === null ? null : { value: m, n: 0 };
                      return <Score score={s} band={legendFor(s)} strong />;
                    })()}
                  </>
                ) : data.groups.map((g) => g.columns.map((c, i) => {
                  const m = media(rows.map((r) => r.cells[c.key]?.value));
                  return (
                    <td key={c.key} className={`${styles.cell} ${i === 0 ? styles.groupStart : ""}`}>
                      {m === null ? <span className={styles.none}>—</span> : fmt(m)}
                    </td>
                  );
                }))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {data.rows.length === 0 && (
        <p className={styles.empty}>La categoría no tiene jugadores.</p>
      )}
    </section>
  );
}

function parseOrden(raw: string | null): Orden | null {
  if (!raw) return null;
  const i = raw.lastIndexOf(":");
  const key = raw.slice(0, i), dir = raw.slice(i + 1);
  return key && (dir === "asc" || dir === "desc") ? { key, dir } : null;
}

/** [primary, tie-break] — larger is better in both, so "desc" = best first. */
function sortKey(r: Row, key: string, col: CCEvalColumn | undefined): [number, number] | null {
  if (key === "overall") return r.overall ? [r.overall.value, r.overall.n] : null;
  if (key.startsWith("g:")) {
    const s = r.groups[key.slice(2)];
    return s ? [s.value, s.n] : null;
  }
  const c = r.cells[key];
  if (!c) return null;
  const tie = col?.direction === "down" ? -c.value : c.value;
  return [c.level ?? 0, tie];
}

function Score({ score, band, strong }: {
  score: CCEvalScore | null | undefined;
  band: { label: string; color: string } | undefined;
  strong?: boolean;
}) {
  const cls = `${styles.cell} ${styles.groupStart} ${strong ? styles.overallCell : ""}`;
  if (!score) return <td className={cls}><span className={styles.none} aria-label="Sin tests">—</span></td>;
  const titulo = `${band?.label ?? ""}${score.n ? ` · ${score.n} test${score.n === 1 ? "" : "s"}` : ""}`;
  return (
    <td className={cls} title={titulo}>
      <span className={styles.value}>
        <span className={styles.dot} style={{ background: band?.color ?? "transparent" }} aria-hidden="true" />
        {score.value.toLocaleString("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
        <span className={styles.srOnly}>{` ${titulo}`}</span>
      </span>
    </td>
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
