"use client";

/**
 * Period picker of the Centro de mando squad panels: a month calendar with the
 * team's matches marked (official filled, friendly outlined, rival on hover).
 *   Semana  one click on any day → that Mon–Sun week, with that day chosen.
 *   Rango   start, then end (or "Hasta hoy") → any period, not just a week.
 * Plus shortcuts (Esta semana, Semana del último partido, Últimas 3 semanas…).
 *
 * Matches come from `GET /load-control/calendar` for the visible month.
 * Keyboard: arrows move a day / a week, PageUp/PageDown a month, Enter picks,
 * Escape closes.
 */

import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { api } from "@/lib/api";
import styles from "./CalendarPicker.module.css";

export interface CalMatch { date: string; kind: "official" | "friendly"; opponent: string; event_id: string | null }

const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
  "noviembre", "diciembre"];
const MON = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const WEEKDAYS = ["L", "M", "M", "J", "V", "S", "D"];
const WEEKDAY_LONG = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s: string) => new Date(`${s}T12:00:00`);
export const addDays = (s: string, n: number) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
export const daysBetween = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86400000);
export const mondayOf = (s: string) => addDays(s, -((parse(s).getDay() + 6) % 7));
export const shortLabel = (s: string) => { const d = parse(s); return `${d.getDate()} ${MON[d.getMonth()]}`; };
const longLabel = (s: string) => { const d = parse(s); return `${WEEKDAY_LONG[d.getDay()]} ${d.getDate()} de ${MONTHS[d.getMonth()]}`; };

// Words that do not tell one rival from another ("UNIVERSIDAD CATOLICA",
// "UNIVERSIDAD DE CONCEPCION", "DEPORTES RECOLETA").
const NOISE = new Set(["UNIVERSIDAD", "DE", "DEL", "LA", "EL", "LOS", "CLUB", "DEPORTES", "DEPORTIVO", "CD", "FC",
  "CSD", "SADP", "SAD", "U"]);
/** 3 letters for the calendar cell: "COLO COLO" → CC, "UNION ESPAÑOLA" → UE, "UNIVERSIDAD CATOLICA" → CAT. */
export function rivalShort(name: string): string {
  const toks = name.toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").split(/\s+/).filter((t) => t && !NOISE.has(t));
  if (toks.length === 0) return name.slice(0, 3).toUpperCase();
  if (toks.length === 1) return toks[0].slice(0, 3);
  return toks.slice(0, 3).map((t) => t[0]).join("");
}

/** Monday-first grid of the month holding `month` (YYYY-MM-01). */
function grid(month: string): string[] {
  const first = parse(month);
  const offset = (first.getDay() + 6) % 7;
  const start = addDays(month, -offset);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

type Props = {
  categoryId: string;
  today: string;
  /** The period on screen and the day chosen in it. */
  start: string;
  end: string;
  day: string;
  /** A new period; `day` when the pick says which day (a click in Semana). */
  onPick: (start: string, end: string, day?: string) => void;
  onClose: () => void;
};

export default function CalendarPicker({ categoryId, today, start, end, day, onPick, onClose }: Props) {
  const isWeek = mondayOf(start) === start && daysBetween(start, end) === 6;
  const [tab, setTab] = useState<"week" | "range">(isWeek ? "week" : "range");
  const [month, setMonth] = useState(() => `${day.slice(0, 7)}-01`);
  const [focus, setFocus] = useState(day);
  const [cache, setCache] = useState<Record<string, CalMatch[]>>({});
  // Range in progress: the first click; the second one closes it.
  const [draftStart, setDraftStart] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  // Keyboard navigation shows the focused day's tooltip; the mouse shows the hovered one.
  const [kbd, setKbd] = useState(false);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  const days = useMemo(() => grid(month), [month]);
  const matches = cache[month];

  useEffect(() => {
    if (cache[month]) return;
    let cancelled = false;
    api<{ matches: CalMatch[] }>(`/load-control/calendar?category_id=${categoryId}&start=${days[0]}&end=${days[41]}`)
      .then((r) => { if (!cancelled) setCache((c) => ({ ...c, [month]: r.matches })); })
      .catch(() => { if (!cancelled) setCache((c) => ({ ...c, [month]: [] })); });
    return () => { cancelled = true; };
  }, [month, categoryId, days, cache]);

  // Close on a click outside / Escape.
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (root.current && !root.current.contains(e.target as Node)) onClose(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [onClose]);

  // Keep keyboard focus on the focused day.
  useEffect(() => {
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-day="${focus}"]`)?.focus();
  }, [focus, month]);

  const byDay = useMemo(() => new Map((matches ?? []).map((m) => [m.date, m])), [matches]);
  const monthMatches = (matches ?? []).filter((m) => m.date.startsWith(month.slice(0, 7)));

  const moveMonth = (n: number) => {
    const d = parse(month);
    d.setMonth(d.getMonth() + n);
    const next = iso(d).slice(0, 7) + "-01";
    setMonth(next);
    setFocus(next);
  };

  const done = (a: string, b: string, d?: string) => { onPick(a, b, d); onClose(); };
  const pick = (d: string) => {
    if (tab === "week") { const mon = mondayOf(d); done(mon, addDays(mon, 6), d); return; }
    if (!draftStart) { setDraftStart(d); return; }
    const [a, b] = d < draftStart ? [d, draftStart] : [draftStart, d];
    done(a, b);
  };

  const onGridKey = (e: React.KeyboardEvent) => {
    setKbd(true);
    const step: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (e.key in step) {
      e.preventDefault();
      const next = addDays(focus, step[e.key]);
      if (next.slice(0, 7) !== month.slice(0, 7)) setMonth(`${next.slice(0, 7)}-01`);
      setFocus(next);
    } else if (e.key === "PageUp" || e.key === "PageDown") {
      e.preventDefault();
      moveMonth(e.key === "PageUp" ? -1 : 1);
    }
  };

  // What is highlighted: the week under the mouse (Semana), the range being
  // drawn (Rango), else the period on screen.
  let lo = start, hi = end;
  if (tab === "week" && hover) { lo = mondayOf(hover); hi = addDays(lo, 6); }
  if (tab === "range" && draftStart) {
    const other = hover ?? draftStart;
    [lo, hi] = other < draftStart ? [other, draftStart] : [draftStart, other];
  }

  const lastMatchWeek = async () => {
    setBusy(true);
    try {
      const r = await api<{ matches: CalMatch[] }>(
        `/load-control/calendar?category_id=${categoryId}&start=${addDays(today, -90)}&end=${today}`);
      const last = r.matches.filter((m) => m.date <= today).pop();
      if (last) { const mon = mondayOf(last.date); done(mon, addDays(mon, 6), last.date); }
    } finally { setBusy(false); }
  };
  const presets: { label: string; run: () => void }[] = [
    { label: "Esta semana", run: () => { const mon = mondayOf(today); done(mon, addDays(mon, 6), today); } },
    { label: "Semana del último partido", run: () => { void lastMatchWeek(); } },
    { label: "Últimas 3 semanas", run: () => done(addDays(mondayOf(today), -14), today) },
    { label: "Últimos 30 días", run: () => done(addDays(today, -29), today) },
    { label: "Este mes", run: () => done(`${today.slice(0, 7)}-01`, today) },
    { label: "Toda la temporada", run: () => done(`${today.slice(0, 4)}-01-01`, today) },
  ];

  return (
    <div ref={root} className={styles.pop} role="dialog" aria-modal="false" aria-labelledby={titleId}>
      <div className={styles.tabs} role="group" aria-label="Cómo elegir">
        <button type="button" aria-pressed={tab === "week"} onClick={() => { setTab("week"); setDraftStart(null); }}>Semana</button>
        <button type="button" aria-pressed={tab === "range"} onClick={() => setTab("range")}>Rango de fechas</button>
      </div>
      <p className={styles.hint} aria-live="polite">
        {tab === "week" ? "Toca un día: se ve su semana con ese día elegido."
          : draftStart ? <>Desde el <strong>{shortLabel(draftStart)}</strong>. Elige la fecha de fin o{" "}
            <button type="button" className={styles.inlineLink} onClick={() => done(draftStart, today)}>hasta hoy</button>.</>
            : "Elige la fecha de inicio y luego la de fin (puede ser más de una semana)."}
      </p>
      <div className={styles.head}>
        <button type="button" className={styles.navBtn} onClick={() => moveMonth(-1)} aria-label="Mes anterior">
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        <span id={titleId} className={styles.month}>{MONTHS[parse(month).getMonth()]} {parse(month).getFullYear()}</span>
        <button type="button" className={styles.navBtn} onClick={() => moveMonth(1)} aria-label="Mes siguiente">
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
      <div className={styles.weekdays} aria-hidden="true">{WEEKDAYS.map((w, i) => <span key={i}>{w}</span>)}</div>
      <div ref={gridRef} className={styles.grid} role="grid" aria-labelledby={titleId} onKeyDown={onGridKey}
        onMouseLeave={() => setHover(null)} onMouseMove={() => kbd && setKbd(false)}>
        {days.map((d) => {
          const m = byDay.get(d);
          const outside = d.slice(0, 7) !== month.slice(0, 7);
          const edge = d === lo || d === hi;
          const inRange = d > lo && d < hi;
          const chosen = d === day && !draftStart && !(tab === "week" && hover);
          const cls = [styles.day, outside && styles.outside, d === today && styles.today,
            m && (m.kind === "official" ? styles.official : styles.friendly),
            inRange && styles.inRange, edge && styles.selected, chosen && styles.chosen,
            d === lo && styles.rangeStart, d === hi && styles.rangeEnd].filter(Boolean).join(" ");
          const label = `${longLabel(d)}${m ? `: partido ${m.kind === "official" ? "oficial" : "amistoso"}${m.opponent ? ` vs ${m.opponent}` : ""}` : ""}${d === today ? " (hoy)" : ""}`;
          const col = (parse(d).getDay() + 6) % 7;
          return (
            <button key={d} type="button" data-day={d} className={cls} tabIndex={d === focus ? 0 : -1}
              aria-label={label} aria-pressed={d >= lo && d <= hi}
              onClick={() => pick(d)} onMouseEnter={() => setHover(d)} onFocus={() => setFocus(d)}>
              <span className={styles.num}>{parse(d).getDate()}</span>
              {m && <span className={styles.ball} aria-hidden="true">{m.opponent ? rivalShort(m.opponent) : "⚽"}</span>}
              {/* Instant tooltip (the native one waits ~1 s): on hover and on keyboard focus. */}
              {m && (hover === d || (focus === d && kbd)) && (
                <span className={`${styles.tip} ${col >= 5 ? styles.tipEnd : col <= 1 ? styles.tipStart : ""}`} aria-hidden="true">
                  <strong>vs {m.opponent || "rival sin registrar"}</strong>
                  <span>{m.kind === "official" ? "Oficial" : "Amistoso"} · {shortLabel(d)}</span>
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className={styles.legend} aria-hidden="true">
        <span><i className={`${styles.swatch} ${styles.official}`} /> Partido oficial</span>
        <span><i className={`${styles.swatch} ${styles.friendly}`} /> Amistoso</span>
        <span><i className={`${styles.swatch} ${styles.todaySw}`} /> Hoy</span>
      </div>
      <div className={styles.presets} role="group" aria-label="Atajos">
        {presets.map((p) => (
          <button key={p.label} type="button" className={styles.preset} onClick={p.run} disabled={busy}>{p.label}</button>
        ))}
      </div>
      {monthMatches.length > 0 && (
        <div className={styles.matches}>
          <span className={styles.matchesTitle}>Partidos del mes</span>
          <ul>
            {monthMatches.map((m) => (
              <li key={m.date}>
                <button type="button" className={styles.matchBtn} onClick={() => pick(m.date)}>
                  <span className={styles.matchDate}>{shortLabel(m.date)}</span>
                  <span>vs {m.opponent || "rival sin registrar"}</span>
                  <span className={styles.matchKind}>{m.kind === "official" ? "Oficial" : "Amistoso"}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {matches === undefined && <p className={styles.hint}>Cargando partidos…</p>}
    </div>
  );
}
