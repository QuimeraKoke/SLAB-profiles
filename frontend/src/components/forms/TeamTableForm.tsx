"use client";

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type {
  ExamField,
  ExamResult,
  ExamTemplate,
  PlayerSummary,
  TeamResultsIn,
  TeamResultsOut,
} from "@/lib/types";
import styles from "./TeamTableForm.module.css";

interface TeamTableFormProps {
  template: ExamTemplate;
  categoryId: string;
  /** When set, every saved row links to this event (recorded_at is derived
   *  from the event's starts_at server-side). Used by the matches editor's
   *  bulk match-performance entry. */
  eventId?: string | null;
  /** When set, narrows the visible roster to these players only (e.g. the
   *  match's participants). Defaults to the full category roster. */
  participantIds?: string[];
  onCommitted?: (out: TeamResultsOut) => void;
  onCancel?: () => void;
}

type CellValue = string | number | boolean | null;

function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function defaultValueFor(field: ExamField): CellValue {
  if (field.type === "boolean") return false;
  if (field.type === "date") return todayISO();
  return "";
}

function isBlank(value: CellValue, fieldType: ExamField["type"]): boolean {
  if (value === null || value === undefined) return true;
  if (fieldType === "boolean") return value === false;
  return value === "";
}

export default function TeamTableForm({
  template,
  categoryId,
  eventId = null,
  participantIds,
  onCommitted,
  onCancel,
}: TeamTableFormProps) {
  const fields = useMemo(
    () => template.config_schema?.fields ?? [],
    [template.config_schema],
  );
  const teamCfg = template.input_config?.team_table ?? {};

  // Resolve shared vs row fields, defaulting row_fields to "everything not
  // shared and not calculated" (in declared order).
  const sharedKeys = useMemo(
    () => new Set(teamCfg.shared_fields ?? []),
    [teamCfg.shared_fields],
  );
  const sharedFields = useMemo(
    () => fields.filter((f) => sharedKeys.has(f.key) && f.type !== "calculated"),
    [fields, sharedKeys],
  );
  const rowFields = useMemo(() => {
    if (teamCfg.row_fields && teamCfg.row_fields.length > 0) {
      const set = new Set(teamCfg.row_fields);
      return fields.filter((f) => set.has(f.key) && f.type !== "calculated");
    }
    return fields.filter((f) => !sharedKeys.has(f.key) && f.type !== "calculated");
  }, [fields, sharedKeys, teamCfg.row_fields]);

  const [players, setPlayers] = useState<PlayerSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [sharedValues, setSharedValues] = useState<Record<string, CellValue>>(
    () => Object.fromEntries(sharedFields.map((f) => [f.key, defaultValueFor(f)])),
  );
  const [cells, setCells] = useState<Record<string, Record<string, CellValue>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Two parallel fetches: the roster (always needed) and the
    // existing-results-for-this-(template,event) (only when an event
    // is bound — that's the only context where prefill makes sense).
    const rosterPromise = api<PlayerSummary[]>(`/players?category_id=${categoryId}`);
    const resultsPromise: Promise<ExamResult[]> = eventId
      ? api<ExamResult[]>(
          `/results?template_id=${template.id}&event_id=${eventId}`,
        ).catch(() => [])  // missing/empty is non-fatal; we just start blank.
      : Promise.resolve([]);

    Promise.all([rosterPromise, resultsPromise])
      .then(([data, existing]) => {
        if (cancelled) return;
        const includeInactive = teamCfg.include_inactive === true;
        // Optionally narrow to a participant subset (e.g. only players who
        // were on the match's roster when bulk-entering performance).
        const allowedIds = participantIds && participantIds.length > 0
          ? new Set(participantIds)
          : null;
        const roster = data
          .filter((p) => includeInactive || p.is_active)
          .filter((p) => !allowedIds || allowedIds.has(p.id))
          .sort((a, b) =>
            (a.last_name + a.first_name).localeCompare(b.last_name + b.first_name),
          );
        setPlayers(roster);

        // Build a player_id → existing result_data map. Most-recent
        // wins when a player has multiple (shouldn't happen for an
        // upsert-keyed template + event, but defensive).
        const dataByPlayer = new Map<string, Record<string, unknown>>();
        for (const er of existing) {
          dataByPlayer.set(er.player_id, er.result_data ?? {});
        }

        // Initialize cells. Pre-fill from existing result_data when
        // available; fall back to defaults. Boolean / date fields get
        // their defaults applied even when there's a partial result —
        // we never want a saved blank to come back as an "edited" today.
        setCells(
          Object.fromEntries(
            roster.map((p) => {
              const existingData = dataByPlayer.get(p.id);
              const row: Record<string, CellValue> = {};
              for (const f of rowFields) {
                const raw = existingData?.[f.key];
                if (raw !== undefined && raw !== null) {
                  if (f.type === "number") {
                    row[f.key] = typeof raw === "number" ? raw : Number(raw);
                  } else if (f.type === "boolean") {
                    row[f.key] = Boolean(raw);
                  } else {
                    row[f.key] = String(raw);
                  }
                } else {
                  row[f.key] = defaultValueFor(f);
                }
              }
              return [p.id, row];
            }),
          ),
        );

        // Hydrate shared values too — every existing row should carry
        // the same shared values (e.g. fecha), so we pick the first
        // non-empty value across all results.
        if (sharedFields.length > 0 && existing.length > 0) {
          setSharedValues((prev) => {
            const next = { ...prev };
            for (const f of sharedFields) {
              for (const er of existing) {
                const v = (er.result_data ?? {})[f.key];
                if (v !== undefined && v !== null && v !== "") {
                  next[f.key] = (
                    f.type === "number"
                      ? Number(v)
                      : f.type === "boolean"
                        ? Boolean(v)
                        : String(v)
                  ) as CellValue;
                  break;
                }
              }
            }
            return next;
          });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.message : "No se pudo cargar el plantel");
      });
    return () => {
      cancelled = true;
    };
    // rowFields is derived from `template`; it's stable across this lifecycle.
    // participantIds reference identity is unstable from the parent — we
    // de-duplicate by stringifying so prop array re-renders don't refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryId, teamCfg.include_inactive, eventId, template.id, (participantIds ?? []).join(",")]);

  const setSharedValue = (key: string, value: CellValue) => {
    setSharedValues((prev) => ({ ...prev, [key]: value }));
  };

  const setCellValue = (playerId: string, fieldKey: string, value: CellValue) => {
    setCells((prev) => ({
      ...prev,
      [playerId]: { ...(prev[playerId] ?? {}), [fieldKey]: value },
    }));
  };

  // Per-player "is this row blank?" helper. Used to dim empty rows and to
  // show a live count of how many will actually be saved.
  const isRowBlank = (playerId: string): boolean => {
    const row = cells[playerId] ?? {};
    return rowFields.every((f) => isBlank(row[f.key] ?? null, f.type));
  };

  const filledCount = useMemo(
    () => (players ?? []).filter((p) => !isRowBlank(p.id)).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cells, players],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!players) return;

    // Validate shared fields.
    const sharedData: Record<string, unknown> = {};
    for (const f of sharedFields) {
      const v = sharedValues[f.key];
      if (isBlank(v, f.type)) {
        if (f.required) {
          setError(`Falta el campo compartido "${f.label}"`);
          return;
        }
        continue;
      }
      sharedData[f.key] = f.type === "number" ? Number(v) : v;
    }

    // Build rows, skipping blanks but validating non-blank rows.
    const rows: { player_id: string; result_data: Record<string, unknown> }[] = [];
    for (const player of players) {
      if (isRowBlank(player.id)) continue;
      const row: Record<string, unknown> = {};
      for (const f of rowFields) {
        const v = cells[player.id]?.[f.key];
        if (isBlank(v ?? null, f.type)) {
          if (f.required) {
            setError(
              `Falta "${f.label}" para ${player.first_name} ${player.last_name}`,
            );
            return;
          }
          continue;
        }
        if (f.type === "number") {
          const n = Number(v);
          if (Number.isNaN(n)) {
            setError(`"${f.label}" debe ser un número (${player.last_name})`);
            return;
          }
          if (typeof f.min === "number" && n < f.min) {
            setError(
              `"${f.label}" debe ser ≥ ${f.min} (${player.last_name})`,
            );
            return;
          }
          if (typeof f.max === "number" && n > f.max) {
            setError(
              `"${f.label}" debe ser ≤ ${f.max} (${player.last_name})`,
            );
            return;
          }
          row[f.key] = n;
        } else {
          row[f.key] = v;
        }
      }
      rows.push({ player_id: player.id, result_data: row });
    }

    if (rows.length === 0) {
      setError("Ingresa al menos un valor antes de guardar.");
      return;
    }

    const payload: TeamResultsIn = {
      template_id: template.id,
      category_id: categoryId,
      recorded_at: new Date().toISOString(),
      shared_data: sharedData,
      rows,
      // When linking to an event, the backend overrides recorded_at with
      // the event's starts_at — recorded_at above is just a fallback.
      ...(eventId ? { event_id: eventId } : {}),
    };

    setSubmitting(true);
    try {
      const out = await api<TeamResultsOut>("/results/team", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onCommitted?.(out);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al guardar el lote");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <div className={styles.form}>
        <div className={styles.error} role="alert">
          {loadError}
        </div>
      </div>
    );
  }

  if (!players) {
    return (
      <div className={styles.form}>
        <div className={styles.empty}>Cargando plantel…</div>
      </div>
    );
  }

  if (rowFields.length === 0) {
    return (
      <div className={styles.form}>
        <div className={styles.empty}>
          Esta plantilla no tiene campos para captura por jugador. Configura
          <code> input_config.team_table.row_fields </code>
          o agrega campos no calculados.
        </div>
      </div>
    );
  }

  const hasCalculated = fields.some((f) => f.type === "calculated");

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <header className={styles.header}>
        <h3 className={styles.title}>{template.name}</h3>
        <span className={styles.version}>v{template.version}</span>
      </header>

      {sharedFields.length > 0 && (
        <fieldset className={styles.sharedSection}>
          <legend className={styles.legend}>Datos compartidos</legend>
          <div className={styles.sharedGrid}>
            {sharedFields.map((f) => (
              <SharedFieldInput
                key={f.key}
                field={f}
                value={sharedValues[f.key]}
                onChange={(v) => setSharedValue(f.key, v)}
              />
            ))}
          </div>
        </fieldset>
      )}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Jugador</th>
              {rowFields.map((f) => (
                <th key={f.key}>
                  {f.label}
                  {f.unit && <span className={styles.unit}>{f.unit}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {players.map((p) => {
              const blank = isRowBlank(p.id);
              return (
                <tr key={p.id} className={blank ? styles.empty : ""}>
                  <td className={styles.playerCell}>
                    {p.last_name}, {p.first_name}
                  </td>
                  {rowFields.map((f) => (
                    <td key={f.key}>
                      <CellInput
                        field={f}
                        value={cells[p.id]?.[f.key] ?? defaultValueFor(f)}
                        onChange={(v) => setCellValue(p.id, f.key, v)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {hasCalculated && (
        <p className={styles.calculatedHint}>
          Los campos calculados se computarán al guardar.
        </p>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        <span className={styles.summary}>
          {filledCount} de {players.length} jugador{players.length === 1 ? "" : "es"} con datos.
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          {onCancel && (
            <button
              type="button"
              className={styles.cancelBtn}
              onClick={onCancel}
              disabled={submitting}
            >
              Cancelar
            </button>
          )}
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || filledCount === 0}
          >
            {submitting ? "Guardando…" : `Guardar ${filledCount} registro${filledCount === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </form>
  );
}

interface SharedFieldInputProps {
  field: ExamField;
  value: CellValue;
  onChange: (v: CellValue) => void;
}

function SharedFieldInput({ field, value, onChange }: SharedFieldInputProps) {
  const id = `shared-${field.key}`;
  const labelText = field.unit ? `${field.label} [${field.unit}]` : field.label;

  if (field.type === "categorical") {
    const labels = field.option_labels ?? {};
    return (
      <label htmlFor={id} className={styles.field}>
        <span className={styles.label}>{labelText}</span>
        <select
          id={id}
          value={value === null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        >
          <option value="">— Seleccionar —</option>
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {labels[opt] ?? opt}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (field.type === "boolean") {
    return (
      <label htmlFor={id} className={styles.field}>
        <span className={styles.label}>{labelText}</span>
        <input
          id={id}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
      </label>
    );
  }

  const inputType =
    field.type === "date" ? "date" : field.type === "number" ? "number" : "text";

  return (
    <label htmlFor={id} className={styles.field}>
      <span className={styles.label}>{labelText}</span>
      <input
        id={id}
        type={inputType}
        min={field.type === "number" ? field.min : undefined}
        max={field.type === "number" ? field.max : undefined}
        step={field.type === "number" ? "any" : undefined}
        value={value === null ? "" : String(value)}
        placeholder={field.placeholder ?? ""}
        onChange={(e) =>
          onChange(field.type === "number" ? e.target.value : e.target.value)
        }
        required={field.required}
      />
    </label>
  );
}

interface CellInputProps {
  field: ExamField;
  value: CellValue;
  onChange: (v: CellValue) => void;
}

function CellInput({ field, value, onChange }: CellInputProps) {
  if (field.type === "categorical") {
    const labels = field.option_labels ?? {};
    return (
      <select
        className={styles.cellInput}
        value={value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value=""></option>
        {(field.options ?? []).map((opt) => (
          <option key={opt} value={opt}>
            {labels[opt] ?? opt}
          </option>
        ))}
      </select>
    );
  }

  if (field.type === "boolean") {
    return (
      <input
        className={styles.cellInput}
        type="checkbox"
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }

  const inputType =
    field.type === "date" ? "date" : field.type === "number" ? "number" : "text";

  return (
    <input
      className={styles.cellInput}
      type={inputType}
      min={field.type === "number" ? field.min : undefined}
      max={field.type === "number" ? field.max : undefined}
      step={field.type === "number" ? "any" : undefined}
      value={value === null ? "" : String(value)}
      placeholder={field.placeholder ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
