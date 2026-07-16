"use client";

import React, { useEffect, useState } from "react";
import { Activity, Plus, Trash2 } from "lucide-react";

import { ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast/Toast";
import {
  type AcwrConfig,
  type AcwrVariable,
  type Severity,
  fetchAcwrConfig,
  saveAcwrConfig,
} from "@/lib/alertRules";
import styles from "./AcwrConfigSection.module.css";

interface Props {
  categoryId: string;
  canEdit: boolean;
}

// Numeric fields held as strings so decimals type cleanly; coerced on save.
interface Draft {
  field: string;
  label: string;
  method: "moving_avg" | "ewma";
  acute_days: string;
  chronic_days: string;
  sweet_low: string;
  sweet_high: string;
  danger_low: string;
  danger_high: string;
  alert: boolean;
  severity: Severity;
}

const SEV_LABEL: Record<string, string> = {
  info: "Informativa",
  warning: "Advertencia",
  critical: "Crítica",
};

function toDraft(v: AcwrVariable): Draft {
  return {
    field: v.field,
    label: v.label,
    method: v.method,
    acute_days: String(v.acute_days),
    chronic_days: String(v.chronic_days),
    sweet_low: String(v.sweet_low),
    sweet_high: String(v.sweet_high),
    danger_low: String(v.danger_low),
    danger_high: String(v.danger_high),
    alert: v.alert,
    severity: v.severity,
  };
}

function toVariable(d: Draft): AcwrVariable {
  const n = (s: string, fallback: number) => (s.trim() === "" || isNaN(Number(s)) ? fallback : Number(s));
  return {
    field: d.field,
    label: d.label || d.field,
    method: d.method,
    acute_days: Math.max(1, Math.round(n(d.acute_days, 7))),
    chronic_days: Math.max(1, Math.round(n(d.chronic_days, 28))),
    sweet_low: n(d.sweet_low, 0.8),
    sweet_high: n(d.sweet_high, 1.3),
    danger_low: n(d.danger_low, 0.7),
    danger_high: n(d.danger_high, 1.5),
    alert: d.alert,
    severity: d.severity,
  };
}

const BLANK: Draft = {
  field: "", label: "", method: "moving_avg",
  acute_days: "7", chronic_days: "28",
  sweet_low: "0.8", sweet_high: "1.3", danger_low: "0.7", danger_high: "1.5",
  alert: false, severity: "warning",
};

/** ACWR (§1.f) — per-category acute:chronic config: monitored variable(s),
 *  window days (acute/chronic), method, and the target + risk limit bands.
 *  Editable in place; feeds the roster readiness, command-center KPI and (when
 *  "alertar" is on) the alert engine. */
export default function AcwrConfigSection({ categoryId, canEdit }: Props) {
  const { toast } = useToast();
  const [cfg, setCfg] = useState<AcwrConfig | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    fetchAcwrConfig(categoryId)
      .then((c) => {
        if (cancelled) return;
        setCfg(c);
        setDrafts(c.variables.map(toDraft));
      })
      .catch(() => {
        if (!cancelled) setCfg(null);
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  function update(i: number, patch: Partial<Draft>) {
    setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  }
  function addVar() {
    const first = cfg?.available_fields[0];
    setDrafts((ds) => [
      ...ds,
      { ...BLANK, field: first?.key ?? "tot_dist", label: first?.label ?? "" },
    ]);
  }
  function removeVar(i: number) {
    setDrafts((ds) => ds.filter((_, j) => j !== i));
  }

  async function save() {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await saveAcwrConfig(categoryId, drafts.map(toVariable));
      setCfg(saved);
      setDrafts(saved.variables.map(toDraft));
      toast.success("Configuración de ACWR guardada.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo guardar el ACWR.");
    } finally {
      setBusy(false);
    }
  }

  if (!cfg) return null;

  const fieldOptions = (d: Draft) => {
    const opts = [...(cfg.available_fields ?? [])];
    if (d.field && !opts.some((f) => f.key === d.field)) {
      opts.unshift({ key: d.field, label: d.label || d.field, unit: "" });
    }
    return opts;
  };

  return (
    <section className={styles.card}>
      <button
        type="button"
        className={styles.head}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className={styles.headTitle}>
          <Activity size={18} aria-hidden="true" /> Cálculo de ACWR (carga aguda:crónica)
        </span>
        <span className={styles.headMeta}>
          {drafts.length} variable{drafts.length === 1 ? "" : "s"}
          <span className={styles.chev}>{open ? "▴" : "▾"}</span>
        </span>
      </button>

      {open && (
        <div className={styles.body}>
          <p className={styles.intro}>
            Relación entre la carga reciente (<strong>aguda</strong>) y la habitual
            (<strong>crónica</strong>). Configurá la ventana en días y los límites: la
            <em> banda objetivo</em> (verde) y el <em>límite de riesgo</em> (rojo).
          </p>

          {drafts.length === 0 && (
            <p className={styles.muted}>Sin variables configuradas. Agregá una para monitorear el ACWR.</p>
          )}

          {drafts.map((d, i) => (
            <div key={i} className={styles.varCard}>
              <div className={styles.varGrid}>
                <label className={styles.field}>
                  <span className={styles.lbl}>Variable</span>
                  <select
                    className={styles.input}
                    value={d.field}
                    disabled={!canEdit}
                    onChange={(e) => {
                      const f = cfg.available_fields.find((x) => x.key === e.target.value);
                      update(i, { field: e.target.value, label: f?.label ?? e.target.value });
                    }}
                  >
                    {fieldOptions(d).map((f) => (
                      <option key={f.key} value={f.key}>{f.label}</option>
                    ))}
                  </select>
                </label>

                <label className={styles.field}>
                  <span className={styles.lbl}>Método</span>
                  <select
                    className={styles.input}
                    value={d.method}
                    disabled={!canEdit}
                    onChange={(e) => update(i, { method: e.target.value as Draft["method"] })}
                  >
                    {cfg.methods.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </label>

                <label className={styles.field}>
                  <span className={styles.lbl}>Ventana aguda (días)</span>
                  <input
                    type="number" min={1} className={styles.input}
                    value={d.acute_days} disabled={!canEdit}
                    onChange={(e) => update(i, { acute_days: e.target.value })}
                  />
                </label>
                <label className={styles.field}>
                  <span className={styles.lbl}>Ventana crónica (días)</span>
                  <input
                    type="number" min={1} className={styles.input}
                    value={d.chronic_days} disabled={!canEdit}
                    onChange={(e) => update(i, { chronic_days: e.target.value })}
                  />
                </label>
              </div>

              <div className={styles.bands}>
                <div className={styles.bandGroup}>
                  <span className={`${styles.bandLabel} ${styles.bandOk}`}>Banda objetivo</span>
                  <label className={styles.limit}>
                    <span className={styles.limSub}>inferior</span>
                    <input type="number" step="0.05" className={styles.limInput}
                      value={d.sweet_low} disabled={!canEdit}
                      onChange={(e) => update(i, { sweet_low: e.target.value })} />
                  </label>
                  <span className={styles.dash}>–</span>
                  <label className={styles.limit}>
                    <span className={styles.limSub}>superior</span>
                    <input type="number" step="0.05" className={styles.limInput}
                      value={d.sweet_high} disabled={!canEdit}
                      onChange={(e) => update(i, { sweet_high: e.target.value })} />
                  </label>
                </div>

                <div className={styles.bandGroup}>
                  <span className={`${styles.bandLabel} ${styles.bandDanger}`}>Límite de riesgo</span>
                  <label className={styles.limit}>
                    <span className={styles.limSub}>inferior</span>
                    <input type="number" step="0.05" className={styles.limInput}
                      value={d.danger_low} disabled={!canEdit}
                      onChange={(e) => update(i, { danger_low: e.target.value })} />
                  </label>
                  <span className={styles.dash}>–</span>
                  <label className={styles.limit}>
                    <span className={styles.limSub}>superior</span>
                    <input type="number" step="0.05" className={styles.limInput}
                      value={d.danger_high} disabled={!canEdit}
                      onChange={(e) => update(i, { danger_high: e.target.value })} />
                  </label>
                </div>
              </div>

              <div className={styles.varFoot}>
                <label className={styles.alertToggle}>
                  <input type="checkbox" checked={d.alert} disabled={!canEdit}
                    onChange={(e) => update(i, { alert: e.target.checked })} />
                  Generar alerta al salir del límite de riesgo
                </label>
                {d.alert && (
                  <select
                    className={styles.sevSelect}
                    value={d.severity}
                    disabled={!canEdit}
                    onChange={(e) => update(i, { severity: e.target.value as Severity })}
                  >
                    {cfg.severities.map((s) => (
                      <option key={s} value={s}>{SEV_LABEL[s] ?? s}</option>
                    ))}
                  </select>
                )}
                {canEdit && (
                  <button type="button" className={styles.removeBtn} onClick={() => removeVar(i)}
                    aria-label="Quitar variable" title="Quitar variable">
                    <Trash2 size={15} />
                  </button>
                )}
              </div>
            </div>
          ))}

          {canEdit && (
            <div className={styles.actions}>
              <button type="button" className={styles.addBtn} onClick={addVar}>
                <Plus size={15} /> Agregar variable
              </button>
              <button type="button" className={styles.saveBtn} disabled={busy} onClick={save}>
                {busy ? "Guardando…" : "Guardar ACWR"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
