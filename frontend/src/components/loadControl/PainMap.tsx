"use client";

/**
 * "¿Dónde les duele?" — the squad's check-in / check-out pain answers on a
 * muscle-group body map (front and back), for the selected day or its week.
 *
 * Encoding: sequential single hue (blue, light → dark) by how many PLAYERS
 * marked the zone; grey = nobody. The number is printed on every marked zone,
 * and the ranked list beside the map carries the same data as text (who, how
 * many days) so colour is never the only channel. Answers that name a muscle
 * without its side, and answers that name no zone at all, are listed — never
 * drawn on a guessed leg, never dropped.
 */

import React, { useMemo, useState } from "react";

import { type PainCell, type PainMapData } from "@/lib/loadControl";
import { PAIN_OUTLINE, PAIN_VIEWBOX, PAIN_VIEWS, painZoneId } from "@/lib/painZones";

import styles from "./loadControl.module.css";

// dataviz reference palette, sequential blue (steps 150 → 600).
const RAMP = ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#184f95"];
const EMPTY = "#eef0f3";
const STROKE = "#ffffff";
const OUTLINE = "#e4e7ec";

function fillFor(players: number, max: number): string {
  if (!players) return EMPTY;
  const i = max <= 1 ? 0 : Math.round(((players - 1) / (max - 1)) * (RAMP.length - 1));
  return RAMP[Math.min(RAMP.length - 1, Math.max(0, i))];
}

/** Rough centre of a polygon path (its vertices' mean) — where the count goes. */
function centre(path: string): [number, number] {
  const nums = (path.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);
  const pts: [number, number][] = [];
  // Arc commands carry 7 numbers; only the plain "x y" pairs of M/L are vertices.
  const cmds = path.match(/[MLA][^MLAZ]*/g) ?? [];
  for (const c of cmds) {
    const n = (c.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);
    if (c[0] === "A") pts.push([n[5], n[6]]);
    else if (n.length >= 2) pts.push([n[0], n[1]]);
  }
  if (!pts.length && nums.length >= 2) return [nums[0], nums[1]];
  return [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
}

interface Props {
  data: { day: PainMapData; week: PainMapData };
  scope: "day" | "week";
  onScope: (s: "day" | "week") => void;
  dayLabel: string;
  weekLabel: string;
}

export default function PainMap({ data, scope, onScope, dayLabel, weekLabel }: Props) {
  const map = scope === "week" ? data.week : data.day;
  const [active, setActive] = useState<string | null>(null);

  const byId = useMemo(() => {
    const m = new Map<string, PainCell>();
    for (const c of map.zones) {
      const id = painZoneId(c.zone, c.side);
      if (id) m.set(id, c);
    }
    return m;
  }, [map]);
  const max = Math.max(0, ...map.zones.map((c) => c.players));
  const unsided = map.zones.filter((c) => !painZoneId(c.zone, c.side));
  const activeCell = active ? byId.get(active) ?? null : null;
  const total = new Set(map.zones.flatMap((c) => c.who.map((w) => w.player_id))).size;
  const who = (c: PainCell) => c.who.map((w) => (scope === "week" && w.days > 1 ? `${w.name} (${w.days} días)` : w.name)).join(", ");

  return (
    <section className={styles.card} aria-labelledby="pm-title">
      <div className={styles.cardHead}>
        <h2 id="pm-title" className={styles.h2}>¿Dónde les duele? · {scope === "week" ? weekLabel : dayLabel}</h2>
        <span className={styles.muted}>
          {total} jugador{total === 1 ? "" : "es"} con molestias · check-in y check-out
        </span>
      </div>
      <div className={styles.controls}>
        <div role="group" aria-label="Período del mapa" className={styles.segmented}>
          <button type="button" aria-pressed={scope === "day"} onClick={() => onScope("day")}>Día</button>
          <button type="button" aria-pressed={scope === "week"} onClick={() => onScope("week")}>Semana</button>
        </div>
      </div>

      {map.zones.length === 0 && map.others.length === 0 ? (
        <p className={styles.muted}>Nadie marcó molestias {scope === "week" ? "esta semana" : "este día"}.</p>
      ) : (
        <div className={styles.painGrid}>
          <div className={styles.painFigures}>
            {PAIN_VIEWS.map((v) => (
              <figure key={v.key} className={styles.painFigure}>
                <svg viewBox={PAIN_VIEWBOX} role="img"
                  aria-label={`Vista ${v.label.toLowerCase()}: ${v.zones.filter((s) => byId.has(s.id))
                    .map((s) => `${byId.get(s.id)!.label} ${byId.get(s.id)!.players}`).join(", ") || "sin molestias"}`}>
                  {PAIN_OUTLINE.map((d, i) => <path key={i} d={d} fill={OUTLINE} />)}
                  {v.zones.map((s) => {
                    const c = byId.get(s.id);
                    const on = active === s.id;
                    return (
                      <path key={s.id} d={s.path} fill={fillFor(c?.players ?? 0, max)}
                        stroke={on ? "#101828" : STROKE} strokeWidth={on ? 2 : 1.5}
                        tabIndex={c ? 0 : -1} aria-label={c ? `${c.label}: ${c.players} jugador${c.players === 1 ? "" : "es"}` : undefined}
                        style={{ cursor: c ? "pointer" : "default", outline: "none" }}
                        onMouseEnter={() => c && setActive(s.id)} onMouseLeave={() => setActive(null)}
                        onFocus={() => c && setActive(s.id)} onBlur={() => setActive(null)}>
                        {c && <title>{`${c.label}: ${who(c)}`}</title>}
                      </path>
                    );
                  })}
                  {v.zones.map((s) => {
                    const c = byId.get(s.id);
                    if (!c) return null;
                    const [x, y] = centre(s.path);
                    const dark = RAMP.indexOf(fillFor(c.players, max)) >= 3;
                    return (
                      <text key={`t-${s.id}`} x={x} y={y + 4} textAnchor="middle" fontSize={11} fontWeight={700}
                        fill={dark ? "#ffffff" : "#101828"} pointerEvents="none">{c.players}</text>
                    );
                  })}
                  <text x={v.key === "front" ? 18 : 18} y={300} fontSize={10} fill="#667085">{v.key === "front" ? "Der." : "Izq."}</text>
                  <text x={182} y={300} fontSize={10} fill="#667085" textAnchor="end">{v.key === "front" ? "Izq." : "Der."}</text>
                </svg>
                <figcaption className={styles.muted}>{v.label}</figcaption>
              </figure>
            ))}
            <div className={styles.painLegend} aria-hidden="true">
              <span>Jugadores</span>
              <span className={styles.painSwatch} style={{ background: EMPTY }} />0
              {RAMP.map((c) => <span key={c} className={styles.painSwatch} style={{ background: c }} />)}
              {max > 0 ? max : ""}
            </div>
            <p className={styles.muted} aria-live="polite">
              {activeCell ? `${activeCell.label}: ${who(activeCell)}` : "Pasá el mouse por una zona para ver quiénes."}
            </p>
          </div>

          <div>
            <table className={styles.table} style={{ minWidth: 0 }}>
              <thead>
                <tr><th style={{ textAlign: "left" }}>Zona</th><th style={{ textAlign: "right" }}>Jugadores</th>
                  {scope === "week" && <th style={{ textAlign: "right" }}>Días</th>}<th style={{ textAlign: "left" }}>Quiénes</th></tr>
              </thead>
              <tbody>
                {map.zones.map((c) => {
                  const id = painZoneId(c.zone, c.side);
                  return (
                    <tr key={`${c.zone}-${c.side}`} onMouseEnter={() => id && setActive(id)} onMouseLeave={() => setActive(null)}
                      style={{ background: id && active === id ? "#f2f4f7" : undefined }}>
                      <td style={{ textAlign: "left" }}>{c.label}{!id && <span className={styles.posTag}> · sin lado</span>}</td>
                      <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{c.players}</td>
                      {scope === "week" && <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{c.marks}</td>}
                      <td className={styles.muted} style={{ textAlign: "left" }}>{who(c)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {unsided.length > 0 && (
              <p className={styles.provenance}>
                “Sin lado”: el jugador nombró el músculo pero no el lado (formularios de texto libre); se cuenta en la
                lista pero no se dibuja en el mapa.
              </p>
            )}
            {map.others.length > 0 && (
              <>
                <h3 className={styles.h3} style={{ marginTop: 12 }}>Otras molestias (texto libre)</h3>
                <ul className={styles.pendingList}>
                  {map.others.map((o, i) => (
                    <li key={`${o.player_id}-${o.date}-${i}`}>
                      <span><strong>{o.name}</strong> · {o.text}</span>
                      {scope === "week" && <span className={styles.muted}>{o.date.slice(8, 10)}/{o.date.slice(5, 7)}</span>}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
