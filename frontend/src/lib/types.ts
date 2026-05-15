// Shared types matching backend Pydantic schemas (api/schemas.py).

export interface ApiUser {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  is_staff: boolean;
  is_superuser: boolean;
  /** Effective Django permission codenames (group + direct user perms).
   *  Superusers receive a single `"*"` sentinel — the frontend's
   *  `hasPermission` helper treats it as "match anything". */
  permissions: string[];
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
  /** Signed URL to the club logo when uploaded, null otherwise.
   *  Source: `Club.logo` (ImageField) via storage backend. The URL
   *  expires (5 min on the dev MinIO config) so don't cache it
   *  across user-session lifetimes. */
  logo_url?: string | null;
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

export type Sex = "" | "M" | "F";

export type PlayerStatus = "available" | "injured" | "recovery" | "reintegration";

export interface Episode {
  id: string;
  player_id: string;
  template_id: string;
  template_slug: string;
  template_name: string;
  status: "open" | "closed";
  stage: string;
  title: string;
  started_at: string;
  ended_at: string | null;
  metadata: Record<string, unknown>;
  result_count: number;
  latest_result_data: Record<string, unknown>;
}

export type ContractType = "permanent" | "loan_in" | "loan_out" | "youth";

export interface Contract {
  id: string;
  player_id: string;
  contract_type: ContractType;
  start_date: string;
  end_date: string;
  signing_date: string | null;
  ownership_percentage: number;
  total_gross_amount: number | null;
  salary_currency: string;
  fixed_bonus: string;
  variable_bonus: string;
  salary_increase: string;
  purchase_option: string;
  release_clause: string;
  renewal_option: string;
  agent_name: string;
  notes: string;
  season_label: string;
  /** When false, the API redacted salary fields for the current viewer. */
  salary_visible: boolean;
}

export interface ContractCreateIn {
  player_id: string;
  contract_type?: ContractType;
  start_date: string;
  end_date: string;
  signing_date?: string | null;
  ownership_percentage?: number;
  total_gross_amount?: number | null;
  salary_currency?: string;
  fixed_bonus?: string;
  variable_bonus?: string;
  salary_increase?: string;
  purchase_option?: string;
  release_clause?: string;
  renewal_option?: string;
  agent_name?: string;
  notes?: string;
}

export interface PlayerSummary {
  id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  sex: Sex;
  nationality: string;
  is_active: boolean;
  status: PlayerStatus;
  category_id: string;
  position: Position | null;
  current_weight_kg: number | null;
  current_height_cm: number | null;
}

/** Create payload for `POST /api/players`. */
export interface PlayerCreateIn {
  first_name: string;
  last_name: string;
  date_of_birth?: string | null;
  sex?: Sex;
  nationality?: string;
  is_active?: boolean;
  category_id: string;
  position_id?: string | null;
  current_weight_kg?: number | null;
  current_height_cm?: number | null;
}

/** Partial update for `PATCH /api/players/{id}`. */
export interface PlayerPatchIn {
  first_name?: string;
  last_name?: string;
  date_of_birth?: string | null;
  sex?: Sex;
  nationality?: string;
  is_active?: boolean;
  category_id?: string;
  position_id?: string | null;
  current_weight_kg?: number | null;
  current_height_cm?: number | null;
}

export interface PlayerDetail {
  id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  sex: Sex;
  nationality: string;
  is_active: boolean;
  status: PlayerStatus;
  club: Club;
  category: Category;
  position: Position | null;
  current_contract: Contract | null;
  current_weight_kg: number | null;
  current_height_cm: number | null;
  age: number | null;
  open_episode_count: number;
}

export type ExamFieldType =
  | "number"
  | "text"
  | "categorical"
  | "calculated"
  | "boolean"
  | "date"
  | "file";

export interface ExamField {
  key: string;
  label: string;
  type: ExamFieldType;
  unit?: string;
  group?: string;
  options?: string[];
  /** Optional display labels for categorical options. The dropdown shows
   *  the label; the canonical option string is what's stored. Useful to
   *  keep storage in a stable vocabulary (e.g. English keys for episode
   *  stages) while showing localized strings to the doctor. */
  option_labels?: Record<string, string>;
  /** Optional region map for the body_map_heatmap widget. Maps each option
   *  string to a body region name (e.g. {"Muslo der.": "right_thigh"}). */
  option_regions?: Record<string, string>;
  /** Optional grouping for long categorical option lists. Maps each option
   *  string to its group label (e.g. {"paracetamol": "Analgésicos"}). When
   *  set, the form renders a two-step cascade: pick group → pick option.
   *  The saved value is still just the option string; the group is a UI
   *  affordance only. Options without a group entry land in "Sin categoría". */
  option_groups?: Record<string, string>;
  formula?: string;
  chart_type?: string;
  required?: boolean;
  /** When true on a `text` field, renders a textarea instead of a single-line input. */
  multiline?: boolean;
  /** Optional row count hint for multiline text fields. */
  rows?: number;
  /** Hint text shown inside empty inputs. */
  placeholder?: string;
  /** Clinical reference bands for numeric/calculated fields. Drives the
   *  form hint shown below the input (compact static + dynamic active
   *  band as the user types) and widget cell-border coloring downstream. */
  reference_ranges?: ReferenceBand[];
  /** Coloring opinion for variation deltas on widgets. */
  direction_of_good?: "up" | "down" | "neutral";
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

export interface ExamTeamTableConfig {
  /** Field keys asked once at the top of the form (e.g. fecha). */
  shared_fields?: string[];
  /** Field keys rendered as one column per — defaults to all non-shared,
   *  non-calculated fields in declared order when omitted. */
  row_fields?: string[];
  /** When true, inactive players are included in the roster. Default false. */
  include_inactive?: boolean;
}

export interface ExamInputConfig {
  input_modes: ExamInputMode[];
  default_input_mode?: ExamInputMode;
  modifiers?: ExamInputModifiers;
  /** Optional column-mapping config used by bulk_ingest mode. */
  column_mapping?: Record<string, unknown>;
  /** Optional team-table config: which fields are shared (asked once)
   *  vs per-row (one column per). */
  team_table?: ExamTeamTableConfig;
  /** When true, the single-mode form shows a match picker so the result
   *  can be linked to a calendar event (and recorded_at derived from it). */
  allow_event_link?: boolean;
}

export interface EpisodeConfig {
  stage_field: string;
  open_stages: string[];
  closed_stage: string;
  title_template?: string;
}

export interface ExamTemplate {
  id: string;
  name: string;
  /** Stable identifier used in formula references like `[<slug>.<field_key>]`. */
  slug: string;
  department: Department;
  version: number;
  config_schema: ExamConfigSchema;
  input_config?: ExamInputConfig;
  /** When true, data-entry forms (single + bulk + team) show a match selector
   *  whose pick overrides recorded_at and is FK-stored on every result. */
  link_to_match: boolean;
  /** When true, results form linked Episodes (e.g. injuries). The registrar
   *  prompts the user to pick a new or existing episode. */
  is_episodic?: boolean;
  episode_config?: EpisodeConfig;
  /** When true, the registrar shows an inline panel with the player's open
   *  injuries plus a "+ Registrar lesión" button (opens the Lesiones form
   *  in a modal). For non-episodic exam templates that benefit from injury
   *  context (daily notes, GPS uploads, etc.). */
  show_injuries?: boolean;
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
  /** Audit-of-record: every external value (player.X / <slug>.Y) the formula
   *  engine resolved at calculation time. Empty when no namespace refs were used. */
  inputs_snapshot?: Record<string, unknown>;
  event?: ExamResultEventBrief | null;
}

// ---------- Team-table batch submission ----------

export interface TeamResultRowIn {
  player_id: string;
  result_data: Record<string, unknown>;
}

export interface TeamResultsIn {
  template_id: string;
  category_id: string;
  recorded_at: string;
  /** When set, every saved row is linked to this event and `recorded_at`
   *  is overridden server-side to the event's `starts_at`. */
  event_id?: string;
  shared_data: Record<string, unknown>;
  rows: TeamResultRowIn[];
}

export interface TeamResultsOut {
  created: number;
  skipped: number;
  results: ExamResult[];
}

// ---------- Goals & Alerts ----------

export type GoalOperator = "<=" | "<" | "==" | ">=" | ">";
export type GoalStatus = "active" | "met" | "missed" | "cancelled";

export interface GoalProgress {
  /** Whether `current_value` already satisfies `operator target_value`.
   *  Null when no reading exists. */
  achieved: boolean | null;
  /** Signed delta `current_value - target_value`. */
  distance: number | null;
  /** Same delta as a % of `target_value`. Null when target is 0. */
  distance_pct: number | null;
}

export interface Goal {
  id: string;
  player_id: string;
  template_id: string;
  template_name: string;
  field_key: string;
  field_label: string;
  field_unit: string;
  operator: GoalOperator;
  target_value: number;
  due_date: string; // YYYY-MM-DD
  notes: string;
  status: GoalStatus;
  /** Value the scheduled evaluator stored at the last run — may be stale.
   *  Use `current_value` for live displays. */
  last_value: number | null;
  evaluated_at: string | null;
  /** Days before due_date to start firing pre-deadline warnings. null/0 disables. */
  warn_days_before: number | null;
  created_at: string;
  /** Live current value (latest reading on this player+template family+field).
   *  Computed at every list/get; distinct from `last_value`. */
  current_value: number | null;
  current_recorded_at: string | null;
  progress: GoalProgress;
}

/** Per-player goal_card widget payload. */
export interface GoalCardPayload {
  chart_type: "goal_card";
  title: string;
  cards: {
    id: string;
    template_name: string;
    field_key: string;
    field_label: string;
    field_unit: string;
    operator: GoalOperator;
    target_value: number;
    due_date: string;
    days_to_due: number;
    current_value: number | null;
    current_recorded_at: string | null;
    progress: GoalProgress;
    notes: string;
  }[];
  empty?: boolean;
}

export interface GoalCreateIn {
  player_id: string;
  template_id: string;
  field_key: string;
  operator: GoalOperator;
  target_value: number;
  due_date: string;
  notes?: string;
  warn_days_before?: number | null;
}

// ---------- Attachments ----------

export type AttachmentSourceType =
  | "contract"
  | "exam_field"
  | "exam_result"
  | "event";

export interface Attachment {
  id: string;
  source_type: AttachmentSourceType;
  source_id: string;
  field_key: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  label: string;
  uploaded_at: string;
}

export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "active" | "dismissed" | "resolved";
export type AlertSource = "goal" | "goal_warning" | "threshold";

export interface Alert {
  id: string;
  player_id: string;
  source_type: AlertSource;
  source_id: string;
  severity: AlertSeverity;
  status: AlertStatus;
  message: string;
  fired_at: string;
  /** Most-recent trigger time. Equal to fired_at on first fire; refreshes on re-trigger. */
  last_fired_at: string | null;
  /** How many times the source rule has triggered since this alert was raised. */
  trigger_count: number;
  dismissed_at: string | null;
}

/** AlertOut + embedded player summary, returned by GET /api/alerts. */
export interface AlertWithPlayer extends Alert {
  player_first_name: string;
  player_last_name: string;
  player_category_name: string;
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
/** One row in an activity-log timeline. Each `fields` entry is a raw
 *  key/value pair from the result so the frontend can render arbitrary
 *  schemas without compile-time knowledge of which fields exist. */
export interface ActivityLogField {
  key: string;
  label: string;
  unit: string;
  value: string | number | boolean | null;
}

export interface ActivityLogEntry {
  id: string;
  recorded_at: string;
  template_name: string;
  fields: ActivityLogField[];
}

export interface ActivityLogPayload {
  chart_type: "activity_log";
  title: string;
  entries: ActivityLogEntry[];
  limit: number;
  empty?: boolean;
  error?: string;
}

export type WidgetData =
  | ComparisonTablePayload
  | LineWithSelectorPayload
  | DonutPerResultPayload
  | GroupedBarPayload
  | MultiLinePayload
  | CrossExamLinePayload
  | BodyMapHeatmapPayload
  | GoalCardPayload
  | PlayerAlertsPayload
  | ActivityLogPayload
  | UnsupportedPayload
  | EmptyPayload;

/** Clinical reference band: a labeled numeric range with optional color.
 *  Either `min` or `max` (or both) is present — bands are disjoint and
 *  ordered low→high. Server-side validation lives in `TemplateField._validate_reference_ranges`. */
export interface ReferenceBand {
  label: string;
  min?: number;
  max?: number;
  color?: string;
}

export interface FieldMeta {
  key: string;
  label: string;
  unit: string;
  group: string;
  type: string;
  /** When present, drives form hint + cell-border coloring on widgets. */
  reference_ranges?: ReferenceBand[];
  direction_of_good?: "up" | "down" | "neutral";
}

export interface ComparisonTablePayload {
  chart_type: "comparison_table";
  columns: { result_id: string; recorded_at: string }[];
  rows: (FieldMeta & {
    values: (number | string | boolean | null)[];
    deltas: (number | null)[];
  })[];
}

export interface LineWithSelectorOption extends FieldMeta {
  field_key?: string;
  template_id?: string;
  template_label?: string;
}

export interface LineWithSelectorPayload {
  chart_type: "line_with_selector";
  available_fields: LineWithSelectorOption[];
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

export interface BodyMapStageInfo {
  value: string;
  label: string;
  kind: "open" | "closed";
}

export interface BodyMapHeatmapPayload {
  chart_type: "body_map_heatmap";
  field: FieldMeta;
  /** Region → count map (only regions with non-zero counts are present).
   *  Always reflects ALL stages combined; client-side filter recomputes
   *  from `counts_by_stage` when a stage is selected. */
  counts: Record<string, number>;
  /** When the source template is episodic with a stage_field, this map
   *  pre-buckets counts by the stage value (e.g. injured / recovery). */
  counts_by_stage: Record<string, Record<string, number>>;
  /** Ordered stage list for the chip selector (worst → best, then closed). */
  stages: BodyMapStageInfo[];
  /** Stage field key (empty string when the template isn't episodic). */
  stage_field_key: string;
  max_count: number;
  /** Per-region detail with the contributing options + their labels. Used
   *  for tooltips so the doctor sees "Muslo der. — 3" not "right_thigh — 3". */
  items: {
    region: string;
    count: number;
    options: { value: string; label: string; count: number }[];
  }[];
  total_results: number;
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
  chart_height: number | null;
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

// ---------- Team reports ----------

/** Per-player horizontal bar groups, one bar per recent reading.
 *
 *  `fields` lists every metric the admin configured on the data source —
 *  the widget renders a dropdown to switch between them client-side (no
 *  refetch). `default_field_key` is the one shown on first load. Each row's
 *  `values` is keyed by field_key so the dropdown change is a pure
 *  client-side selector.
 */
/** A position bucket emitted when `grouping === "position"`. */
export interface TeamPositionGroup {
  id: string;
  /** Short label (typically the position abbreviation: POR / DF / MC / DEL). */
  label: string;
  /** Full position name for tooltips. */
  name: string;
  color: string;
}

export interface TeamHorizontalComparisonPayload {
  chart_type: "team_horizontal_comparison";
  title: string;
  /** "none" (default — one row per player) or "position" (rows = positions,
   *  bars = monthly means across players in that position). */
  grouping?: "none" | "position";
  /** Render mode:
   *  - "by_reading" (default): dropdown picks which field, bars within a
   *    row represent recent readings of that field (most-recent → oldest).
   *  - "multi_field": no dropdown; each row shows one bar per field_key
   *    side by side, each field gets its own color. Each value is the
   *    latest reading in the data window. */
  mode?: "by_reading" | "multi_field";
  fields: { key: string; label: string; unit: string }[];
  default_field_key: string;
  limit_per_player: number;
  /** Present only when `grouping === "position"`. */
  groups?: TeamPositionGroup[];
  /** Shape depends on `grouping`:
   *   - "none":     one row per player (with `player_id`, `player_name`).
   *   - "position": one row per position (with `group_id`, `group_label`,
   *                 `group_name`, `color`). */
  rows: (
    | {
        player_id: string;
        player_name: string;
        values: Record<string, { value: number; label: string; iso: string }[]>;
      }
    | {
        group_id: string;
        group_label: string;
        group_name: string;
        color: string;
        values: Record<string, { value: number; label: string; iso: string }[]>;
      }
  )[];
  empty?: boolean;
  error?: string;
}

/** Roster × metrics matrix — rows = players, columns = field keys.
 *
 *  Each cell is the player's *latest* numeric value for that field; cells
 *  for fields the player has no readings on are absent from the dict (the
 *  frontend renders them as "—"). `ranges` carry the team-wide min/max per
 *  field for `vs_team_range` cell coloring.
 */
export interface TeamRosterMatrixPayload {
  chart_type: "team_roster_matrix";
  title: string;
  columns: {
    key: string;
    label: string;
    unit: string;
    /** Drives delta coloring (green/red). When omitted or "neutral"
     *  the frontend keeps the existing blue/orange neutral palette. */
    direction_of_good?: "up" | "down" | "neutral";
    /** Reference bands for cell border coloring. Empty / undefined = no
     *  band-based treatment, cell renders with its current background. */
    reference_ranges?: ReferenceBand[];
  }[];
  ranges: Record<string, { min: number; max: number }>;
  rows: {
    player_id: string;
    player_name: string;
    cells: Record<
      string,
      {
        value: number;
        iso: string;
        /** Set when `variation != "off"` AND a prior numeric reading exists. */
        previous_value?: number;
        previous_iso?: string;
      }
    >;
  }[];
  coloring: "none" | "vs_team_range";
  /** Cell delta vs prior numeric reading on the same field.
   *  - `off`     — hide
   *  - `absolute` — `▲ +1.6`
   *  - `percent`  — `▼ -2.0%`
   */
  variation: "off" | "absolute" | "percent";
  empty?: boolean;
  error?: string;
}

/** Squad availability snapshot. `available_count / total` is the headline.
 *  `stages[0]` is always the `available` bucket (synthetic — players with no
 *  open episode); the remainder follow `episode_config.open_stages` in the
 *  template's declared order (worst → best). */
export interface TeamStatusCountsPayload {
  chart_type: "team_status_counts";
  title: string;
  stages: {
    value: string;
    label: string;
    kind: "available" | "open";
    count: number;
    color: string;
    players: { id: string; name: string }[];
  }[];
  available_count: number;
  total: number;
  empty?: boolean;
  error?: string;
}

/** Multi-series line chart of team averages over time.
 *  When `grouping === "position"`, the team-wide mean splits into one
 *  line per position (POR/DF/MC/DEL). Bucket values are then keyed by
 *  group id, not by field key. */
export interface TeamTrendLinePayload {
  chart_type: "team_trend_line";
  title: string;
  grouping?: "none" | "position";
  fields: { key: string; label: string; unit: string }[];
  default_field_key: string;
  bucket_size: "week" | "month";
  /** Present only when `grouping === "position"`. */
  groups?: TeamPositionGroup[];
  buckets: {
    label: string;
    iso: string;
    /** Present when `grouping === "none"` (or omitted = "none"). */
    values?: Record<string, number>;
    /** Present when `grouping === "position"`. Mapping position_id →
     *  field_key → mean. Missing field keys = no data that bucket. */
    values_by_group?: Record<string, Record<string, number>>;
  }[];
  empty?: boolean;
  error?: string;
}

/** Histogram of latest values across the roster for one metric. */
/** Per-band count summary emitted when the field has `reference_ranges`
 *  configured AND the widget hasn't opted out via
 *  `display_config.coloring === "none"`. Renders as the chip row under
 *  the stats. Entries with `count: 0` are kept so the row is consistent
 *  across renders. */
export interface TeamDistributionBandCount {
  label: string;
  color?: string;
  /** Inclusive lower bound; null for the lowest band (open-left). */
  min: number | null;
  /** Inclusive upper bound; null for the highest band (open-right). */
  max: number | null;
  count: number;
}

export interface TeamDistributionPayload {
  chart_type: "team_distribution";
  title: string;
  field: { key: string; label: string; unit: string } | null;
  bin_count: number;
  bins: {
    low: number;
    high: number;
    count: number;
    players: { id: string; name: string; value: number }[];
    /** Hex color of the band the bin's midpoint falls into. Present only
     *  when band coloring is active. Frontend falls back to the default
     *  violet when absent. */
    color?: string;
    /** Band label (e.g. "Élite", "Bueno"). Present only when band
     *  coloring is active and the bin midpoint falls inside a band. */
    band_label?: string;
  }[];
  stats: {
    n?: number;
    mean?: number;
    median?: number;
    min?: number;
    max?: number;
  };
  /** Present only when band coloring is active. One entry per declared
   *  band, in declaration order (worst-to-best or vice versa, whichever
   *  the template chose). */
  band_counts?: TeamDistributionBandCount[];
  /** Size of the (filtered) roster the backend resolved against, used by
   *  the frontend to flag "small-N" distributions with a warning badge. */
  roster_size?: number;
  empty?: boolean;
  error?: string;
}

/** One active alert row, shared between the per-player widget and the
 *  team widget (each player card embeds a list of these). */
export interface AlertItem {
  id: string;
  source_type: "goal" | "goal_warning" | "threshold" | "medication" | string;
  source_id?: string;
  severity: "info" | "warning" | "critical" | string;
  message: string;
  fired_at: string;
  last_fired_at?: string | null;
  trigger_count?: number;
  template_name?: string;
  field_key?: string;
}

/** Per-player active-alerts list, scoped to the widget's department. */
export interface PlayerAlertsPayload {
  chart_type: "player_alerts";
  title: string;
  department_id: string;
  department_name: string;
  alerts: AlertItem[];
  total: number;
  empty?: boolean;
  error?: string;
}

/** Team mean per (field × day). One bucket per day in the window,
 *  each carrying the mean of every configured field across the roster.
 *  Optional overlay line for the per-day sum of bar values. */
export interface TeamDailyGroupedBarsPayload {
  chart_type: "team_daily_grouped_bars";
  title: string;
  fields: {
    key: string;
    label: string;
    unit: string;
    color: string;
  }[];
  buckets: {
    iso: string;
    label: string;
    values: Record<string, number | null>;
    total: number | null;
  }[];
  show_total_line: boolean;
  total_label: string;
  total_color: string;
  /** Fixed Y-axis domain for the BARS axis (left). Optional. */
  y_min?: number | null;
  y_max?: number | null;
  /** Fixed Y-axis domain for the TOTAL LINE axis (right). Optional. */
  total_y_min?: number | null;
  total_y_max?: number | null;
  /** Forced decimal precision for tooltip values. Optional. */
  decimals?: number | null;
  empty?: boolean;
  error?: string;
}

/** Compact stat-cards strip aggregating one match across the roster.
 *  Each card = one field with SUM / AVG / STD / MIN / MAX / N. */
export interface TeamMatchSummaryPayload {
  chart_type: "team_match_summary";
  title: string;
  cards: {
    field_key: string;
    label: string;
    unit: string;
    sum: number | null;
    avg: number | null;
    std: number | null;
    min: number | null;
    max: number | null;
    n: number;
  }[];
  sample_size: number;
  per_player_aggregator?: "sum" | "avg" | "max" | "latest";
  empty?: boolean;
  error?: string;
}

/** Stacked horizontal bars per player. One bar per row, composed of N
 *  colored segments (one per configured field_key). Sorted by total
 *  across all stacked fields. Use case: Acc + Dec + Acc&Dec breakdown. */
export interface TeamStackedBarsPayload {
  chart_type: "team_stacked_bars";
  title: string;
  fields: {
    key: string;
    label: string;
    unit: string;
    color: string;
  }[];
  aggregator: "sum" | "avg" | "max" | "latest";
  order: "asc" | "desc";
  rows: {
    player_id: string;
    player_name: string;
    /** Per-field value or null when the player has no readings on that
     *  field. The stack drops the segment when null. */
    values: Record<string, number | null>;
    total: number;
  }[];
  empty?: boolean;
  error?: string;
}

/** Team-wide activity-log timeline. Same shape as the per-player
 *  ActivityLogPayload but every entry carries `player_id` / `player_name`. */
export interface TeamActivityLogEntry extends ActivityLogEntry {
  player_id: string;
  player_name: string;
}

export interface TeamActivityLogPayload {
  chart_type: "team_activity_log";
  title: string;
  entries: TeamActivityLogEntry[];
  limit: number;
  empty?: boolean;
  error?: string;
}

/** Team-wide active-alerts ranking, scoped to the widget's department. */
export interface TeamAlertsPayload {
  chart_type: "team_alerts";
  title: string;
  department_id: string;
  department_name: string;
  players: {
    player_id: string;
    player_name: string;
    alert_count: number;
    critical_count: number;
    max_severity: "info" | "warning" | "critical" | string;
    alerts: AlertItem[];
  }[];
  total_alerts: number;
  empty?: boolean;
  error?: string;
}

/** Currently-active records, keyed on date-range fields. */
export interface TeamActiveRecordsPayload {
  chart_type: "team_active_records";
  title: string;
  columns: { key: string; label: string; unit: string }[];
  rows: {
    player_id: string;
    player_name: string;
    started_at: string;
    ends_at: string | null;
    values: Record<string, unknown>;
  }[];
  as_of: string;
  active_count: number;
  total: number;
  start_field?: string;
  end_field?: string;
  empty?: boolean;
  error?: string;
}

/** Top-N ranking. Two modes:
 *  - "single" (default): one metric ranked top-N.
 *  - "multi_field": every roster player gets a value per configured
 *    field. Sorted by the FIRST field's value (move data source's
 *    field_keys order to change the sort key). Frontend renders grouped
 *    vertical bars: one group per player, one bar per field. */
export interface TeamLeaderboardPayload {
  chart_type: "team_leaderboard";
  title: string;
  mode?: "single" | "multi_field";
  /** Single-mode rendering style. `list` = podium-style ordered list
   *  (legacy, default). `vertical_bars` = vertical bar chart with every
   *  roster player visible — required when using `reference_lines`. */
  style?: "list" | "vertical_bars";
  /** Legacy single ref line. New frontends prefer `reference_lines`. */
  reference_line?: {
    value: number;
    label: string;
    color: string;
  } | null;
  /** Array of horizontal lines (target, upper/lower limit, team avg). */
  reference_lines?: {
    value: number;
    label: string;
    color: string;
  }[];
  /** Shaded horizontal zones between two Y values (clinical "safe zone"). */
  reference_bands?: {
    min: number | null;
    max: number | null;
    label: string;
    color: string;
  }[];
  /** Zoom the Y axis to a custom range. Useful when values cluster near
   *  a non-zero number (urine specific gravity 1.000–1.040, etc.) and
   *  the default `0 → max` rendering crushes the differences. Both
   *  optional; missing falls back to auto (y_min=0, y_max=data max). */
  y_min?: number | null;
  y_max?: number | null;
  /** Forced decimal precision for displayed values. When null/undefined
   *  the frontend picks 0-2 dynamically. Bump to 3 for densities, pH. */
  decimals?: number | null;
  /** Present in "single" mode; null otherwise. */
  field?: { key: string; label: string; unit: string } | null;
  /** Present in "multi_field" mode — one entry per configured field. */
  fields?: { key: string; label: string; unit: string }[];
  aggregator: "sum" | "avg" | "max" | "latest";
  order: "asc" | "desc";
  limit: number;
  rows: (
    | {
        rank: number;
        player_id: string;
        player_name: string;
        value: number;
        samples: number;
      }
    | {
        rank: number;
        player_id: string;
        player_name: string;
        values: Record<string, number | null>;
      }
  )[];
  empty?: boolean;
  error?: string;
}

/** Roster × goals matrix. Each column is a distinct (template, field,
 *  operator, target) combo; rows are players. Cells carry current
 *  value + progress vs target + status bucket. */
export interface TeamGoalProgressPayload {
  chart_type: "team_goal_progress";
  title: string;
  columns: {
    key: string;
    template_name: string;
    field_label: string;
    field_unit: string;
    operator: GoalOperator;
    target_value: number;
  }[];
  rows: {
    player_id: string;
    player_name: string;
    cells: Record<
      string,
      {
        goal_id: string;
        current_value: number | null;
        progress: GoalProgress;
        due_date: string;
        days_to_due: number;
        status: "achieved" | "in_progress" | "missed" | "no_data";
      }
    >;
  }[];
  /** Aggregate counts across every cell — useful for a header summary. */
  summary: {
    achieved: number;
    in_progress: number;
    missed: number;
    no_data: number;
    total: number;
  };
  empty?: boolean;
  error?: string;
}

/** Roster × templates matrix tracking days-since-last-result per cell.
 *  Operational "who's overdue for evaluation?" report. */
export interface TeamActivityCoveragePayload {
  chart_type: "team_activity_coverage";
  title: string;
  /** One per template configured on the widget. */
  columns: { key: string; label: string; slug: string }[];
  /** Day thresholds for the green / yellow / red bucket boundaries.
   *  Days-since ≤ green_max ⇒ ok; ≤ yellow_max ⇒ due; otherwise overdue. */
  thresholds: { green_max: number; yellow_max: number };
  rows: {
    player_id: string;
    player_name: string;
    cells: Record<
      string,
      {
        days_since: number | null;
        last_iso: string | null;
        status: "ok" | "due" | "overdue" | "never";
      }
    >;
  }[];
  as_of: string;
  empty?: boolean;
  error?: string;
}

export type TeamWidgetData =
  | TeamHorizontalComparisonPayload
  | TeamRosterMatrixPayload
  | TeamStatusCountsPayload
  | TeamTrendLinePayload
  | TeamDistributionPayload
  | TeamActiveRecordsPayload
  | TeamActivityCoveragePayload
  | TeamLeaderboardPayload
  | TeamGoalProgressPayload
  | TeamAlertsPayload
  | TeamStackedBarsPayload
  | TeamMatchSummaryPayload
  | TeamActivityLogPayload
  | TeamDailyGroupedBarsPayload
  | UnsupportedPayload
  | EmptyPayload;

export interface TeamReportWidget {
  id: string;
  chart_type: string;
  title: string;
  description: string;
  column_span: number;
  chart_height: number | null;
  sort_order: number;
  data: TeamWidgetData;
}

export interface TeamReportSection {
  id: string;
  title: string;
  is_collapsible: boolean;
  default_collapsed: boolean;
  sort_order: number;
  widgets: TeamReportWidget[];
}

export interface TeamMatchOption {
  id: string;
  title: string;
  starts_at: string;
  location: string;
}

export interface TeamMatchSelectorConfig {
  enabled: boolean;
  event_type: string;
  required: boolean;
  label: string;
  show_recent: number;
  options: TeamMatchOption[];
  /** The match the backend resolved against. May be set even when the
   *  user didn't pass `?match_id=` — required-mode layouts auto-pick
   *  the most recent match. The frontend should sync its URL to this
   *  value on first load. */
  selected_id: string | null;
}

export interface TeamReportResponse {
  layout: {
    id: string;
    department: Department;
    category: Category;
    name: string;
    sections: TeamReportSection[];
    match_selector: TeamMatchSelectorConfig;
  } | null;
}
