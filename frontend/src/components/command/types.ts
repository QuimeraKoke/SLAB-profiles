// Types for the Centro de mando (command center) dashboard payload —
// mirrors `backend/api/command_center.py::build_command_center`.

export type Tone = "ok" | "warn" | "crit" | "info" | "muted";

export interface CCNextMatch {
  title: string;
  competition: string | null;
  starts_at: string;
  location: string;
  is_home: boolean | null;
  days_until: number;
  md_label: string;
}

export interface CCLastResult {
  title: string;
  score: unknown;
  starts_at: string;
}

export interface CCContext {
  next_match: CCNextMatch | null;
  last_result: CCLastResult | null;
  pre_match_risk: { count: number; headline: string; players: string[] };
}

export interface CCKpiBreakdown {
  label: string;
  n: number;
  tone?: Tone;
  expected?: number;
}

export interface CCKpis {
  disponibilidad: {
    value: string;
    available: number;
    total: number;
    breakdown: CCKpiBreakdown[];
  };
  riesgo: {
    value: number;
    label: string;
    status: string;
    tone: Tone;
    players: string[];
  };
  carga: {
    value: number | null;
    status: string;
    tone: Tone;
    over?: number;
    detail: string;
  };
  wellness: {
    value: number | null;
    status: string;
    tone: Tone;
    responses?: number;
    expected?: number;
    dimensions: { label: string; value: number }[];
  };
  completitud: {
    value: number | null;
    status: string;
    tone: Tone;
    breakdown: CCKpiBreakdown[];
  };
}

export interface CCSquadPlayer {
  id: string;
  initials: string;
  name: string;
  status: string;
  status_label: string;
  at_risk: boolean;
}

export interface CCSquad {
  counts: {
    disponibles: number;
    riesgo_alto: number;
    reintegracion: number;
    lesionados: number;
    recuperacion: number;
  };
  por_linea: { linea: string; pct: number; total: number }[];
  players: CCSquadPlayer[];
}

export interface CCDecision {
  player_id: string;
  initials: string;
  player: string;
  status: string;
  status_label: string;
  signal: string;
  priority: "alta" | "media" | "baja";
  alerts: number;
}

export interface CCDataQualityRow {
  source: string;
  status: Tone;
  detail: string;
  last_at: string | null;   // most recent recorded_at for this source (ISO), or null
  players: number | null;   // distinct players uploaded on that last day
  expected: number;         // roster size, for context
}

export interface CCRecentItem {
  kind: string;
  text: string;
  at: string | null;
}

export interface BriefingItem {
  department: string;
  department_label: string;
  priority: "alta" | "media" | "baja";
  tags: string[];
  title: string;
  recommendation: string;
  evidence: string[];
  confidence: number;
  owner_role: string;
  timing: string;
  cta_label: string;
  players: string[];
}

export interface CCCheckinNonResponder {
  player_id: string;
  name: string;
  position: string | null;
  injured: boolean;
}

export interface CCCheckinAdherence {
  responded: number;
  expected: number;
  pct: number | null;
  no_respondieron: CCCheckinNonResponder[];
}

export interface CommandCenter {
  category: string;
  generated_at: string;
  context: CCContext;
  kpis: CCKpis;
  squad: CCSquad;
  decisions: CCDecision[];
  data_quality: CCDataQualityRow[];
  checkin_adherence: CCCheckinAdherence;
  recent: CCRecentItem[];
}
