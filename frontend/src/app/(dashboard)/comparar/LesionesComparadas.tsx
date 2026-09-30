"use client";

/**
 * "Lesiones" on /comparar: injury indicators side by side, one column per
 * player, computed in the browser from the injuries the page already loaded
 * for the rail (`lib/injuryStats.ts` holds the rules).
 *
 * The period follows the page's date range — a global control that viewing
 * surfaces must honour (AGENTS.md rule 5) — with an explicit switch to the
 * whole history, because injuries are sparse: a 60-day window is usually
 * empty, and "0 lesiones" there says nothing about the player.
 *
 * Which indicators show is a per-viewer preference kept in localStorage: it
 * changes the layout, not what the data means, so it does not belong in the
 * URL.
 */

import Link from "next/link";
import React, { useMemo, useState } from "react";

import { type InjuryRange, fmtDay, shortName } from "@/lib/injuryRanges";
import { type InjuryStats, SEVERE_DAYS, injuryStats } from "@/lib/injuryStats";
import type { ComparisonPlayer } from "@/lib/types";

import styles from "./page.module.css";
import own from "./LesionesComparadas.module.css";

type Alcance = "periodo" | "historia";
type Mejor = "down" | "up" | null;

interface Indicador {
  key: string;
  label: string;
  hint?: string;
  mejor: Mejor;
  /** Numeric value for highlighting the best, or null when it is text. */
  valor?: (s: InjuryStats) => number | null;
  render: (s: InjuryStats, playerId: string) => React.ReactNode;
  soloPeriodo?: boolean;
}

const INDICADORES: Indicador[] = [
  { key: "total", label: "Lesiones", hint: "iniciadas en el período", mejor: "down",
    valor: (s) => s.total, render: (s) => s.total },
  { key: "dias", label: "Días perdidos", hint: "dentro del período", mejor: "down",
    valor: (s) => s.diasPerdidos, render: (s) => s.diasPerdidos },
  { key: "disponibilidad", label: "Disponibilidad", hint: "días sin lesión", mejor: "up",
    soloPeriodo: true,
    valor: (s) => s.disponibilidad,
    render: (s) => (s.disponibilidad === null ? null : `${s.disponibilidad}%`) },
  { key: "promedio", label: "Días por lesión", mejor: "down",
    valor: (s) => s.promedio, render: (s) => s.promedio },
  { key: "severas", label: "Severas", hint: `más de ${SEVERE_DAYS} días`, mejor: "down",
    valor: (s) => s.severas, render: (s) => s.severas },
  { key: "musculares", label: "Musculares", mejor: "down",
    valor: (s) => s.musculares, render: (s) => s.musculares },
  { key: "recidivas", label: "Recidivas", mejor: "down",
    valor: (s) => s.recidivas, render: (s) => s.recidivas },
  { key: "zona", label: "Zona más lesionada", mejor: null,
    render: (s) => (s.porZona[0] ? `${s.porZona[0].nombre} · ${s.porZona[0].n}` : null) },
  { key: "porZona", label: "Por zona", mejor: null, render: (s) => <Barras filas={s.porZona} /> },
  { key: "tipo", label: "Tipo más frecuente", mejor: null,
    render: (s) => (s.porTipo[0] ? `${s.porTipo[0].nombre} · ${s.porTipo[0].n}` : null) },
  { key: "estado", label: "Estado actual", mejor: null,
    render: (s, id) => (s.abierta ? (
      <Link href={`/perfil/${id}?tab=lesiones`} className={own.lesionado}>
        {/* The stage already says "Lesionado — fase aguda"; only a stage-less
            episode needs the word. */}
        {s.abierta.stage_label
          ? `${shortName(s.abierta)} · ${s.abierta.stage_label}`
          : `Lesionado · ${shortName(s.abierta)}`}
      </Link>
    ) : <span className={own.disponible}>Disponible</span>) },
  { key: "ultima", label: "Última lesión", mejor: null,
    render: (s) => (s.ultima ? (
      <>
        {shortName(s.ultima)} · {fmtDay(s.ultima.started_at)}
        <span className={styles.n}> · hace {s.diasDesdeUltima} d</span>
      </>
    ) : null) },
];

const POR_DEFECTO = ["total", "dias", "disponibilidad", "severas", "zona", "porZona", "estado", "ultima"];
const STORAGE = "slab.comparar.lesiones";

function leerPreferencia(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(STORAGE) ?? "null");
    return Array.isArray(v) ? v.filter((k) => INDICADORES.some((i) => i.key === k)) : POR_DEFECTO;
  } catch {
    return POR_DEFECTO;
  }
}

function mejorIndice(valores: (number | null)[], mejor: Mejor): number {
  if (!mejor) return -1;
  const validos = valores.filter((v): v is number => v !== null);
  if (validos.length < 2) return -1;
  const objetivo = mejor === "down" ? Math.min(...validos) : Math.max(...validos);
  // A tie is not a winner: highlighting one of three zeros would be arbitrary.
  if (validos.filter((v) => v === objetivo).length > 1) return -1;
  return valores.indexOf(objetivo);
}

export default function LesionesComparadas({
  players, lesiones, desde, hasta, periodoLabel, colorDe,
}: {
  players: ComparisonPlayer[];
  lesiones: InjuryRange[];
  desde: string | null;
  hasta: string;
  periodoLabel: string;
  colorDe: (i: number) => string;
}) {
  const [alcance, setAlcance] = useState<Alcance>("periodo");
  const [claves, setClaves] = useState<string[]>(() =>
    typeof window === "undefined" ? POR_DEFECTO : leerPreferencia());
  const [configurando, setConfigurando] = useState(false);

  const desdeEfectivo = alcance === "periodo" ? desde : null;
  const stats = useMemo(
    () => players.map((p) =>
      injuryStats(lesiones.filter((l) => l.player_id === p.id), desdeEfectivo, hasta)),
    [players, lesiones, desdeEfectivo, hasta],
  );

  const visibles = INDICADORES.filter((i) =>
    claves.includes(i.key) && !(i.soloPeriodo && (alcance === "historia" || !desde)));

  const alternar = (k: string) => {
    const siguiente = claves.includes(k) ? claves.filter((x) => x !== k) : [...claves, k];
    setClaves(siguiente);
    try { localStorage.setItem(STORAGE, JSON.stringify(siguiente)); } catch { /* preferencia, no dato */ }
  };

  return (
    <>
      <div className={styles.seccionCab}>
        <h2 className={styles.seccionTitulo}>Lesiones</h2>
        <button type="button" className={styles.linkBtn} aria-expanded={configurando}
          onClick={() => setConfigurando((v) => !v)}>
          {configurando ? "Listo" : `Configurar (${claves.length})`}
        </button>
      </div>

      {configurando && (
        <div className={own.picker} role="group" aria-label="Indicadores de lesiones">
          {INDICADORES.map((i) => (
            <label key={i.key} className={own.opcion}>
              <input type="checkbox" checked={claves.includes(i.key)}
                onChange={() => alternar(i.key)} />
              {i.label}
            </label>
          ))}
        </div>
      )}

      <section className={styles.centro}>
        <div className={styles.switchRow}>
          <div className={styles.segmented} role="tablist" aria-label="Período de las lesiones">
            <button type="button" role="tab" aria-selected={alcance === "periodo"}
              className={alcance === "periodo" ? styles.segOn : styles.seg}
              onClick={() => setAlcance("periodo")}>{periodoLabel}</button>
            <button type="button" role="tab" aria-selected={alcance === "historia"}
              className={alcance === "historia" ? styles.segOn : styles.seg}
              onClick={() => setAlcance("historia")}>Toda la historia</button>
          </div>
        </div>

        {visibles.length === 0 ? (
          <p className={styles.vacio}>Elegí al menos un indicador en Configurar.</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Indicador</th>
                  {players.map((p, i) => (
                    <th key={p.id} style={{ color: colorDe(i) }}>{p.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibles.map((ind) => {
                  const mejor = ind.valor
                    ? mejorIndice(stats.map(ind.valor), ind.mejor) : -1;
                  return (
                    <tr key={ind.key}>
                      <th scope="row" className={styles.rowHead}>
                        {ind.label}
                        {ind.hint && (alcance === "periodo" || !ind.hint.includes("período")) && (
                          <span className={styles.unidad}> ({ind.hint})</span>
                        )}
                      </th>
                      {stats.map((s, i) => {
                        const contenido = ind.render(s, players[i].id);
                        return (
                          <td key={players[i].id} className={i === mejor ? styles.mejor : undefined}>
                            {contenido === null || contenido === undefined
                              ? <span className={styles.nulo}>—</span> : contenido}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className={own.nota}>
          Fuente: registro de lesiones del club. Se cuentan las lesiones iniciadas en
          el período; los días perdidos y la disponibilidad cuentan los días del
          período, aunque la lesión haya empezado antes.
        </p>
      </section>
    </>
  );
}

function Barras({ filas }: { filas: { nombre: string; n: number }[] }) {
  if (filas.length === 0) return null;
  const max = filas[0].n;
  return (
    <ul className={own.barras}>
      {filas.slice(0, 4).map((f) => (
        <li key={f.nombre}>
          <span className={own.barraNombre}>{f.nombre}</span>
          <span className={own.barra} style={{ width: `${(f.n / max) * 100}%` }} aria-hidden />
          <span className={own.barraN}>{f.n}</span>
        </li>
      ))}
      {filas.length > 4 && <li className={own.mas}>+{filas.length - 4} zonas</li>}
    </ul>
  );
}
