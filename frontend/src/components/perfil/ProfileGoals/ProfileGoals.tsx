"use client";

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import type {
  ExamField,
  ExamTemplate,
  Goal,
  GoalCreateIn,
  GoalOperator,
  PlayerDetail,
} from "@/lib/types";
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
  const [error, setError] = useState<string | null>(null);
  // Creation flow: null (idle) → "choose" (pick type) → "metric" | "free" (form).
  const [flow, setFlow] = useState<null | "choose" | "metric" | "free">(null);
  const { confirm } = useConfirm();
  const canAdd = usePermission("goals.add_goal");
  const canChange = usePermission("goals.change_goal");

  const refresh = async () => {
    try {
      // Alerts moved to their own "Alertas" tab (ProfileAlerts) — this tab
      // is goals only.
      const g = await api<Goal[]>(`/players/${player.id}/goals`);
      setGoals(g);
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
    setFlow(null);
  };

  const handleCancel = async (goal: Goal) => {
    const ok = await confirm({
      title: "Cancelar objetivo",
      message: "¿Cancelar este objetivo? Quedará marcado como cancelado en el historial.",
      confirmLabel: "Sí, cancelar",
    });
    if (!ok) return;
    await handleSetStatus(goal, "cancelled");
  };

  // §7.3 — manual close of a FREE goal (or cancel of any). Metric goals
  // only accept "cancelled"; the backend rejects a bad transition.
  const handleSetStatus = async (goal: Goal, status: "met" | "missed" | "cancelled") => {
    try {
      const updated = await api<Goal>(`/goals/${goal.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setGoals((prev) => (prev ?? []).map((g) => (g.id === goal.id ? updated : g)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo actualizar el objetivo");
    }
  };

  if (goals === null) {
    return <div className={styles.container}>Cargando objetivos…</div>;
  }

  return (
    <div className={styles.container}>
      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.toolbar}>
        <h3 className={styles.title}>Objetivos · {goals.length}</h3>
        {flow === null && canAdd && (
          <button
            type="button"
            className={styles.newBtn}
            onClick={() => setFlow("choose")}
          >
            + Crear objetivo
          </button>
        )}
      </div>

      {flow === "choose" && canAdd && (
        <GoalTypeChooser onPick={(m) => setFlow(m)} onCancel={() => setFlow(null)} />
      )}

      {(flow === "metric" || flow === "free") && canAdd && (
        <GoalForm
          player={player}
          mode={flow}
          onCreated={handleCreated}
          onCancel={() => setFlow(null)}
        />
      )}

      {goals.length === 0 ? (
        <div className={styles.empty}>
          Aún no hay objetivos para este jugador.
        </div>
      ) : (
        <div className={styles.list}>
          {goals.map((g) => (
            <GoalCard
              key={g.id}
              goal={g}
              onCancel={handleCancel}
              onSetStatus={handleSetStatus}
              canChange={canChange}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Goal card
// ---------------------------------------------------------------------------

function GoalCard({
  goal, onCancel, onSetStatus, canChange,
}: {
  goal: Goal;
  onCancel: (g: Goal) => void;
  onSetStatus: (g: Goal, status: "met" | "missed" | "cancelled") => void;
  canChange: boolean;
}) {
  const op = goal.operator ? OPERATOR_LABELS[goal.operator] : "";
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

  const unitSuffix = goal.field_unit ? ` ${goal.field_unit}` : "";
  const targetStr = `${goal.target_value}${unitSuffix}`;
  // Prefer the live `current_value` over the evaluator-cached `last_value`
  // — the latter can lag behind reality between scheduled runs.
  const currentValue = goal.current_value;
  const currentStr =
    currentValue !== null ? `${currentValue}${unitSuffix}` : "Sin datos";

  // Color the current value green/red based on the server-computed
  // `progress.achieved`. Falls back to neutral when no reading exists.
  const currentValueClass =
    goal.progress?.achieved === true
      ? styles.good
      : goal.progress?.achieved === false
        ? styles.bad
        : "";

  const distance = goal.progress?.distance;
  const distancePct = goal.progress?.distance_pct;

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div>
          <div className={styles.cardTitle}>
            {goal.is_metric_goal ? `${goal.field_label} ${op} ${targetStr}` : goal.title}
          </div>
          <div className={styles.cardSubtitle}>
            {goal.is_metric_goal ? goal.template_name : "Objetivo libre"}
          </div>
        </div>
        <span className={`${styles.statusPill} ${statusClass}`}>{statusLabel}</span>
      </div>
      <div className={styles.row}>
        <span className={styles.rowLabel}>Fecha objetivo</span>
        <span className={styles.rowValue}>{formatDate(goal.due_date)}</span>
      </div>
      {goal.is_metric_goal && (
        <div className={styles.row}>
          <span className={styles.rowLabel}>Valor actual</span>
          <span className={`${styles.rowValue} ${currentValueClass}`}>
            {currentStr}
            {currentValue !== null && distance !== null && distance !== 0 && (
              <span className={styles.deltaInline}>
                {" "}({distance > 0 ? "+" : ""}{distance}
                {distancePct !== null ? `, ${distancePct > 0 ? "+" : ""}${distancePct.toFixed(1)}%` : ""}
                {" "}vs objetivo)
              </span>
            )}
          </span>
        </div>
      )}
      {goal.is_metric_goal && goal.current_recorded_at && (
        <div className={styles.row}>
          <span className={styles.rowLabel}>Medido el</span>
          <span className={styles.rowValueMuted}>
            {formatDate(goal.current_recorded_at)}
          </span>
        </div>
      )}
      {goal.notes && <div className={styles.notes}>{goal.notes}</div>}
      {goal.status === "active" && canChange && (
        <div className={styles.cardActions}>
          {!goal.is_metric_goal && (
            <>
              <button type="button" className={styles.linkBtnGood} onClick={() => onSetStatus(goal, "met")}>
                Marcar cumplido
              </button>
              <button type="button" className={styles.linkBtnBad} onClick={() => onSetStatus(goal, "missed")}>
                Marcar no cumplido
              </button>
            </>
          )}
          <button type="button" className={styles.linkBtn} onClick={() => onCancel(goal)}>
            Cancelar
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — choose the goal type (§7.3)
// ---------------------------------------------------------------------------

function GoalTypeChooser({
  onPick, onCancel,
}: {
  onPick: (mode: "metric" | "free") => void;
  onCancel: () => void;
}) {
  return (
    <div className={styles.chooser}>
      <div className={styles.chooserPrompt}>¿El objetivo se mide con una métrica?</div>
      <div className={styles.chooserOptions}>
        <button type="button" className={styles.chooserOption} onClick={() => onPick("metric")}>
          <span className={styles.chooserTitle}>Con una métrica</span>
          <span className={styles.chooserDesc}>
            Se evalúa contra una medición (p. ej. Peso ≤ 78 kg) y se marca
            cumplido / no cumplido automáticamente.
          </span>
        </button>
        <button type="button" className={styles.chooserOption} onClick={() => onPick("free")}>
          <span className={styles.chooserTitle}>Objetivo libre</span>
          <span className={styles.chooserDesc}>
            Solo un texto y una fecha (p. ej. “Completar el reintegro”). Lo
            cerrás vos manualmente.
          </span>
        </button>
      </div>
      <div className={styles.chooserFooter}>
        <button type="button" className={styles.cancelBtn} onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — goal-creation form
// ---------------------------------------------------------------------------

interface FormProps {
  player: PlayerDetail;
  /** §7.3 — fixed by the chooser step; the form no longer toggles it. */
  mode: "metric" | "free";
  onCreated: (goal: Goal) => void;
  onCancel: () => void;
}

function GoalForm({ player, mode, onCreated, onCancel }: FormProps) {
  const [title, setTitle] = useState("");
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

    let payload: GoalCreateIn;
    if (mode === "free") {
      if (!title.trim()) {
        setError("Ingresá un título para el objetivo.");
        return;
      }
      payload = {
        player_id: player.id,
        title: title.trim(),
        due_date: dueDate,
        notes: notes || undefined,
      };
    } else {
      if (!templateId || !fieldKey || !targetValue) {
        setError("Completa plantilla, campo y valor objetivo.");
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
      payload = {
        player_id: player.id,
        template_id: templateId,
        field_key: fieldKey,
        operator,
        target_value: target,
        due_date: dueDate,
        notes: notes || undefined,
        warn_days_before: warnDays,
      };
    }
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
      <div className={styles.formHeading}>
        {mode === "free" ? "Nuevo objetivo libre" : "Nuevo objetivo con métrica"}
      </div>
      <div className={styles.formGrid}>
        {mode === "free" && (
          <label className={`${styles.field} ${styles.fullWidth}`}>
            <span className={styles.label}>Título del objetivo</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="p. ej. Completar el reintegro deportivo"
              required
            />
          </label>
        )}
        {mode === "metric" && (
        <>
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
        </>
        )}

        <label className={styles.field}>
          <span className={styles.label}>Fecha objetivo</span>
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            required
          />
        </label>

        {mode === "metric" && (
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
        )}

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
