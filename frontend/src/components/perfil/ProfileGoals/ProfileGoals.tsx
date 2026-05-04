"use client";

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type {
  Alert as AlertModel,
  ExamField,
  ExamTemplate,
  Goal,
  GoalCreateIn,
  GoalOperator,
  PlayerDetail,
} from "@/lib/types";
import AlertList from "./AlertList";
import styles from "./ProfileGoals.module.css";

interface Props {
  player: PlayerDetail;
}

const OPERATOR_LABELS: Record<GoalOperator, string> = {
  "<=": "≤",
  "<": "<",
  "==": "=",
  ">=": "≥",
  ">": ">",
};

function formatDate(iso: string): string {
  return new Date(iso + (iso.includes("T") ? "" : "T00:00:00")).toLocaleDateString(
    undefined,
    { day: "2-digit", month: "short", year: "numeric" },
  );
}

export default function ProfileGoals({ player }: Props) {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [alerts, setAlerts] = useState<AlertModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const refresh = async () => {
    try {
      const [g, a] = await Promise.all([
        api<Goal[]>(`/players/${player.id}/goals`),
        api<AlertModel[]>(`/players/${player.id}/alerts?status=active`),
      ]);
      setGoals(g);
      setAlerts(a);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudieron cargar los objetivos");
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.id]);

  const handleCreated = (goal: Goal) => {
    setGoals((prev) => (prev ? [goal, ...prev] : [goal]));
    setShowForm(false);
  };

  const handleCancel = async (goal: Goal) => {
    if (!confirm("¿Cancelar este objetivo?")) return;
    try {
      const updated = await api<Goal>(`/goals/${goal.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "cancelled" }),
      });
      setGoals((prev) => (prev ?? []).map((g) => (g.id === goal.id ? updated : g)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al cancelar");
    }
  };

  const handleAlertDismiss = async (alert: AlertModel) => {
    try {
      await api(`/alerts/${alert.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "dismissed" }),
      });
      setAlerts((prev) => prev.filter((a) => a.id !== alert.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al descartar alerta");
    }
  };

  if (goals === null) {
    return <div className={styles.container}>Cargando objetivos…</div>;
  }

  return (
    <div className={styles.container}>
      {alerts.length > 0 && (
        <AlertList alerts={alerts} onDismiss={handleAlertDismiss} />
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.toolbar}>
        <h3 className={styles.title}>Objetivos · {goals.length}</h3>
        {!showForm && (
          <button
            type="button"
            className={styles.newBtn}
            onClick={() => setShowForm(true)}
          >
            + Crear objetivo
          </button>
        )}
      </div>

      {showForm && (
        <GoalForm
          player={player}
          onCreated={handleCreated}
          onCancel={() => setShowForm(false)}
        />
      )}

      {goals.length === 0 ? (
        <div className={styles.empty}>
          Aún no hay objetivos para este jugador.
        </div>
      ) : (
        <div className={styles.list}>
          {goals.map((g) => (
            <GoalCard key={g.id} goal={g} onCancel={handleCancel} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Goal card
// ---------------------------------------------------------------------------

function GoalCard({ goal, onCancel }: { goal: Goal; onCancel: (g: Goal) => void }) {
  const op = OPERATOR_LABELS[goal.operator];
  const statusClass =
    goal.status === "met"
      ? styles.statusMet
      : goal.status === "missed"
        ? styles.statusMissed
        : goal.status === "cancelled"
          ? styles.statusCancelled
          : styles.statusActive;
  const statusLabel =
    goal.status === "met"
      ? "Cumplido"
      : goal.status === "missed"
        ? "No cumplido"
        : goal.status === "cancelled"
          ? "Cancelado"
          : "Activo";

  const targetStr = `${goal.target_value}${goal.field_unit ? ` ${goal.field_unit}` : ""}`;
  const lastStr =
    goal.last_value !== null
      ? `${goal.last_value}${goal.field_unit ? ` ${goal.field_unit}` : ""}`
      : "Sin datos";

  // Color the "last value" red/green when we have one.
  let lastValueClass = "";
  if (goal.last_value !== null) {
    const ok = compare(goal.last_value, goal.operator, goal.target_value);
    lastValueClass = ok ? styles.good : styles.bad;
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div>
          <div className={styles.cardTitle}>
            {goal.field_label} {op} {targetStr}
          </div>
          <div className={styles.cardSubtitle}>{goal.template_name}</div>
        </div>
        <span className={`${styles.statusPill} ${statusClass}`}>{statusLabel}</span>
      </div>
      <div className={styles.row}>
        <span className={styles.rowLabel}>Fecha objetivo</span>
        <span className={styles.rowValue}>{formatDate(goal.due_date)}</span>
      </div>
      <div className={styles.row}>
        <span className={styles.rowLabel}>Valor actual</span>
        <span className={`${styles.rowValue} ${lastValueClass}`}>{lastStr}</span>
      </div>
      {goal.notes && <div className={styles.notes}>{goal.notes}</div>}
      {goal.status === "active" && (
        <div className={styles.cardActions}>
          <button type="button" className={styles.linkBtn} onClick={() => onCancel(goal)}>
            Cancelar
          </button>
        </div>
      )}
    </div>
  );
}

function compare(actual: number, op: GoalOperator, target: number): boolean {
  switch (op) {
    case "<=": return actual <= target;
    case "<":  return actual < target;
    case "==": return actual === target;
    case ">=": return actual >= target;
    case ">":  return actual > target;
  }
}

// ---------------------------------------------------------------------------
// Goal-creation form
// ---------------------------------------------------------------------------

interface FormProps {
  player: PlayerDetail;
  onCreated: (goal: Goal) => void;
  onCancel: () => void;
}

function GoalForm({ player, onCreated, onCancel }: FormProps) {
  const [templates, setTemplates] = useState<ExamTemplate[] | null>(null);
  const [templateId, setTemplateId] = useState<string>("");
  const [fieldKey, setFieldKey] = useState<string>("");
  const [operator, setOperator] = useState<GoalOperator>("<=");
  const [targetValue, setTargetValue] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return d.toISOString().slice(0, 10);
  });
  const [notes, setNotes] = useState("");
  const [warnDaysBefore, setWarnDaysBefore] = useState<string>("7");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<ExamTemplate[]>(`/players/${player.id}/templates`)
      .then((data) => {
        if (!cancelled) setTemplates(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "No se pudieron cargar las plantillas");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [player.id]);

  const selectedTemplate = useMemo(
    () => templates?.find((t) => t.id === templateId) ?? null,
    [templates, templateId],
  );

  // Only numeric/calculated fields can be a goal target.
  const numericFields = useMemo<ExamField[]>(() => {
    if (!selectedTemplate) return [];
    return (selectedTemplate.config_schema?.fields ?? []).filter(
      (f) => f.type === "number" || f.type === "calculated",
    );
  }, [selectedTemplate]);

  // Auto-pick first field when template changes.
  useEffect(() => {
    if (numericFields.length > 0 && !numericFields.some((f) => f.key === fieldKey)) {
      setFieldKey(numericFields[0].key);
    }
  }, [numericFields, fieldKey]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!templateId || !fieldKey || !targetValue) {
      setError("Completá plantilla, campo y valor objetivo.");
      return;
    }
    const target = Number(targetValue);
    if (Number.isNaN(target)) {
      setError("Valor objetivo inválido.");
      return;
    }
    // Empty input or 0 disables warnings; otherwise pass through as a number.
    let warnDays: number | null = null;
    if (warnDaysBefore.trim() !== "") {
      const parsed = Number(warnDaysBefore);
      if (Number.isNaN(parsed) || parsed < 0) {
        setError("Días de aviso inválidos.");
        return;
      }
      warnDays = parsed === 0 ? null : Math.floor(parsed);
    }

    const payload: GoalCreateIn = {
      player_id: player.id,
      template_id: templateId,
      field_key: fieldKey,
      operator,
      target_value: target,
      due_date: dueDate,
      notes: notes || undefined,
      warn_days_before: warnDays,
    };
    setSubmitting(true);
    try {
      const created = await api<Goal>("/goals", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al crear el objetivo");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={styles.formCard} onSubmit={handleSubmit}>
      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span className={styles.label}>Plantilla</span>
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            required
          >
            <option value="">— Seleccionar —</option>
            {(templates ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.department.name} · {t.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Campo</span>
          <select
            value={fieldKey}
            onChange={(e) => setFieldKey(e.target.value)}
            disabled={!selectedTemplate}
            required
          >
            {numericFields.length === 0 ? (
              <option value="">(sin campos numéricos)</option>
            ) : (
              numericFields.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                  {f.unit ? ` (${f.unit})` : ""}
                </option>
              ))
            )}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Operador</span>
          <select
            value={operator}
            onChange={(e) => setOperator(e.target.value as GoalOperator)}
          >
            <option value="<=">≤ menor o igual</option>
            <option value="<">&lt; menor que</option>
            <option value="==">= igual a</option>
            <option value=">=">≥ mayor o igual</option>
            <option value=">">&gt; mayor que</option>
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Valor objetivo</span>
          <input
            type="number"
            step="any"
            value={targetValue}
            onChange={(e) => setTargetValue(e.target.value)}
            required
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Fecha objetivo</span>
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            required
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>
            Avisar días antes
            <span className={styles.hint}> · 0 o vacío desactiva</span>
          </span>
          <input
            type="number"
            min="0"
            step="1"
            value={warnDaysBefore}
            onChange={(e) => setWarnDaysBefore(e.target.value)}
            placeholder="7"
          />
        </label>

        <label className={`${styles.field} ${styles.fullWidth}`}>
          <span className={styles.label}>Notas (opcional)</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Plan de acción, criterios, etc."
          />
        </label>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.formActions}>
        <button type="button" className={styles.cancelBtn} onClick={onCancel} disabled={submitting}>
          Cancelar
        </button>
        <button type="submit" className={styles.saveBtn} disabled={submitting}>
          {submitting ? "Guardando…" : "Crear objetivo"}
        </button>
      </div>
    </form>
  );
}
