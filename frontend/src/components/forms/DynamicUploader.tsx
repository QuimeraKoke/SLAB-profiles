"use client";

import React, { useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ExamField, ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./DynamicUploader.module.css";

interface DynamicUploaderProps {
  template: ExamTemplate;
  playerId: string;
  onSaved?: (result: ExamResult) => void;
  onCancel?: () => void;
}

type FormValue = string | number | boolean | null;

function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function defaultValue(field: ExamField): FormValue {
  if (field.type === "boolean") return false;
  if (field.type === "date") return todayISO();
  return "";
}

function groupFields(fields: ExamField[]): { group: string | null; items: ExamField[] }[] {
  const groups = new Map<string | null, ExamField[]>();
  for (const f of fields) {
    if (f.type === "calculated") continue; // never rendered as input
    const key = f.group ?? null;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(f);
  }
  return Array.from(groups.entries()).map(([group, items]) => ({ group, items }));
}

export default function DynamicUploader({
  template,
  playerId,
  onSaved,
  onCancel,
}: DynamicUploaderProps) {
  const fields = template.config_schema?.fields ?? [];
  const grouped = useMemo(() => groupFields(fields), [fields]);
  const calculated = useMemo(
    () => fields.filter((f) => f.type === "calculated"),
    [fields],
  );

  const [values, setValues] = useState<Record<string, FormValue>>(() =>
    Object.fromEntries(
      fields
        .filter((f) => f.type !== "calculated")
        .map((f) => [f.key, defaultValue(f)]),
    ),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setValue = (key: string, value: FormValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Build the raw_data payload, coercing numbers from text inputs.
    const raw: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.type === "calculated") continue;
      const v = values[f.key];
      if (v === "" || v === null) {
        if (f.required) {
          setError(`Falta el campo "${f.label}"`);
          return;
        }
        continue;
      }
      if (f.type === "number") {
        const n = typeof v === "number" ? v : Number(v);
        if (Number.isNaN(n)) {
          setError(`"${f.label}" debe ser un número`);
          return;
        }
        raw[f.key] = n;
      } else {
        raw[f.key] = v;
      }
    }

    setSubmitting(true);
    try {
      const result = await api<ExamResult>("/results", {
        method: "POST",
        body: JSON.stringify({
          player_id: playerId,
          template_id: template.id,
          recorded_at: new Date().toISOString(),
          raw_data: raw,
        }),
      });
      onSaved?.(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al guardar el examen");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.header}>
        <h3 className={styles.title}>{template.name}</h3>
        <span className={styles.version}>v{template.version}</span>
      </div>

      {grouped.map(({ group, items }) => (
        <fieldset className={styles.group} key={group ?? "_default"}>
          {group && <legend className={styles.legend}>{group}</legend>}
          <div className={styles.grid}>
            {items.map((f) => (
              <FieldInput
                key={f.key}
                field={f}
                value={values[f.key]}
                onChange={(v) => setValue(f.key, v)}
              />
            ))}
          </div>
        </fieldset>
      ))}

      {calculated.length > 0 && (
        <p className={styles.calculatedHint}>
          {calculated.length} campo{calculated.length === 1 ? "" : "s"} calculado
          {calculated.length === 1 ? "" : "s"} se computará{calculated.length === 1 ? "" : "n"}{" "}
          automáticamente al guardar.
        </p>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        {onCancel && (
          <button type="button" className={styles.cancelBtn} onClick={onCancel} disabled={submitting}>
            Cancelar
          </button>
        )}
        <button type="submit" className={styles.submitBtn} disabled={submitting}>
          {submitting ? "Guardando…" : "Guardar informe"}
        </button>
      </div>
    </form>
  );
}

interface FieldInputProps {
  field: ExamField;
  value: FormValue;
  onChange: (value: FormValue) => void;
}

function FieldInput({ field, value, onChange }: FieldInputProps) {
  const id = `field-${field.key}`;
  const label = field.unit ? `${field.label} [${field.unit}]` : field.label;

  if (field.type === "boolean") {
    return (
      <label htmlFor={id} className={styles.checkboxLabel}>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
    );
  }

  if (field.type === "categorical" && field.options?.length) {
    return (
      <label htmlFor={id} className={styles.field}>
        <span className={styles.label}>{label}</span>
        <select
          id={id}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        >
          <option value="">—</option>
          {field.options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (field.type === "text" && field.multiline) {
    return (
      <label htmlFor={id} className={`${styles.field} ${styles.fullWidth}`}>
        <span className={styles.label}>{label}</span>
        <textarea
          id={id}
          rows={field.rows ?? 5}
          placeholder={field.placeholder}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      </label>
    );
  }

  const inputType =
    field.type === "number" ? "number" : field.type === "date" ? "date" : "text";

  return (
    <label htmlFor={id} className={styles.field}>
      <span className={styles.label}>{label}</span>
      <input
        id={id}
        type={inputType}
        step={field.type === "number" ? "any" : undefined}
        placeholder={field.placeholder}
        value={typeof value === "string" || typeof value === "number" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        required={field.required}
      />
    </label>
  );
}
