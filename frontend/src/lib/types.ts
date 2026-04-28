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

export interface ExamTemplate {
  id: string;
  name: string;
  department: Department;
  version: number;
  config_schema: ExamConfigSchema;
}

export interface ExamResult {
  id: string;
  player_id: string;
  template_id: string;
  recorded_at: string;
  result_data: Record<string, unknown>;
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
