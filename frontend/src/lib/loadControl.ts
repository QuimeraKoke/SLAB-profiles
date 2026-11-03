/**
 * Control de carga — types and helpers shared by the planning screen.
 * Backend: `backend/api/load_control.py`, `backend/load_control/planning.py`.
 */

export type DayKind = "training" | "rest" | "official" | "friendly";
export type McStatus = "draft" | "open" | "closed";

export interface Metric { key: string; label: string; short: string; unit: string }

export interface McSummary {
  id: string; number: number; kind: string; status: McStatus;
  start_date: string; end_date: string;
}

export interface TeamPayload {
  season: number; label: string; bracket_id: string; bracket: string;
  categories: string[]; microcycles: McSummary[];
}

export interface RefCell { value: number; n_rows: number }
export interface RefGroup {
  [metric: string]: RefCell | number | boolean | undefined;
  n_players: number; n_matches: number; fallback?: boolean; own_players?: number;
}
export interface Reference {
  window: { start: string; end: string };
  params: { ref_window_days: number; ref_min_minutes: number; ref_official_only: boolean;
    ref_min_players?: number; metrics: string[] };
  team: RefGroup;
  groups: Record<string, RefGroup>;
  preview: boolean;
}

export interface McDay {
  date: string; weekday: string; kind: DayKind; md_label: string;
  /** "club" = the CÓDIGO the club wrote in its GPS sheet; "calc" = computed. */
  md_label_source?: "club" | "calc";
  targets_pct: Record<string, number>;
  /** The match loaded in SLAB for this day (link to /partidos/{id}); a
   *  friendly has none, only `opponent` from the GPS sheet. */
  event_id?: string | null;
  opponent?: string | null;
}

export interface McDetail extends McSummary {
  season: number;
  team: { label: string; bracket_id: string; bracket: string; categories: string[] };
  notes: string;
  frozen_at: string | null;
  copied_from: McSummary | null;
  metrics: Metric[];
  groups: { code: string; label: string }[];
  kinds: string[];
  reference: Reference;
  days: McDay[];
  targets: Record<string, Record<string, Record<string, number | null>>>;
  changed_vs_copy: Record<string, string[]>;
}

export interface Suggestion {
  start_date: string; end_date: string; number: number; kind: string; kinds: string[];
  copy_from: McSummary | null;
  days: { date: string; weekday: string; kind: DayKind; md_label: string; md_label_source?: "club" | "calc";
    event_id?: string | null; opponent?: string | null }[];
}

export const DAY_KIND_LABEL: Record<DayKind, string> = {
  training: "Entrenamiento",
  rest: "Descanso",
  official: "Partido oficial",
  friendly: "Partido amistoso",
};

export const STATUS_LABEL: Record<McStatus, string> = {
  draft: "Borrador", open: "Publicado", closed: "Cerrado",
};

const KIND_LABEL: Record<string, string> = {
  mixta: "Mixta", amplitud: "Amplitud", profundidad: "Profundidad",
  adaptacion: "Adaptación", competencia: "Competencia",
};
export const kindLabel = (k: string) => KIND_LABEL[k] ?? (k ? k[0].toUpperCase() + k.slice(1) : "Sin tipo");

export const isMatch = (k: DayKind) => k === "official" || k === "friendly";

/** "26 oct" from an ISO date, without timezone drift. */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("es-CL", { day: "numeric", month: "short" })
    .replace(".", "");
}

export function fmt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("es-CL");
}

export function refValue(group: RefGroup | undefined, metric: string): number | null {
  const cell = group?.[metric];
  return cell && typeof cell === "object" ? (cell as RefCell).value : null;
}

/** A % cell as typed: "" = no target, otherwise 0–200. */
export function parsePct(raw: string): { value: number | null; valid: boolean } {
  const t = raw.trim().replace(",", ".").replace("%", "");
  if (t === "") return { value: null, valid: true };
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 && n <= 200 ? { value: n, valid: true } : { value: null, valid: false };
}

// ── Evaluation (Carga GPS tab) — backend `load_control/evaluation.py` ──────────
export type Band = "ok" | "leve" | "grave";

export interface EvalCell { target: number | null; real: number | null; pct: number | null; band: Band | null }
export interface EvalPlayer {
  player_id: string; name: string; group: string; days: number; days_planned: number;
  minutes: number; sparring: boolean; compensacion: boolean; cells: Record<string, EvalCell>;
}
export interface EvalAlert extends EvalCell { player_id: string; name: string; group: string; metric: string; diff: number }
export interface Evaluation {
  mode: "day" | "accumulated"; day: string | null;
  days: { date: string; md_label: string; kind: DayKind }[];
  metrics: Metric[];
  bands: { ok: number; mild: number };
  summary: Record<string, EvalCell & { counts: Record<Band, number>; n: number }>;
  players: EvalPlayer[];
  alerts: EvalAlert[];
  provenance: {
    microcycle: number; include_sparring: boolean; include_matches: boolean; players: number;
    players_with_sparring: number; duplicates_dropped: number; reference_frozen: boolean;
    reference_window: { start: string; end: string } | null; fallback_groups: string[];
  };
}

export const BAND_WORD: Record<Band, string> = { ok: "en objetivo", leve: "alerta leve", grave: "alerta grave" };

export function signedPct(p: number | null): string {
  if (p == null) return "—";
  const r = Math.round(p);
  return `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r)}%`;
}

/** "bajo" / "sobre" — the direction in words, since colour never carries it alone. */
export const direction = (p: number | null) => (p == null ? "" : p < 0 ? "bajo" : p > 0 ? "sobre" : "");
