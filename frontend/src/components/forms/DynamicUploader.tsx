"use client";

import React, { useEffect, useMemo, useState } from "react";
import AttachmentList from "@/components/ui/AttachmentList/AttachmentList";
import DeferredFilePicker from "@/components/forms/DeferredFilePicker";
import { api, ApiError, getToken } from "@/lib/api";
import type { CalendarEvent, ExamField, ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./DynamicUploader.module.css";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

interface DynamicUploaderProps {
  template: ExamTemplate;
  playerId: string;
  /** For episodic templates: pass an existing episode UUID to continue it,
   *  or undefined / null to open a new episode on submit. */
  episodeId?: string | null;
  /** Pre-populate non-file form values from this map (e.g. continuing an
   *  episode using `episode.latest_result_data`). Ignored when editing. */
  initialValues?: Record<string, unknown>;
  /** When set, the form switches to edit mode: PATCHes the existing result
   *  instead of POSTing a new one. Files are managed via the live
   *  AttachmentList, not the deferred picker. */
  existingResult?: ExamResult;
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
  episodeId,
  initialValues,
  existingResult,
  onSaved,
  onCancel,
}: DynamicUploaderProps) {
  const isEditing = existingResult != null;
  const fields = useMemo(
    () => template.config_schema?.fields ?? [],
    [template.config_schema],
  );
  const grouped = useMemo(() => groupFields(fields), [fields]);
  const calculated = useMemo(
    () => fields.filter((f) => f.type === "calculated"),
    [fields],
  );
  const fileFields = useMemo(
    () => fields.filter((f) => f.type === "file"),
    [fields],
  );

  // Source of truth for initial form values: existing result > caller's
  // initialValues > field defaults. Coerced into FormValue shape.
  //
  // When a source is present (edit / continue-episode), missing keys mean
  // "the doctor left this empty — keep it empty". We DON'T fall back to
  // `defaultValue(f)` (which auto-fills today's date for date fields) — that
  // would silently invent values like a `retorno_efectivo` of today on a
  // diagnosis that hadn't set it yet.
  const startingValues = useMemo<Record<string, FormValue>>(() => {
    const hasSource = existingResult != null || initialValues != null;
    const source = existingResult?.result_data ?? initialValues ?? {};
    return Object.fromEntries(
      fields
        .filter((f) => f.type !== "calculated" && f.type !== "file")
        .map((f) => {
          const raw = source[f.key];
          if (raw === undefined || raw === null) {
            if (hasSource) {
              // Respect the saved blank — don't auto-fill today / 0 / etc.
              return [f.key, f.type === "boolean" ? false : ""];
            }
            return [f.key, defaultValue(f)];
          }
          if (f.type === "boolean") return [f.key, Boolean(raw)];
          if (f.type === "number") {
            return [f.key, typeof raw === "number" ? raw : Number(raw)];
          }
          return [f.key, String(raw)];
        }),
    );
  }, [fields, existingResult, initialValues]);

  const [values, setValues] = useState<Record<string, FormValue>>(startingValues);
  // Files queued client-side per file-field key. Uploaded after the result
  // is created, in handleSubmit's second phase.
  const [queuedFiles, setQueuedFiles] = useState<Record<string, File[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    uploaded: number;
    total: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  // Optional match-event association — only rendered when the template
  // opts in AND we're creating (event_id is immutable on edit).
  const allowEventLink =
    !isEditing &&
    (template.link_to_match === true ||
      template.input_config?.allow_event_link === true);
  const [eventId, setEventId] = useState<string>("");
  const [matches, setMatches] = useState<CalendarEvent[]>([]);

  useEffect(() => {
    if (!allowEventLink) return;
    let cancelled = false;
    api<CalendarEvent[]>(`/events?event_type=match&player_id=${playerId}`)
      .then((data) => {
        if (cancelled) return;
        setMatches(
          [...data].sort(
            (a, b) =>
              new Date(b.starts_at).getTime() - new Date(a.starts_at).getTime(),
          ),
        );
      })
      .catch(() => {
        // Non-fatal — form still works without a match association.
      });
    return () => {
      cancelled = true;
    };
  }, [allowEventLink, playerId]);

  const selectedMatch = useMemo(
    () => matches.find((m) => m.id === eventId) ?? null,
    [matches, eventId],
  );

  const setValue = (key: string, value: FormValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const setQueuedForField = (key: string, files: File[]) => {
    setQueuedFiles((prev) => ({ ...prev, [key]: files }));
  };

  /**
   * Upload all queued files in sequence, attaching each to `result.id`.
   * Returns the count of failures so the caller can surface a warning
   * without blocking the redirect — the result itself is already saved.
   */
  const uploadQueuedFiles = async (resultId: string): Promise<string[]> => {
    const jobs: { fieldKey: string; file: File }[] = [];
    for (const f of fileFields) {
      const files = queuedFiles[f.key] ?? [];
      for (const file of files) {
        jobs.push({ fieldKey: f.key, file });
      }
    }
    if (jobs.length === 0) return [];

    setUploadProgress({ uploaded: 0, total: jobs.length });
    const failures: string[] = [];
    const token = getToken();
    for (let i = 0; i < jobs.length; i++) {
      const { fieldKey, file } = jobs[i];
      try {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("source_type", "exam_field");
        fd.append("source_id", resultId);
        fd.append("field_key", fieldKey);
        const res = await fetch(`${API_URL}/attachments`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          body: fd,
        });
        if (!res.ok) {
          const body = (await res.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(body?.detail ?? `Error ${res.status}`);
        }
      } catch (err) {
        failures.push(`${file.name}: ${err instanceof Error ? err.message : "fallo"}`);
      } finally {
        setUploadProgress({ uploaded: i + 1, total: jobs.length });
      }
    }
    return failures;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setWarning(null);

    // Build the raw_data payload, coercing numbers from text inputs.
    const raw: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.type === "calculated" || f.type === "file") continue;
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

    // Required-file validation: required file fields must have ≥1 file queued.
    // Skipped in edit mode — files are managed by the live AttachmentList
    // and may already exist on the server independently of this submit.
    if (!isEditing) {
      for (const f of fileFields) {
        if (f.required && (queuedFiles[f.key] ?? []).length === 0) {
          setError(`Adjuntá al menos un archivo en "${f.label}"`);
          return;
        }
      }
    }

    setSubmitting(true);
    try {
      if (isEditing && existingResult) {
        // PATCH path: update raw_data on the existing result. Files are
        // managed via AttachmentList in real time — nothing to upload here.
        const result = await api<ExamResult>(`/results/${existingResult.id}`, {
          method: "PATCH",
          body: JSON.stringify({ raw_data: raw }),
        });
        onSaved?.(result);
      } else {
        const payload: Record<string, unknown> = {
          player_id: playerId,
          template_id: template.id,
          recorded_at: new Date().toISOString(),
          raw_data: raw,
        };
        if (eventId) payload.event_id = eventId;
        if (episodeId) payload.episode_id = episodeId;
        const result = await api<ExamResult>("/results", {
          method: "POST",
          body: JSON.stringify(payload),
        });

        // Phase 2 — upload queued files and link to the new result.
        const failures = await uploadQueuedFiles(result.id);
        if (failures.length > 0) {
          // Result was saved; some files failed. Tell the user and let them
          // retry from the AttachmentList on the now-existing result.
          setWarning(
            `Se guardó el registro pero ${failures.length} archivo${
              failures.length === 1 ? "" : "s"
            } no se subió: ${failures.join("; ")}. ` +
              `Podés reintentarlo desde la pestaña.`,
          );
          // Brief pause so the user can read the warning before the parent navigates away.
          await new Promise((r) => setTimeout(r, 1500));
        }
        onSaved?.(result);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al guardar el examen");
    } finally {
      setSubmitting(false);
      setUploadProgress(null);
    }
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.header}>
        <h3 className={styles.title}>{template.name}</h3>
        <span className={styles.version}>v{template.version}</span>
      </div>

      {allowEventLink && (
        <fieldset className={styles.group}>
          <legend className={styles.legend}>Asociar partido</legend>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span className={styles.label}>
                Partido
                {selectedMatch && (
                  <span className={styles.matchHint}>
                    · fecha: {selectedMatch.starts_at.slice(0, 10)}
                  </span>
                )}
              </span>
              <select
                value={eventId}
                onChange={(e) => setEventId(e.target.value)}
              >
                <option value="">— Sin partido —</option>
                {matches.map((m) => {
                  const score = (m.metadata as { score?: { home?: number; away?: number } })?.score;
                  const scoreLabel =
                    score && (score.home != null || score.away != null)
                      ? ` (${score.home ?? "-"}-${score.away ?? "-"})`
                      : "";
                  return (
                    <option key={m.id} value={m.id}>
                      {m.starts_at.slice(0, 10)} · {m.title}
                      {scoreLabel}
                    </option>
                  );
                })}
              </select>
            </label>
          </div>
        </fieldset>
      )}

      {grouped.map(({ group, items }) => (
        <fieldset className={styles.group} key={group ?? "_default"}>
          {group && <legend className={styles.legend}>{group}</legend>}
          <div className={styles.grid}>
            {items.map((f) =>
              f.type === "file" ? (
                <div key={f.key} className={`${styles.field} ${styles.fullWidth}`}>
                  <span className={styles.label}>
                    {f.label}
                    {f.required ? " *" : ""}
                  </span>
                  {isEditing && existingResult ? (
                    // The result already exists — files can upload immediately
                    // via the live AttachmentList. Add/remove are autonomous.
                    <AttachmentList
                      sourceType="exam_field"
                      sourceId={existingResult.id}
                      fieldKey={f.key}
                      hint={f.placeholder ?? f.label}
                    />
                  ) : (
                    <DeferredFilePicker
                      value={queuedFiles[f.key] ?? []}
                      onChange={(files) => setQueuedForField(f.key, files)}
                      hint={f.placeholder ?? f.label}
                      disabled={submitting}
                    />
                  )}
                </div>
              ) : (
                <FieldInput
                  key={f.key}
                  field={f}
                  value={values[f.key]}
                  onChange={(v) => setValue(f.key, v)}
                />
              ),
            )}
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
      {warning && <div className={styles.warning}>{warning}</div>}

      <div className={styles.actions}>
        {onCancel && (
          <button type="button" className={styles.cancelBtn} onClick={onCancel} disabled={submitting}>
            Cancelar
          </button>
        )}
        <button type="submit" className={styles.submitBtn} disabled={submitting}>
          {submitting
            ? uploadProgress
              ? `Subiendo ${uploadProgress.uploaded}/${uploadProgress.total} archivos…`
              : "Guardando…"
            : isEditing
              ? "Guardar cambios"
              : "Guardar informe"}
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
    if (field.option_groups && Object.keys(field.option_groups).length > 0) {
      return (
        <GroupedCategoricalField
          id={id}
          label={label}
          field={field}
          value={typeof value === "string" ? value : ""}
          onChange={onChange}
        />
      );
    }
    const labels = field.option_labels ?? {};
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
              {labels[o] ?? o}
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

const UNGROUPED_KEY = "__ungrouped__";

interface GroupedCategoricalFieldProps {
  id: string;
  label: string;
  field: ExamField;
  value: string;
  onChange: (value: string) => void;
}

/**
 * Two-step picker for categorical fields with `option_groups` set:
 * "Tipo" select narrows the second select's options. The leaf value
 * (a string from `field.options`) is what goes into result_data — the
 * group is purely UI state, derived from `option_groups[value]` on
 * mount (so editing an existing result pre-fills correctly).
 */
function GroupedCategoricalField({
  id,
  label,
  field,
  value,
  onChange,
}: GroupedCategoricalFieldProps) {
  // Memoize derived shapes so dep arrays on the rest of the hooks don't
  // see new identities every render (the `?? {}` fallbacks would otherwise
  // produce fresh objects each call).
  const allOptions = useMemo(() => field.options ?? [], [field.options]);
  const optionGroups = useMemo(
    () => field.option_groups ?? {},
    [field.option_groups],
  );
  const optionLabels = field.option_labels ?? {};

  // Build the ordered group list from the order options appear in `options`,
  // de-duplicated. Options without a group entry land in a synthetic
  // "Sin categoría" bucket (key UNGROUPED_KEY, label shown in the select).
  const groups = useMemo(() => {
    const seen = new Map<string, string>();
    let hasUngrouped = false;
    for (const opt of allOptions) {
      const groupLabel = optionGroups[opt];
      if (groupLabel) {
        if (!seen.has(groupLabel)) seen.set(groupLabel, groupLabel);
      } else {
        hasUngrouped = true;
      }
    }
    const list = Array.from(seen.entries()).map(([key, value]) => ({
      key,
      label: value,
    }));
    if (hasUngrouped) list.push({ key: UNGROUPED_KEY, label: "Sin categoría" });
    return list;
  }, [allOptions, optionGroups]);

  // Local state for the "selected group". Tracks the user's pick; the
  // effective group falls back to the saved value's group when present so
  // we don't fight stale local state across edit/continue flows.
  const [pickedGroup, setPickedGroup] = useState<string | null>(null);
  const effectiveGroup = useMemo(() => {
    if (pickedGroup && groups.some((g) => g.key === pickedGroup)) {
      return pickedGroup;
    }
    if (value) {
      return optionGroups[value] || UNGROUPED_KEY;
    }
    return groups[0]?.key ?? "";
  }, [pickedGroup, groups, value, optionGroups]);

  const filteredOptions = useMemo(() => {
    return allOptions.filter((opt) => {
      const g = optionGroups[opt];
      if (effectiveGroup === UNGROUPED_KEY) return !g;
      return g === effectiveGroup;
    });
  }, [allOptions, optionGroups, effectiveGroup]);

  const handleGroupChange = (next: string) => {
    setPickedGroup(next);
    // Reset the leaf value if it no longer belongs to the chosen group.
    if (value) {
      const valueGroup = optionGroups[value] || UNGROUPED_KEY;
      if (valueGroup !== next) onChange("");
    }
  };

  return (
    <div className={styles.field}>
      <span className={styles.label}>{label}</span>
      <div className={styles.groupedFieldRow}>
        <select
          aria-label={`${label} — tipo`}
          value={effectiveGroup}
          onChange={(e) => handleGroupChange(e.target.value)}
        >
          {groups.map((g) => (
            <option key={g.key} value={g.key}>{g.label}</option>
          ))}
        </select>
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        >
          <option value="">—</option>
          {filteredOptions.map((o) => (
            <option key={o} value={o}>
              {optionLabels[o] ?? o}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
