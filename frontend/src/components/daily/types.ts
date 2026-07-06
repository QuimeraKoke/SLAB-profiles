// Payload of GET /daily-report — la Daily, the 8 AM planning meeting.

export type Tone = "ok" | "warn" | "crit" | "info" | "muted";

export interface DailyKpis {
  disponibles: { n: number; total: number };
  no_disponibles: {
    n: number;
    breakdown: { label: string; n: number; tone: Tone }[];
  };
  alertas: { critical: number; warning: number };
  wellness_hoy: { n: number; expected: number };
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

export interface DailyReport {
  date: string;
  generated_at: string;
  category: string;
  kpis: DailyKpis;
  lesionados: DailyLesionado[];
  alertas: DailyAlertRow[];
  notes: DailyNote[];
  players: { id: string; name: string }[];
  departments: { id: string; name: string; slug: string }[];
}
