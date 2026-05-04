"use client";

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { ExamField, ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./ProfileTimeline.module.css";

interface ProfileTimelineProps {
  playerId: string;
}

export default function ProfileTimeline({ playerId }: ProfileTimelineProps) {
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setResults(null);
      setTemplates([]);
      setError(null);
    });

    Promise.all([
      api<ExamResult[]>(`/players/${playerId}/results`),
      api<ExamTemplate[]>(`/players/${playerId}/templates`),
    ])
      .then(([r, t]) => {
        if (cancelled) return;
        setResults(r);
        setTemplates(t);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load timeline");
        setResults([]);
      });

    return () => {
      cancelled = true;
    };
  }, [playerId]);

  // Sort by the doctor-typed `fecha` when present (it's the clinically
  // meaningful date — when the measurement actually happened — even if
  // it differs from `recorded_at` which is the moment the form was saved).
  // Falls back to `recorded_at` when no fecha was filled in.
  const sorted = useMemo(() => {
    if (!results) return [];
    return [...results].sort(
      (a, b) => effectiveDate(b).getTime() - effectiveDate(a).getTime(),
    );
  }, [results]);

  const templateById = useMemo(
    () => new Map(templates.map((t) => [t.id, t])),
    [templates],
  );

  if (error) {
    return (
      <section className={styles.container}>
        <div className={styles.error}>{error}</div>
      </section>
    );
  }

  if (results === null) {
    return (
      <section className={styles.container}>
        <div className={styles.empty}>Cargando línea de tiempo…</div>
      </section>
    );
  }

  if (sorted.length === 0) {
    return (
      <section className={styles.container}>
        <div className={styles.empty}>
          Aún no hay registros para este jugador en los departamentos a los que tienes acceso.
        </div>
      </section>
    );
  }

  return (
    <section className={styles.container}>
      <header className={styles.header}>
        <h3 className={styles.title}>Línea de tiempo</h3>
        <span className={styles.count}>
          {sorted.length} {sorted.length === 1 ? "registro" : "registros"}
        </span>
      </header>

      <ol className={styles.timeline}>
        {sorted.map((result) => {
          const template = templateById.get(result.template_id);
          return (
            <TimelineItem key={result.id} result={result} template={template} />
          );
        })}
      </ol>
    </section>
  );
}

interface TimelineItemProps {
  result: ExamResult;
  template: ExamTemplate | undefined;
}

function TimelineItem({ result, template }: TimelineItemProps) {
  const fields = template?.config_schema?.fields ?? [];
  const summary = summarizeResult(result, fields);
  // Display the effective date (doctor-typed `fecha` when present) so the
  // timeline reads as a clinical record, not a save-event log.
  const recorded = effectiveDate(result);

  return (
    <li className={styles.item}>
      <div className={styles.dateColumn}>
        <span className={styles.dateRelative}>{relativeDate(recorded)}</span>
        <span className={styles.dateAbsolute}>
          {recorded.toLocaleDateString(undefined, {
            day: "2-digit",
            month: "short",
          })}
        </span>
      </div>

      <div className={styles.dot} aria-hidden="true" />

      <div className={styles.card}>
        <header className={styles.cardHeader}>
          {template?.department && (
            <span className={styles.departmentBadge}>{template.department.name}</span>
          )}
          <span className={styles.templateName}>
            {template?.name ?? "Examen sin plantilla"}
          </span>
        </header>

        {summary && <p className={styles.summary}>{summary}</p>}
      </div>
    </li>
  );
}

const MAX_SUMMARY_LEN = 110;

function summarizeResult(result: ExamResult, fields: ExamField[]): string | null {
  const data = result.result_data;

  // Subject + body excerpt for notes/goals templates.
  const subjectField = fields.find((f) => f.key === "asunto" || f.key === "objetivo");
  const subject =
    subjectField && data[subjectField.key] ? String(data[subjectField.key]) : null;

  const longTextField = fields.find(
    (f) => f.type === "text" && f.multiline && data[f.key] != null && data[f.key] !== "",
  );
  const body = longTextField ? String(data[longTextField.key]) : null;

  if (subject && body) {
    return truncate(`${subject} — ${body}`, MAX_SUMMARY_LEN);
  }
  if (subject) {
    // Pair the subject with status/plazo if available, for Metas-shape templates.
    const status = fields.find((f) => f.key === "estado" && data[f.key]);
    if (status) return truncate(`${subject} · ${data[status.key]}`, MAX_SUMMARY_LEN);
    return truncate(subject, MAX_SUMMARY_LEN);
  }
  if (body) {
    return truncate(body, MAX_SUMMARY_LEN);
  }

  // Measurement templates: top calculated values inline.
  const calculated = fields
    .filter((f) => f.type === "calculated" && data[f.key] != null)
    .slice(0, 2);
  if (calculated.length > 0) {
    return calculated
      .map((f) => `${f.label}: ${formatValue(data[f.key])}${f.unit ? ` ${f.unit}` : ""}`)
      .join(" · ");
  }

  return null;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + "…";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

// truncate is declared above with summarizeResult so it can be reused.

/**
 * The clinically meaningful date for a result: the doctor-typed `fecha`
 * field if present and parseable, otherwise the system's `recorded_at`
 * timestamp. Used by the timeline so back-dated entries (e.g. doctor
 * registers Monday's check-in on Tuesday morning) show on Monday.
 */
function effectiveDate(result: ExamResult): Date {
  const raw = result.result_data?.fecha;
  if (typeof raw === "string" && raw.length >= 10) {
    // ISO date or datetime; treat naked dates as midnight local.
    const parsed = new Date(raw.includes("T") ? raw : `${raw}T00:00:00`);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date(result.recorded_at);
}

function relativeDate(then: Date): string {
  const diffMs = Date.now() - then.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return "Hoy";
  if (diffDays === 1) return "Ayer";
  if (diffDays < 7) return `Hace ${diffDays} días`;
  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7);
    return `Hace ${weeks} ${weeks === 1 ? "semana" : "semanas"}`;
  }
  if (diffDays < 365) {
    const months = Math.floor(diffDays / 30);
    return `Hace ${months} ${months === 1 ? "mes" : "meses"}`;
  }
  const years = Math.floor(diffDays / 365);
  return `Hace ${years} ${years === 1 ? "año" : "años"}`;
}
