"use client";

/**
 * `team_gauge` — one metric's latest value on a half-circle arc that runs
 * from the squad's lowest to its highest latest value, coloured with the
 * club's bands for the category. The needle is the squad mean, or one
 * player's own value when the report is filtered to that player.
 */

import React, { useMemo, useState } from "react";

import { bandColor, findBandForValue, formatBandRange } from "@/lib/reference";
import type { ReferenceBand, TeamGaugePayload, TeamReportWidget } from "@/lib/types";
import styles from "./TeamGauge.module.css";

interface Props {
  widget: TeamReportWidget;
}

const CX = 120;
const CY = 118;
const R = 92;
const STROKE = 18;
const TRACK = "#e5e7eb";

/** Point on the arc for t ∈ [0, 1] (0 = left end, 1 = right end). */
function polar(t: number, r = R): [number, number] {
  const a = Math.PI * (1 - t);
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
}

function arcPath(t0: number, t1: number): string {
  const [x0, y0] = polar(t0);
  const [x1, y1] = polar(t1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${R} ${R} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function fmt(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) >= 100 ? 1 : 2);
}

export default function TeamGauge({ widget }: Props) {
  const data = widget.data as TeamGaugePayload;
  const fields = useMemo(() => data.fields ?? [], [data.fields]);
  const [picked, setPicked] = useState<string | null>(null);
  const field = fields.find((f) => f.key === (picked ?? data.default_field_key)) ?? fields[0] ?? null;

  const geom = useMemo(() => {
    if (!field || field.value === null || field.min === null || field.max === null) return null;
    let lo = Math.min(field.min, field.value);
    let hi = Math.max(field.max, field.value);
    if (hi - lo < 1e-9) {
      const pad = Math.abs(lo) * 0.05 || 1;
      lo -= pad;
      hi += pad;
    }
    const t = (v: number) => Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
    const segments: { band: ReferenceBand; t0: number; t1: number }[] = [];
    for (const band of field.bands ?? []) {
      const a = Math.max(lo, typeof band.min === "number" ? band.min : -Infinity);
      const b = Math.min(hi, typeof band.max === "number" ? band.max : Infinity);
      if (b > a) segments.push({ band, t0: t(a), t1: t(b) });
    }
    return { needle: t(field.value), segments };
  }, [field]);

  const header = (
    <header className={styles.header}>
      <div>
        <h3 className={styles.title}>{widget.title}</h3>
        {widget.description && <p className={styles.description}>{widget.description}</p>}
      </div>
      {fields.length > 1 ? (
        <label className={styles.selectLabel}>
          <span className={styles.selectHint}>Métrica</span>
          <select className={styles.select} value={field?.key ?? ""}
            onChange={(e) => setPicked(e.target.value)}>
            {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </label>
      ) : field ? (
        <span className={styles.tag}>{field.label}</span>
      ) : null}
    </header>
  );

  if (data.error || !field || !geom || field.value === null) {
    return (
      <div className={styles.widget}>
        {header}
        <div className={styles.empty}>{data.error ?? "Sin datos en el período."}</div>
      </div>
    );
  }

  const unit = field.unit ? ` ${field.unit}` : "";
  const band = findBandForValue(field.value, field.bands);
  const [nx, ny] = polar(geom.needle, R - STROKE / 2 - 6);
  const visibles = geom.segments.map((s) => s.band);
  const who = field.subject ?? `Media del plantel · ${field.n} jugador${field.n === 1 ? "" : "es"}`;

  return (
    <div className={styles.widget}>
      {header}
      <svg viewBox="0 0 240 172" className={styles.svg} role="img"
        aria-label={`${field.label}: ${fmt(field.value)}${unit}${band ? ` (${band.label})` : ""}. `
          + `${who}. Rango del plantel ${fmt(field.min!)} a ${fmt(field.max!)}${unit}.`}>
        <path d={arcPath(0, 1)} fill="none" stroke={TRACK} strokeWidth={STROKE} />
        {geom.segments.map((s, i) => (
          <path key={i} d={arcPath(s.t0, s.t1)} fill="none" stroke={bandColor(s.band)}
            strokeWidth={STROKE} opacity={0.85} />
        ))}
        {/* 2px surface gaps between band segments. */}
        {geom.segments.slice(1).map((s, i) => {
          const [x0, y0] = polar(s.t0, R - STROKE / 2 - 1);
          const [x1, y1] = polar(s.t0, R + STROKE / 2 + 1);
          return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} stroke="#ffffff" strokeWidth={2} />;
        })}
        <line x1={CX} y1={CY} x2={nx} y2={ny} stroke="#1d2939" strokeWidth={2.5} strokeLinecap="round" />
        <circle cx={CX} cy={CY} r={5} fill="#1d2939" stroke="#ffffff" strokeWidth={2} />
        <text x={polar(0)[0]} y={CY + 22} textAnchor="middle" className={styles.end}>{fmt(field.min!)}</text>
        <text x={polar(1)[0]} y={CY + 22} textAnchor="middle" className={styles.end}>{fmt(field.max!)}</text>
        <text x={CX} y={CY + 30} textAnchor="middle" className={styles.value}>
          {fmt(field.value)}<tspan className={styles.unit}>{unit}</tspan>
        </text>
        <text x={CX} y={CY + 48} textAnchor="middle" className={styles.who}>{who}</text>
      </svg>
      {field.top != null && field.top_subject && (
        <p className={styles.top}>
          Máximo: <strong>{fmt(field.top)}{unit}</strong> · {field.top_subject}
        </p>
      )}
      {visibles.length > 0 && (
        <ul className={styles.legend} aria-label="Bandas de referencia">
          {visibles.map((b) => (
            <li key={b.label} className={`${styles.legendItem} ${b === band ? styles.current : ""}`}>
              <span className={styles.swatch} style={{ background: bandColor(b) }} aria-hidden="true" />
              {b.label} <span className={styles.range}>{formatBandRange(b)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
