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
    /** False for a calendar week with no plan: no targets. */
    planned?: boolean;
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

// ── Check-in / out (Bienestar tab) — backend `load_control/wellness.py` ────────
export interface WellnessItem { key: string; label: string }
export interface WellnessDay {
  date: string; checkin_n: number; checkout_n: number; players: number;
  [item: string]: number | string | null;
}
export interface WellnessRow {
  player_id: string; name: string; position?: string; checkin: boolean; checkout: boolean;
  scores: Record<string, number | null>; total_bienestar: number | null;
  duracion_min: number | null; rpe: number | null; ua: number | null; peso: number | null;
  /** Body zones from `dolor_muscular` / `molestia_post`. */
  pain: string[];
  /** Illness from `sintomas` (fiebre, resfriado…) — not pain. */
  symptoms: string[];
}
export interface WellnessPending { player_id: string; name: string; position: string; trained: boolean }
export interface WellnessFlag extends WellnessRow { lows: { key: string; value: number }[]; severity: number }
export interface WellnessPayload {
  items: WellnessItem[]; low: number; series: WellnessDay[]; players: number; day: string | null;
  rows?: WellnessRow[]; flagged?: WellnessFlag[]; missing?: { player_id: string; name: string }[];
  /** This week's squad without the form that day; `trained` = GPS that day. */
  no_checkin?: WellnessPending[]; no_checkout?: WellnessPending[];
  answered?: { checkin: number; checkout: number };
}

/** 1–5 wellness score → band, as the club's dashboard colours it. */
export function scoreBand(v: number | null, low: number): "ok" | "leve" | "grave" | null {
  if (v == null) return null;
  return v <= low ? "grave" : v < 4 ? "leve" : "ok";
}

// ── Kinesia y lesiones — backend `load_control/availability.py` ────────────────
export type PlayerStatus = "injured" | "recovery" | "reintegration" | "available";
export interface AvailabilityRow {
  player_id: string; name: string; position: string; status: PlayerStatus; status_label: string;
  episode: {
    id: string; title: string; stage_label: string; severity: string | null; body_part: string | null;
    diagnosed_at: string; days_out: number; available_at: string | null;
    expected_return: string | null; days_to_return: number | null;
  } | null;
}
export interface InjuryHistoryRow {
  episode_id: string; player_id: string; name: string; title: string; body_part: string | null;
  severity: string | null; started: string; returned: string | null; days_out: number | null;
}
export interface AvailabilityPayload {
  date: string; players: number;
  counts: { status: PlayerStatus; label: string; n: number }[];
  unavailable: AvailabilityRow[];
  history: InjuryHistoryRow[];
}

// ── Minutos y asistencia — backend `load_control/participation.py` ─────────────
export interface ParticipationMatch { date: string; event_id: string | null; source: "comet" | "gps"; opponent: string | null }
export interface ParticipationRow {
  player_id: string; name: string; status: PlayerStatus; status_label: string;
  matches: ({ minutes: number; starter: boolean | null } | null)[];
  minutes: number; minutes_pct: number | null; called_up: number; starts: number;
  sessions_attended: number; attendance_pct: number | null; attendance_low: boolean;
  /** Sessions counted by training GPS, and those counted only by a check-in/out. */
  sessions_gps: number; sessions_form_only: number;
}
export interface ParticipationPayload {
  scope: "microcycle" | "season"; start: string; end: string; match_minutes: number;
  matches: ParticipationMatch[]; sessions: number; session_min_players: number;
  attendance_low_pct: number | null; rows: ParticipationRow[];
}

// ── Fatiga post-partido — backend `load_control/fatigue.py` ────────────────────
export interface FatigueRow {
  player_id: string; name: string; method: string; minutes: number | null;
  pre: number | null; post: number | null; next_pre: number | null;
  golpe_pct: number | null; golpe_band: Band | null;
  llega_pct: number | null; llega_band: Band | null; llega_state: "measured" | "pending" | "missing";
  pre_level: string | null; next_pre_level: string | null;
  basal: number | null; basal_n: number; pre_vs_basal: number | null;
  season_drift_pct: number | null; season_drift_band: Band | null;
  recent: { date: string; pre: number | null; post: number | null; golpe_band: Band | null }[];
}
export interface FatigueMatch { date: string; rival: string | null; source: string | null; tab: string | null; event_id: string | null }
export interface FatiguePayload {
  match: FatigueMatch | null; prev_match: FatigueMatch | null; next_match: FatigueMatch | null;
  rows: FatigueRow[];
  summary: { players: number; golpe_n: number; llega_n: number;
    counts: { golpe: Record<Band, number>; llega: Record<Band, number> } };
  trend: { player_id: string; name: string; method: string;
    points: { date: string; pre: number | null; post: number | null; basal: number | null; rival: string | null }[] } | null;
  params: { baseline_n: number; attempt_value: string; rsi_alert: { ok_from: number; grave_at: number } };
}

// ── Composición corporal — backend `load_control/composition.py` ───────────────
export interface CompBand { label: string; color: string; min?: number | null; max?: number | null }
export interface CompMetric {
  key: string; label: string; unit: string; decimals: number; direction: "up" | "down" | "neutral";
  /** The category's reference bands (the same ones that fire alerts); empty = none. */
  bands: CompBand[];
}
/** First band containing the value, bounds inclusive — as `exams.bands.band_for_value`. */
export function bandOf(value: unknown, bands: CompBand[] | undefined): CompBand | null {
  if (typeof value !== "number" || !bands) return null;
  return bands.find((b) => (b.min == null || value >= b.min) && (b.max == null || value <= b.max)) ?? null;
}
export type CompMeasurement = { date: string; talla: number | null } & Record<string, number | null | string>;
export interface CompositionPayload {
  metrics: CompMetric[]; squad_keys: string[];
  rows: { player_id: string; name: string; position: string; last: CompMeasurement; prev_date: string | null;
    delta: Record<string, number | null>; measurements: number }[];
  mean: Record<string, number | null>;
  player: { player_id: string; name: string; last: CompMeasurement; prev: CompMeasurement | null; first: CompMeasurement;
    delta: Record<string, number | null>; delta_first: Record<string, number | null>; measurements: CompMeasurement[] } | null;
}

// ── Jugador — backend `load_control/player_card.py` ────────────────────────────
export interface PlayerCard {
  player: { player_id: string; name: string; position: string; category: string; age: number | null;
    photo_url: string | null; status: PlayerStatus };
  load: { metrics: Metric[]; accumulated: EvalPlayer | null;
    days: { date: string; md_label: string; kind: DayKind; row: EvalPlayer | null }[] };
  wellness: { items: WellnessItem[]; low: number | null; days: { date: string; row: WellnessRow | null }[] };
  fatigue: { match: FatigueMatch | null; next_match: FatigueMatch | null; row: FatigueRow | null;
    trend: FatiguePayload["trend"]; params: FatiguePayload["params"] };
  minutes: {
    week: Partial<ParticipationRow> & { sessions: number; matches: ParticipationMatch[] };
    season: Partial<ParticipationRow> & { sessions: number; match_count: number };
  };
  status: { status: PlayerStatus; card: AvailabilityRow | null; history: InjuryHistoryRow[] };
  evaluations: {
    groups: { name: string; columns: { key: string; label: string; unit: string; direction: "up" | "down" | "neutral" }[] }[];
    row: { cells: Record<string, { value: number; date: string; band: string | null; color: string | null;
      prev: { value: number; date: string; band: string | null } | null; delta: number | null; delta_pct: number | null }> } | null;
  };
  composition: { metrics: CompMetric[]; mean: Record<string, number | null>; player: CompositionPayload["player"] } | null;
}

// ── Resumen — backend `load_control/summary.py` ────────────────────────────────
export interface SummaryPayload {
  ref_day: string; sentence: string;
  cards: {
    load: { metrics: (EvalCell & { key: string; label: string; counts: Record<Band, number>; n: number })[];
      worst: (EvalCell & { label: string }) | null; days: number; short: number; over: number;
      rules: { short_min_metrics: number; below_pct: number; over_pct: number } };
    fatigue: { state: "fatiga" | "recuperacion"; match: FatigueMatch | null; next_match: FatigueMatch | null;
      counts: Record<Band, number>; measured: number };
    wellness: { day: string | null; answered: { checkin: number; checkout: number } | null; missing: number;
      pain: number; flagged: number };
    availability: { counts: { status: PlayerStatus; label: string; n: number }[]; players: number; available: number };
    participation: { sessions: number; matches: number };
  };
  review: { player_id: string; name: string; score: number;
    flags: { kind: "estado" | "fatiga" | "carga" | "checkin"; text: string; level: Band }[] }[];
}

// ── Day navigator of the squad panels — `GET /load-control/day` ────────────────
export interface DayNav {
  team: { label: string; season: number; categories: string[] };
  week_key: string; day: string; start_date: string; end_date: string; number: number; kind: string;
  planned: boolean; microcycle_id: string | null; md_label: string; day_kind: DayKind | "";
}
