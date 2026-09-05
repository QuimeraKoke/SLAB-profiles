// Payload of GET /daily-report — la Daily, the 8 AM planning meeting.

export type Tone = "ok" | "warn" | "crit" | "info" | "muted";

export interface DailyWellnessDay {
  n: number;
  expected: number;
  no_respondieron: {
    player_id: string;
    name: string;
    position: string | null;
    injured: boolean;
  }[];
  /** Check-OUT only: the day the block actually describes. Not always the
   *  meeting date — check-outs arrive 11:00–18:00, so at 8 AM the useful
   *  question is who never closed the LAST session. Null if no session in
   *  the past two weeks. */
  date?: string | null;
  /** True when `date` IS the viewed date, so the screen can say "de hoy"
   *  instead of naming another day. */
  is_target_date?: boolean;
}

export interface DailyKpis {
  disponibles: { n: number; total: number };
  no_disponibles: {
    n: number;
    breakdown: { label: string; n: number; tone: Tone }[];
  };
  alertas: { critical: number; warning: number };
  wellness_hoy: DailyWellnessDay;
}

export interface DailyEpisode {
  id: string;
  template_slug: string;
  title: string;
  stage: string;
  stage_label: string;
  severity: string | null;
  body_part: string | null;
  diagnosed_at: string;
  days_out: number;
  available_at: string | null;
  expected_return: string | null;
  days_to_return: number | null;
  plan: string | null;
}

export interface DailyLoad {
  ratio: number;
  acute_km: number;
  chronic_week_km: number;
  last: string | null;
  pct_habitual: number | null;
}

export interface GpsCompareMetric {
  key: string;
  label: string;
  unit: string;
  current: number | null;
  baseline: number | null;
  pct: number | null;
  sessions_current: number;
  sessions_baseline: number;
}

export interface GpsCompare {
  baseline_days: number;
  current_days: number;
  injured_at: string;
  current_to: string | null;
  metrics: GpsCompareMetric[];
}

export interface DailyAlert {
  severity: string;
  message: string;
  source_type?: string;
  fired_at?: string | null;
}

export interface DailyNote {
  id: string;
  player_id: string;
  player_name: string;
  department: { id: string; name: string; slug: string } | null;
  /** 'pauta' = morning-meeting note; 'plan' = ongoing work-plan entry. */
  kind?: "pauta" | "plan";
  date: string;
  text: string;
  author: string;
  mine: boolean;
  created_at: string;
}

export interface DailyLesionado {
  player_id: string;
  name: string;
  initials: string;
  photo: string | null;
  position: string;
  status: string;
  status_label: string;
  episode: DailyEpisode | null;
  load: DailyLoad | null;
  gps_compare: GpsCompare | null;
  wellness: { score: number; date: string } | null;
  alerts: DailyAlert[];
  notes: DailyNote[];
}

export interface DailyAlertRow {
  player_id: string;
  name: string;
  initials: string;
  worst: string;
  alerts: DailyAlert[];
}

export interface KineEntry {
  id: string;
  player_id: string;
  player_name: string;
  clinica: string;
  gimnasio: string;
  cancha: string;
  objetivo: string;
  kinesiologo: string;
}

/** GET /daily-report/summary — AI recap of a completed day (null for today). */
export interface DailySummaryPayload {
  date: string;
  text: string | null;
  generated_at: string | null;
  model: string | null;
}

export interface DailyReport {
  date: string;
  generated_at: string;
  category: string;
  kpis: DailyKpis;
  lesionados: DailyLesionado[];
  alertas: DailyAlertRow[];
  kine: KineEntry[];
  notes: DailyNote[];
  /** Standing 'plan de trabajo' (KIND_PLAN) per player id, newest first. */
  plans: Record<string, DailyNote[]>;
  /** Recap of the most recent PRIOR daily (pauta/kine logged), or null. */
  last_daily: {
    date: string;
    notes: number;
    kine: number;
    wellness_responded: number;
    wellness_expected: number;
  } | null;
  players: { id: string; name: string }[];
  departments: { id: string; name: string; slug: string }[];
  /** Wellness forms this category fills. "checkout" only in the Formativo. */
  wellness_roles: ("checkin" | "checkout")[];
  /** Present only when `wellness_roles` includes "checkout". */
  checkout_hoy?: DailyWellnessDay;
}
