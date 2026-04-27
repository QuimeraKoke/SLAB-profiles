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
