"use client";

/**
 * Team injury widgets — the renderers for `dashboards/team_injuries.py`.
 *
 * Three chart types share this file because they share their vocabulary
 * (period, empty state, the injury ink):
 *
 * * `team_injury_kpis`      — headline strip.
 * * `team_injury_list`      — injuries as a table (open, or all in the period).
 * * `team_injury_breakdown` — injuries by a dimension, as bars, donut or table.
 *
 * Colour: a breakdown by bars is ONE series, so it takes one colour — the
 * injury ink the charts already use for injuries. A donut is categorical: the
 * validated slots in fixed order, "Sin dato" in neutral gray (never a hue),
 * and the legend always lists label + value, because three of the slots sit
 * below 3:1 on white and a legend with numbers is the relief that requires.
 */

import Link from "next/link";
import React from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type {
  TeamInjuryBreakdownPayload,
  TeamInjuryColumn,
  TeamInjuryKpisPayload,
  TeamInjuryListPayload,
  TeamReportWidget,
} from "@/lib/types";

import styles from "./TeamInjuries.module.css";

const INK = "#9a5b5b";
const NEUTRAL = "#b8b7b1";
/** Categorical slots, fixed order (dataviz reference palette, validated on white). */
const SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function periodo(p: { from: string | null; to: string }): string {
  return p.from ? `${fmtDate(p.from)} – ${fmtDate(p.to)}` : `hasta ${fmtDate(p.to)}`;
}

function Header({ widget, sub }: { widget: TeamReportWidget; sub?: string }) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {(widget.description || sub) && (
          <p className={styles.description}>{widget.description || sub}</p>
        )}
      </div>
    </header>
  );
}

// ── headline ─────────────────────────────────────────────────────────────
export function TeamInjuryKpis({ widget }: { widget: TeamReportWidget }) {
  const d = widget.data as TeamInjuryKpisPayload;
  const tiles: { label: string; value: string; hint?: string; strong?: boolean }[] = [
    { label: "Lesionados hoy", value: String(d.injured_now), strong: d.injured_now > 0,
      hint: d.open_injuries !== d.injured_now ? `${d.open_injuries} lesiones abiertas` : `de ${d.roster_size}` },
    { label: "Lesiones en el período", value: String(d.injuries),
      hint: `${d.players_injured} jugadores` },
    { label: "Días perdidos", value: d.days_lost.toLocaleString("es-CL") },
    { label: "Días por lesión", value: d.avg_days === null ? "—" : String(d.avg_days) },
    { label: "Severas", value: String(d.severe), hint: "más de 28 días" },
    { label: "Recidivas", value: d.recurrence_pct === null ? "—" : `${d.recurrence_pct}%` },
  ];
  return (
    <div className={styles.widget}>
      <Header widget={widget} sub={periodo(d.period)} />
      <div className={styles.kpis}>
        {tiles.map((t) => (
          <div key={t.label} className={`${styles.kpi} ${t.strong ? styles.kpiStrong : ""}`}>
            <span className={styles.kpiValue}>{t.value}</span>
            <span className={styles.kpiLabel}>{t.label}</span>
            {t.hint && <span className={styles.kpiHint}>{t.hint}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── list ─────────────────────────────────────────────────────────────────
const HEAD: Record<TeamInjuryColumn, string> = {
  player: "Jugador", started: "Fecha de lesión", ended: "Alta", diagnosis: "Diagnóstico",
  lado: "Lateralidad", days: "Días", tratamiento: "Tratamiento", recurrencia: "Recurrencia",
  body_part: "Región", type: "Tipo", modo: "Causa", severity: "Severidad", stage: "Etapa",
};
const NUMERIC: TeamInjuryColumn[] = ["days"];

export function TeamInjuryList({ widget }: { widget: TeamReportWidget }) {
  const d = widget.data as TeamInjuryListPayload;
  const sub = d.status === "open"
    ? `${d.rows.length} lesiones abiertas hoy`
    : `${d.rows.length} lesiones iniciadas · ${periodo(d.period)}`;
  return (
    <div className={styles.widget}>
      <Header widget={widget} sub={sub} />
      {d.rows.length === 0 ? (
        <div className={styles.empty}>
          {d.status === "open" ? "Nadie lesionado hoy." : "Sin lesiones en el período."}
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                {d.columns.map((c) => (
                  <th key={c} className={NUMERIC.includes(c) ? styles.num : undefined}>{HEAD[c]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.id} className={r.open && d.status === "period" ? styles.open : undefined}>
                  {d.columns.map((c) => (
                    <td key={c} className={NUMERIC.includes(c) ? styles.num : undefined}>
                      {cell(r, c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function cell(r: TeamInjuryListPayload["rows"][number], c: TeamInjuryColumn): React.ReactNode {
  switch (c) {
    case "player":
      return (
        <Link href={`/perfil/${r.player_id}?tab=lesiones`} className={styles.player}>
          {r.player}
        </Link>
      );
    case "started":
      return fmtDate(r.started);
    case "ended":
      return r.ended ? fmtDate(r.ended) : <span className={styles.enCurso}>en curso</span>;
    case "days":
      return r.open ? <span className={styles.enCurso}>{r.days}</span> : r.days;
    case "lado":
      return r.lado === "NA" ? "No aplica" : r.lado;
    default:
      return r[c] || <span className={styles.nulo}>—</span>;
  }
}

// ── breakdown ────────────────────────────────────────────────────────────
export function TeamInjuryBreakdown({ widget }: { widget: TeamReportWidget }) {
  const d = widget.data as TeamInjuryBreakdownPayload;
  const sub = `${d.measure_label} por ${d.dimension_label.toLowerCase()} · ${periodo(d.period)}`;
  if (d.items.length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} sub={sub} />
        <div className={styles.empty}>Sin lesiones en el período.</div>
      </div>
    );
  }
  return (
    <div className={styles.widget}>
      <Header widget={widget} sub={sub} />
      {d.render === "donut" ? <Donut d={d} /> : d.render === "table" ? <Tabla d={d} /> : <Barras d={d} />}
    </div>
  );
}

const unidad = (d: TeamInjuryBreakdownPayload, v: number) =>
  d.measure === "days" ? `${v} d` : String(v);

function Barras({ d }: { d: TeamInjuryBreakdownPayload }) {
  const max = Math.max(...d.items.map((i) => i.value));
  return (
    <ul className={styles.bars} aria-label={`${d.measure_label} por ${d.dimension_label}`}>
      {d.items.map((i) => {
        const nombre = d.dimension === "player" && i.player_id ? (
          <Link href={`/perfil/${i.player_id}?tab=lesiones`} className={styles.player}>{i.label}</Link>
        ) : i.label;
        return (
          <li key={i.label} className={styles.barRow}
            title={`${i.label}: ${unidad(d, i.value)}${d.measure === "days" ? ` · ${i.n} lesiones` : ""}`}>
            <span className={styles.barLabel}>{nombre}</span>
            <span className={styles.barTrack}>
              <span className={styles.bar}
                style={{ width: `${(i.value / max) * 100}%`, background: i.label === "Sin dato" ? NEUTRAL : INK }} />
            </span>
            <span className={styles.barValue}>{unidad(d, i.value)}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Donut({ d }: { d: TeamInjuryBreakdownPayload }) {
  // Slots advance only for real categories: "Sin dato" / "Otros" are gray and
  // must not shift the colour of the categories after them.
  let slot = 0;
  const datos = d.items.map((i) => {
    const neutro = i.label === "Sin dato" || i.label.startsWith("Otros");
    return { ...i, color: neutro ? NEUTRAL : SLOTS[slot++ % SLOTS.length] };
  });
  return (
    <div className={styles.donutWrap}>
      <div className={styles.donut}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={datos} dataKey="value" nameKey="label" innerRadius="58%" outerRadius="92%"
              stroke="#ffffff" strokeWidth={2} isAnimationActive={false}>
              {datos.map((i) => <Cell key={i.label} fill={i.color} />)}
            </Pie>
            <Tooltip content={({ active, payload }) => {
              const p = active && payload?.[0]?.payload as (typeof datos)[number] | undefined;
              if (!p) return null;
              return (
                <div className={styles.tooltip}>
                  <strong>{p.label}</strong> · {unidad(d, p.value)} · {Math.round((p.value / d.total) * 100)}%
                </div>
              );
            }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className={styles.legend}>
        {datos.map((i) => (
          <li key={i.label}>
            <span className={styles.swatch} style={{ background: i.color }} aria-hidden />
            <span className={styles.legendLabel}>{i.label}</span>
            <span className={styles.legendValue}>
              {unidad(d, i.value)} <span className={styles.pct}>{Math.round((i.value / d.total) * 100)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Tabla({ d }: { d: TeamInjuryBreakdownPayload }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr><th>{d.dimension_label}</th><th className={styles.num}>{d.measure_label}</th><th className={styles.num}>%</th></tr>
        </thead>
        <tbody>
          {d.items.map((i) => (
            <tr key={i.label}>
              <td>{i.label}</td>
              <td className={styles.num}>{unidad(d, i.value)}</td>
              <td className={styles.num}>{Math.round((i.value / d.total) * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
