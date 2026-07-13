"use client";

import React, { useMemo, useState } from "react";
import { FlaskConical, Save, Trash2, X } from "lucide-react";

import { ApiError } from "@/lib/api";
import {
  type AlertRuleDTO,
  type BacktestResult,
  type RuleDraft,
  type RuleKind,
  type RuleMeta,
  backtestRule,
  createRule,
  deleteRule,
  updateRule,
} from "@/lib/alertRules";
import styles from "./page.module.css";

// Temporarily simplified for the first rollout (client, 2026-07-13): hide the
// Línea/posición scope (positions/líneas aren't set up yet) and the
// all-categories toggle. Existing rules still keep their scope.roles / null
// category on save — flip these back to `true` to re-expose the controls.
const SHOW_LINEA_SCOPE: boolean = false;
const SHOW_ALL_CATEGORIES: boolean = false;

interface Props {
  meta: RuleMeta;
  categoryId: string;
  categoryName: string;
  initial: AlertRuleDTO | null;
  onSaved: (rule: AlertRuleDTO) => void;
  onDeleted: (id: string) => void;
  onCancel: () => void;
}

type Cfg = Record<string, unknown>;

/** Windows are `{kind:"timedelta",days}` or `{kind:"last_n",n}`. */
function readWindow(cfg: Cfg): { kind: string; value: number } {
  const w = (cfg.window as { kind?: string; days?: number; n?: number }) || {};
  if (w.kind === "last_n") return { kind: "last_n", value: w.n ?? 5 };
  return { kind: "timedelta", value: w.days ?? 28 };
}

export default function RuleForm({
  meta,
  categoryId,
  categoryName,
  initial,
  onSaved,
  onDeleted,
  onCancel,
}: Props) {
  const [templateId, setTemplateId] = useState(
    initial?.template_id || meta.templates[0]?.id || "",
  );
  const [kind, setKind] = useState<RuleKind>(initial?.kind || "bound");
  const [fieldKey, setFieldKey] = useState(initial?.field_key || "");
  const [config, setConfig] = useState<Cfg>(initial?.config || {});
  const [scope, setScope] = useState(initial?.scope || {});
  const [severity, setSeverity] = useState(initial?.severity || "warning");
  const [allCategories, setAllCategories] = useState(
    initial ? initial.category_id === null : false,
  );
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  // Custom message templates stay an admin-only nicety for now; preserve any
  // existing one on edit, default empty on create (no field in this form yet).
  const messageTemplate = initial?.message_template || "";

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const template = useMemo(
    () => meta.templates.find((t) => t.id === templateId),
    [meta.templates, templateId],
  );
  const isBand = kind === "band";
  const fields = isBand ? template?.band_fields ?? [] : template?.numeric_fields ?? [];
  const bandField = isBand ? template?.band_fields.find((f) => f.key === fieldKey) : undefined;

  function patchConfig(next: Cfg) {
    setConfig((c) => ({ ...c, ...next }));
    setBacktest(null); // stale once the rule changes
  }
  function setWindow(k: string, value: number) {
    patchConfig({ window: k === "last_n" ? { kind: "last_n", n: value } : { kind: "timedelta", days: value } });
  }
  function toggleScope(key: keyof typeof scope, value: string) {
    setScope((s) => {
      const cur = new Set((s[key] as string[]) || []);
      if (cur.has(value)) cur.delete(value);
      else cur.add(value);
      const next = { ...s, [key]: [...cur] };
      if (next[key]!.length === 0) delete next[key];
      return next;
    });
    setBacktest(null);
  }

  function draft(): RuleDraft {
    return {
      template_id: templateId,
      field_key: fieldKey,
      kind,
      category_id: allCategories ? null : categoryId,
      config,
      scope,
      severity,
      message_template: messageTemplate,
      is_active: isActive,
    };
  }

  async function runBacktest() {
    setError(null);
    setTesting(true);
    try {
      setBacktest(await backtestRule({ ...draft(), days: 90 }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo simular la regla.");
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const saved = initial
        ? await updateRule(initial.id, draft())
        : await createRule(draft());
      onSaved(saved);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar la regla.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!initial) return;
    setSaving(true);
    try {
      await deleteRule(initial.id);
      onDeleted(initial.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo eliminar.");
      setSaving(false);
    }
  }

  const win = readWindow(config);
  const num = (v: unknown) => (v === undefined || v === null ? "" : String(v));

  return (
    <div className={styles.formCard}>
      <div className={styles.formHead}>
        <h2 className={styles.cardTitle}>{initial ? "Editar regla" : "Nueva regla"}</h2>
        <button type="button" className={styles.iconBtn} onClick={onCancel} aria-label="Cerrar">
          <X size={18} />
        </button>
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      <div className={styles.grid}>
        <label className={styles.field}>
          <span>Examen</span>
          <select
            value={templateId}
            onChange={(e) => {
              setTemplateId(e.target.value);
              setFieldKey("");
              setBacktest(null);
            }}
          >
            {meta.templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.department} · {t.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Tipo de regla</span>
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as RuleKind);
              setFieldKey("");
              setConfig({});
              setBacktest(null);
            }}
          >
            {meta.kinds.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>{isBand ? "Campo (con bandas)" : "Métrica"}</span>
          <select
            value={fieldKey}
            onChange={(e) => {
              setFieldKey(e.target.value);
              setBacktest(null);
            }}
          >
            <option value="">— elegí —</option>
            {fields.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
                {"unit" in f && f.unit ? ` (${f.unit})` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>Severidad</span>
          <select value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)}>
            {meta.severities.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Kind-specific config ------------------------------------------------ */}
      <div className={styles.kindBox}>
        {kind === "bound" && (
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Umbral superior</span>
              <input
                type="number" value={num(config.upper)} placeholder="sin límite"
                onChange={(e) => patchConfig({ upper: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
            </label>
            <label className={styles.field}>
              <span>Umbral inferior</span>
              <input
                type="number" value={num(config.lower)} placeholder="sin límite"
                onChange={(e) => patchConfig({ lower: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
            </label>
          </div>
        )}

        {kind === "variation" && (
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Ventana</span>
              <select value={win.kind} onChange={(e) => setWindow(e.target.value, win.value)}>
                <option value="timedelta">Últimos N días</option>
                <option value="last_n">Últimas N lecturas</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>{win.kind === "last_n" ? "N lecturas" : "N días"}</span>
              <input type="number" value={win.value} min={1}
                onChange={(e) => setWindow(win.kind, Number(e.target.value))} />
            </label>
            <label className={styles.field}>
              <span>Variación (%)</span>
              <input type="number" value={num(config.threshold_pct)} placeholder="p. ej. 15"
                onChange={(e) => patchConfig({ threshold_pct: e.target.value === "" ? undefined : Number(e.target.value) })} />
            </label>
            <label className={styles.field}>
              <span>Dirección</span>
              <select value={(config.direction as string) || "any"}
                onChange={(e) => patchConfig({ direction: e.target.value })}>
                <option value="any">Cualquiera</option>
                <option value="increase">Solo aumento</option>
                <option value="decrease">Solo descenso</option>
              </select>
            </label>
          </div>
        )}

        {kind === "zscore" && (
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Ventana (días)</span>
              <input type="number" value={win.value} min={1}
                onChange={(e) => setWindow("timedelta", Number(e.target.value))} />
            </label>
            <label className={styles.field}>
              <span>Umbral z</span>
              <input type="number" step="0.1" value={num(config.threshold_z)} placeholder="p. ej. 2"
                onChange={(e) => patchConfig({ threshold_z: e.target.value === "" ? undefined : Number(e.target.value) })} />
            </label>
            <label className={styles.field}>
              <span>Método</span>
              <select value={(config.method as string) || "moving_avg"}
                onChange={(e) => patchConfig({ method: e.target.value })}>
                <option value="moving_avg">Media móvil</option>
                <option value="ewma">EWMA (exponencial)</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>Dirección</span>
              <select value={(config.direction as string) || "any"}
                onChange={(e) => patchConfig({ direction: e.target.value })}>
                <option value="any">Cualquiera</option>
                <option value="increase">Solo aumento</option>
                <option value="decrease">Solo descenso</option>
              </select>
            </label>
          </div>
        )}

        {kind === "pct_match" && (
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>≥ % del partido (superior)</span>
              <input type="number" step="0.05" value={num(config.ratio_upper)} placeholder="p. ej. 0.85"
                onChange={(e) => patchConfig({ ratio_upper: e.target.value === "" ? undefined : Number(e.target.value) })} />
            </label>
            <label className={styles.field}>
              <span>≤ % del partido (inferior)</span>
              <input type="number" step="0.05" value={num(config.ratio_lower)} placeholder="opcional"
                onChange={(e) => patchConfig({ ratio_lower: e.target.value === "" ? undefined : Number(e.target.value) })} />
            </label>
          </div>
        )}

        {kind === "band" && (
          <div className={styles.bandBox}>
            <span className={styles.fieldLabel}>Bandas que disparan alerta</span>
            {bandField ? (
              <div className={styles.chips}>
                {bandField.bands.map((b) => {
                  const sel = ((config.trigger_labels as string[]) || []).includes(b);
                  return (
                    <button key={b} type="button"
                      className={sel ? styles.chipOn : styles.chip}
                      onClick={() => {
                        const cur = new Set((config.trigger_labels as string[]) || []);
                        if (cur.has(b)) cur.delete(b);
                        else cur.add(b);
                        patchConfig({ trigger_labels: [...cur] });
                      }}>
                      {b}
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className={styles.hint}>Elegí un campo con bandas. Vacío = las bandas rojas por defecto.</p>
            )}
          </div>
        )}
      </div>

      {/* Scope --------------------------------------------------------------- */}
      <div className={styles.scopeBox}>
        <span className={styles.fieldLabel}>Alcance (opcional — vacío = todo)</span>
        {template && template.session_types.length > 0 && (
          <ScopeChips label="Tipo de sesión" options={template.session_types}
            selected={scope.session_types || []} onToggle={(v) => toggleScope("session_types", v)} />
        )}
        {SHOW_LINEA_SCOPE && meta.roles.length > 0 && (
          <ScopeChips label="Línea / posición" options={meta.roles}
            selected={scope.roles || []} onToggle={(v) => toggleScope("roles", v)} />
        )}
        <ScopeChips label="Día de microciclo" options={meta.microcycle_days}
          selected={scope.microcycle_days || []} onToggle={(v) => toggleScope("microcycle_days", v)} />
      </div>

      <div className={styles.optsRow}>
        <label className={styles.inlineCheck}>
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          Activa
        </label>
        {SHOW_ALL_CATEGORIES && (
          <label className={styles.inlineCheck}>
            <input type="checkbox" checked={allCategories} onChange={(e) => setAllCategories(e.target.checked)} />
            Aplicar a todas las categorías (no solo {categoryName})
          </label>
        )}
      </div>

      {/* Backtest ------------------------------------------------------------ */}
      <div className={styles.backtestBox}>
        <button type="button" className={styles.testBtn} onClick={runBacktest}
          disabled={testing || !fieldKey}>
          <FlaskConical size={16} /> {testing ? "Simulando…" : "Simular (últimos 90 días)"}
        </button>
        {backtest && (
          <div className={styles.backtestResult}>
            <p className={styles.backtestSummary}>
              Habría disparado <strong>{backtest.fired_count}</strong> vez/veces en{" "}
              <strong>{backtest.players_affected}</strong> jugador(es){" "}
              <span className={styles.muted}>
                ({backtest.evaluated} lecturas evaluadas · {backtest.window_days} días)
              </span>
            </p>
            {backtest.players.length > 0 ? (
              <ul className={styles.playerList}>
                {backtest.players.map((p) => (
                  <li key={p.player_id}>
                    <span>{p.name}</span>
                    <span className={styles.muted}>
                      {p.count}× · última {p.last_date} = {p.last_value}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.hint}>Ningún disparo con estos parámetros — probablemente sin falsos positivos.</p>
            )}
          </div>
        )}
      </div>

      <div className={styles.formFooter}>
        {initial && (
          <button type="button" className={styles.deleteBtn} onClick={remove} disabled={saving}>
            <Trash2 size={16} /> Eliminar
          </button>
        )}
        <div className={styles.footerRight}>
          <button type="button" className={styles.secondaryBtn} onClick={onCancel} disabled={saving}>
            Cancelar
          </button>
          <button type="button" className={styles.primaryBtn} onClick={save}
            disabled={saving || !fieldKey || !templateId}>
            <Save size={16} /> {saving ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ScopeChips({
  label, options, selected, onToggle,
}: {
  label: string; options: string[]; selected: string[]; onToggle: (v: string) => void;
}) {
  return (
    <div className={styles.scopeRow}>
      <span className={styles.scopeRowLabel}>{label}</span>
      <div className={styles.chips}>
        {options.map((o) => (
          <button key={o} type="button"
            className={selected.includes(o) ? styles.chipOn : styles.chip}
            onClick={() => onToggle(o)}>
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}
