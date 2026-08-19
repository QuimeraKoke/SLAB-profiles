"use client";

import React, { useCallback, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Info } from "lucide-react";

import styles from "./MatchPitch.module.css";

/** Two pitches — ours and the rival's — one visible at a time.
 *
 *  Moving the pointer across the halves swaps sides, but hover is only a
 *  shortcut: the real control is a pair of tabs whose state lives in `?equipo=`
 *  (IA principle 2 — the URL owns tab state, so the view is bookmarkable and
 *  works from the keyboard and on the tablets used pitchside). The swap is
 *  animated unless the viewer prefers reduced motion.
 *
 *  Placement honesty is driven by the API, not assumed here: `placement` says
 *  whether the lines came from registered positions or a generic template, and
 *  `lanes_resolved` says how many left/right assignments are real rather than an
 *  even spread. The caption changes accordingly. */

export interface PitchPlayer {
  person_id: number | null;
  name: string | null;
  short_name: string | null;
  shirt_number: number | null;
  captain: boolean;
  is_gk: boolean;
  goals: number;
  yellow: number;
  red: number;
  minute_in: number | null;
  minute_out: number | null;
  x: number;
  y: number;
  line_label: string;
}
export interface PitchSide {
  team: string | null;
  placement: "slab_positions" | "generic";
  positions_resolved: number;
  lanes_resolved: number;
  starters: PitchPlayer[];
  bench: PitchPlayer[];
}
type SideKey = "ours" | "rival";

function Dot({ p }: { p: PitchPlayer }) {
  const marks =
    "⚽".repeat(Math.min(p.goals, 3)) +
    (p.yellow ? "🟨" : "") +
    (p.red ? "🟥" : "");
  return (
    <div
      className={styles.dotWrap}
      style={{ left: `${p.x}%`, bottom: `${p.y}%` }}
      title={`${p.name ?? ""}${p.line_label ? ` · ${p.line_label}` : ""}`}
    >
      <span className={`${styles.dot} ${p.is_gk ? styles.gk : ""}`}>
        {p.shirt_number ?? "–"}
      </span>
      <span className={styles.dotName}>
        {p.short_name ?? p.name}
        {p.captain && <b className={styles.cap}>C</b>}
      </span>
      {(marks || p.minute_out || p.minute_in) && (
        <span className={styles.dotMarks}>
          {marks}
          {p.minute_out ? <i className={styles.out}>↓{p.minute_out}&apos;</i> : null}
          {p.minute_in ? <i className={styles.in}>↑{p.minute_in}&apos;</i> : null}
        </span>
      )}
    </div>
  );
}

function Pitch({ side }: { side: PitchSide }) {
  const caption =
    side.placement === "generic"
      ? "Posiciones no informadas por la federación — ubicación aproximada."
      : side.lanes_resolved > 0
        ? `Líneas según posición registrada. ${side.lanes_resolved} jugador(es) con lado exacto; el resto, reparto parejo.`
        : "Líneas según posición registrada en SLAB. Izquierda/derecha es aproximada.";
  return (
    <div className={styles.pitchCol}>
      <div className={styles.field} aria-hidden="false">
        {/* markings */}
        <span className={styles.halfway} />
        <span className={styles.circle} />
        <span className={styles.box} />
        <span className={styles.sixYard} />
        {side.starters.map((p, i) => (
          <Dot key={p.person_id ?? i} p={p} />
        ))}
      </div>
      <p className={styles.caption}>
        <Info size={11} aria-hidden="true" /> {caption}
      </p>
      {side.bench.length > 0 && (
        <>
          <p className={styles.benchLabel}>Banca</p>
          <ul className={styles.bench}>
            {side.bench.map((p, i) => (
              <li key={p.person_id ?? i}>
                <span className={styles.benchNum}>{p.shirt_number ?? "–"}</span>
                {p.short_name ?? p.name}
                {p.minute_in ? (
                  <i className={styles.in}>↑{p.minute_in}&apos;</i>
                ) : null}
                {p.goals ? <span>{"⚽".repeat(Math.min(p.goals, 3))}</span> : null}
                {p.yellow ? <span>🟨</span> : null}
                {p.red ? <span>🟥</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default function MatchPitch({
  ours,
  rival,
}: {
  ours: PitchSide;
  rival: PitchSide;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const fromUrl = params.get("equipo");
  // The URL is the source of truth; hover is a transient override layered on
  // top. Deriving rather than mirroring keeps the two from drifting and needs no
  // effect to re-sync when the query string changes (back button, shared link).
  const [hover, setHover] = useState<SideKey | null>(null);
  const active: SideKey = hover ?? (fromUrl === "rival" ? "rival" : "ours");
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const select = useCallback(
    (next: SideKey) => {
      setHover(null);
      const qs = new URLSearchParams(Array.from(params.entries()));
      qs.set("equipo", next);
      router.replace(`?${qs.toString()}`, { scroll: false });
    },
    [params, router],
  );

  // Hover shortcut: which half the pointer is over decides the side. Deliberately
  // does NOT write to the URL — only an explicit tab click does, so drifting the
  // mouse across the page can't spam history.
  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = wrapRef.current;
    if (!el) return;
    const { left, width } = el.getBoundingClientRect();
    const next: SideKey = e.clientX - left < width / 2 ? "ours" : "rival";
    if (next !== active) setHover(next);
  }

  const sides: Record<SideKey, PitchSide> = { ours, rival };

  return (
    <div className={styles.wrap}>
      <div className={styles.tabs} role="tablist" aria-label="Equipo en cancha">
        {(["ours", "rival"] as SideKey[]).map((k) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={active === k}
            className={`${styles.tab} ${active === k ? styles.tabOn : ""}`}
            onClick={() => select(k)}
          >
            {sides[k].team ?? (k === "ours" ? "Nosotros" : "Rival")}
          </button>
        ))}
      </div>

      <div
        ref={wrapRef}
        className={styles.stage}
        onMouseMove={onMove}
        role="tabpanel"
        aria-label={sides[active].team ?? undefined}
      >
        {(["ours", "rival"] as SideKey[]).map((k) => (
          <div
            key={k}
            className={`${styles.slide} ${
              active === k ? styles.slideOn : k === "ours" ? styles.slideLeft : styles.slideRight
            }`}
            // Keep the hidden side out of the tab order and off screen readers.
            aria-hidden={active !== k}
            {...(active !== k ? { inert: "" as unknown as boolean } : {})}
          >
            <Pitch side={sides[k]} />
          </div>
        ))}
      </div>
      <p className={styles.hoverHint}>
        Mové el cursor de un lado al otro para cambiar de equipo, o usá las
        pestañas.
      </p>
    </div>
  );
}
