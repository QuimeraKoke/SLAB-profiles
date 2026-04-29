// Shared types matching backend Pydantic schemas (api/schemas.py).

export interface ApiUser {
  id: number;
  email: string;
  username: string;
  is_staff: boolean;
  is_superuser: boolean;
}

export interface Membership {
  club: Club;
  all_categories: boolean;
  categories: Category[];
  all_departments: boolean;
  departments: Department[];
}

export interface MeResponse {
  user: ApiUser;
  membership: Membership | null;
}

export interface LoginResponse {
  access_token: string;
  expires_at: string;
  user: ApiUser;
  membership: Membership | null;
}

export interface Club {
  id: string;
  name: string;
}

export interface Department {
  id: string;
  name: string;
  slug: string;
  club_id: string;
}

export interface Category {
  id: string;
  name: string;
  club_id: string;
  departments: Department[];
}

export interface Position {
  id: string;
  name: string;
  abbreviation: string;
  role: string;
  sort_order: number;
  club_id: string;
}

export interface PlayerSummary {
  id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  nationality: string;
  is_active: boolean;
  category_id: string;
  position: Position | null;
}

export interface PlayerDetail {
  id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  nationality: string;
  is_active: boolean;
  club: Club;
  category: Category;
  position: Position | null;
}

export type ExamFieldType =
  | "number"
  | "text"
  | "categorical"
  | "calculated"
  | "boolean"
  | "date";

export interface ExamField {
  key: string;
  label: string;
  type: ExamFieldType;
  unit?: string;
  group?: string;
  options?: string[];
  formula?: string;
  chart_type?: string;
  required?: boolean;
  /** When true on a `text` field, renders a textarea instead of a single-line input. */
  multiline?: boolean;
  /** Optional row count hint for multiline text fields. */
  rows?: number;
  /** Hint text shown inside empty inputs. */
  placeholder?: string;
}

export interface ExamConfigSchema {
  fields: ExamField[];
}

export type ExamInputMode =
  | "single"
  | "team_table"
  | "quick_list"
  | "bulk_ingest";

export interface ExamInputModifiers {
  prefill_from_last?: boolean;
}

export interface ExamInputConfig {
  input_modes: ExamInputMode[];
  default_input_mode?: ExamInputMode;
  modifiers?: ExamInputModifiers;
  /** Optional column-mapping config used by bulk_ingest mode. */
  column_mapping?: Record<string, unknown>;
  /** When true, the single-mode form shows a match picker so the result
   *  can be linked to a calendar event (and recorded_at derived from it). */
  allow_event_link?: boolean;
}

export interface ExamTemplate {
  id: string;
  name: string;
  department: Department;
  version: number;
  config_schema: ExamConfigSchema;
  input_config?: ExamInputConfig;
}

export interface ExamResultEventBrief {
  id: string;
  event_type: EventType;
  title: string;
  starts_at: string;
  metadata: Record<string, unknown>;
}

export interface ExamResult {
  id: string;
  player_id: string;
  template_id: string;
  recorded_at: string;
  result_data: Record<string, unknown>;
  event?: ExamResultEventBrief | null;
}

// ---------- Bulk ingest preview/commit response ----------

export interface BulkMatchedPlayer {
  player_id: string;
  player_name: string;
  session_label: string | null;
  contributing_rows: number;
  result_data: Record<string, unknown>;
}

export interface BulkUnmatched {
  raw_player: string;
  rows: number;
  issues: string[];
}

export interface BulkIngestResponse {
  matched: BulkMatchedPlayer[];
  unmatched: BulkUnmatched[];
  total_rows: number;
  matched_players: number;
  created_results: number;
  dry_run: boolean;
}

// ---------- Events ----------

export type EventType =
  | "match"
  | "training"
  | "medical_checkup"
  | "physical_test"
  | "team_speech"
  | "nutrition"
  | "other";

export type EventScope = "individual" | "category" | "custom";

export interface EventParticipant {
  id: string;
  first_name: string;
  last_name: string;
}

export interface CalendarEvent {
  id: string;
  club: Club;
  department: Department;
  event_type: EventType;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string | null;
  location: string;
  scope: EventScope;
  category: Category | null;
  participants: EventParticipant[];
  metadata: Record<string, unknown>;
  /** Number of ExamResult rows linked to this event (e.g. GPS uploads). */
  result_count: number;
  created_at: string;
  updated_at: string;
}

// ---------- Configurable dashboards ----------

/** Resolved chart-ready payload returned by the backend. Shape varies by chart_type. */
export type WidgetData =
  | ComparisonTablePayload
  | LineWithSelectorPayload
  | DonutPerResultPayload
  | GroupedBarPayload
  | MultiLinePayload
  | CrossExamLinePayload
  | UnsupportedPayload
  | EmptyPayload;

export interface FieldMeta {
  key: string;
  label: string;
  unit: string;
  group: string;
  type: string;
}

export interface ComparisonTablePayload {
  chart_type: "comparison_table";
  columns: { result_id: string; recorded_at: string }[];
  rows: (FieldMeta & {
    values: (number | string | boolean | null)[];
    deltas: (number | null)[];
  })[];
}

export interface LineWithSelectorPayload {
  chart_type: "line_with_selector";
  available_fields: FieldMeta[];
  series: Record<string, { recorded_at: string; value: number | null }[]>;
}

export interface DonutSlice {
  key: string;
  label: string;
  value: number;
  color: string | null;
  percentage: number;
}

export interface DonutPerResultPayload {
  chart_type: "donut_per_result";
  donuts: {
    result_id: string;
    recorded_at: string;
    slices: DonutSlice[];
    total: number;
  }[];
}

export interface GroupedBarPayload {
  chart_type: "grouped_bar";
  groups: {
    result_id: string;
    recorded_at: string;
    bars: { key: string; label: string; value: number | null }[];
  }[];
  fields: (FieldMeta & { color: string | null })[];
}

export interface MultiLinePayload {
  chart_type: "multi_line";
  series: {
    key: string;
    label: string;
    unit: string;
    color: string | null;
    points: { recorded_at: string; value: number | null }[];
  }[];
}

export interface CrossExamLinePayload {
  chart_type: "cross_exam_line";
  series: {
    label: string;
    color: string | null;
    unit: string;
    template: string;
    field_key: string;
    points: { recorded_at: string; value: number | null }[];
  }[];
}

export interface UnsupportedPayload {
  chart_type: string;
  unsupported: true;
  reason?: string;
}

export interface EmptyPayload {
  chart_type: string;
  empty: true;
  title?: string;
}

export interface DashboardWidget {
  id: string;
  chart_type: string;
  title: string;
  description: string;
  column_span: number;
  sort_order: number;
  display_config: Record<string, unknown>;
  data: WidgetData;
}

export interface DashboardSection {
  id: string;
  title: string;
  is_collapsible: boolean;
  default_collapsed: boolean;
  sort_order: number;
  widgets: DashboardWidget[];
}

export interface DepartmentLayoutResponse {
  layout: {
    id: string;
    department: Department;
    category_id: string;
    name: string;
    sections: DashboardSection[];
  } | null;
}
