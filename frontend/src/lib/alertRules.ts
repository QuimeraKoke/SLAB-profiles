// API client + types for the in-app Alert & Threshold editor (§1.g).
// All endpoints are Editor-role gated on the backend.

import { api } from "@/lib/api";

export type RuleKind = "bound" | "variation" | "zscore" | "pct_match" | "band";
export type Severity = "info" | "warning" | "critical";

export interface RuleScope {
  session_types?: string[];
  roles?: string[];
  microcycle_days?: string[];
}

export interface AlertRuleDTO {
  id: string;
  template_id: string;
  template_name: string;
  field_key: string;
  field_label: string;
  category_id: string | null;
  kind: RuleKind;
  config: Record<string, unknown>;
  scope: RuleScope;
  severity: Severity;
  message_template: string;
  is_active: boolean;
  updated_at: string | null;
}

export interface NumericField {
  key: string;
  label: string;
  unit: string;
  has_bands: boolean;
}
export interface BandField {
  key: string;
  label: string;
  bands: string[];
}
export interface TemplateMeta {
  id: string;
  name: string;
  department: string;
  slug: string;
  numeric_fields: NumericField[];
  band_fields: BandField[];
  session_types: string[];
}
export interface RuleMeta {
  templates: TemplateMeta[];
  kinds: { value: RuleKind; label: string }[];
  severities: { value: Severity; label: string }[];
  roles: string[];
  microcycle_days: string[];
}

export interface BacktestPlayer {
  player_id: string;
  name: string;
  count: number;
  last_date: string | null;
  last_value: number | null;
}
export interface BacktestResult {
  window_days: number;
  evaluated: number;
  fired_count: number;
  players_affected: number;
  players: BacktestPlayer[];
}

export interface RuleDraft {
  template_id: string;
  field_key: string;
  kind: RuleKind;
  category_id: string | null;
  config: Record<string, unknown>;
  scope: RuleScope;
  severity: Severity;
  message_template?: string;
  is_active?: boolean;
}

export function fetchRuleMeta(categoryId: string): Promise<RuleMeta> {
  return api<RuleMeta>(`/alert-rules/meta?category_id=${categoryId}`);
}

export function fetchRules(categoryId: string): Promise<{ rules: AlertRuleDTO[] }> {
  return api<{ rules: AlertRuleDTO[] }>(`/alert-rules?category_id=${categoryId}`);
}

export function createRule(draft: RuleDraft): Promise<AlertRuleDTO> {
  return api<AlertRuleDTO>(`/alert-rules`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export function updateRule(
  id: string,
  patch: Partial<RuleDraft>,
): Promise<AlertRuleDTO> {
  return api<AlertRuleDTO>(`/alert-rules/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteRule(id: string): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>(`/alert-rules/${id}`, { method: "DELETE" });
}

export function backtestRule(
  draft: RuleDraft & { days?: number },
): Promise<BacktestResult> {
  return api<BacktestResult>(`/alert-rules/backtest`, {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

// ── ACWR (acute:chronic) config (§1.f) ──────────────────────────────────────

export interface AcwrVariable {
  field: string;
  label: string;
  acute_days: number;
  chronic_days: number;
  method: "moving_avg" | "ewma";
  sweet_low: number;
  sweet_high: number;
  danger_low: number;
  danger_high: number;
  alert: boolean;
  severity: Severity;
}

export interface AcwrConfig {
  variables: AcwrVariable[];
  available_fields: { key: string; label: string; unit: string }[];
  methods: { value: string; label: string }[];
  severities: Severity[];
}

export function fetchAcwrConfig(categoryId: string): Promise<AcwrConfig> {
  return api<AcwrConfig>(`/acwr-config?category_id=${categoryId}`);
}

export function saveAcwrConfig(
  categoryId: string,
  variables: AcwrVariable[],
): Promise<AcwrConfig> {
  return api<AcwrConfig>(`/acwr-config`, {
    method: "PATCH",
    body: JSON.stringify({ category_id: categoryId, variables }),
  });
}
