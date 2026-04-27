"use client";

import React, { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Department, ExamResult, ExamTemplate } from "@/lib/types";
import DepartmentCard from "@/components/perfil/DepartmentCard/DepartmentCard";
import styles from "./ProfileDepartment.module.css";

interface ProfileDepartmentProps {
  playerId: string;
  department: Department;
}

export default function ProfileDepartment({ playerId, department }: ProfileDepartmentProps) {
  const [results, setResults] = useState<ExamResult[] | null>(null);
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setResults(null);
    setTemplates([]);
    setError(null);

    Promise.all([
      api<ExamResult[]>(
        `/players/${playerId}/results?department=${encodeURIComponent(department.slug)}`,
      ),
      api<ExamTemplate[]>(
        `/players/${playerId}/templates?department=${encodeURIComponent(department.slug)}`,
      ),
    ])
      .then(([resultsData, templatesData]) => {
        if (cancelled) return;
        setResults(resultsData);
        setTemplates(templatesData);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load department data");
        setResults([]);
      });

    return () => {
      cancelled = true;
    };
  }, [playerId, department.slug]);

  const handleResultSaved = (result: ExamResult) => {
    setResults((prev) => (prev ? [result, ...prev] : [result]));
  };

  return (
    <section className={styles.container}>
      <header className={styles.header}>
        <h2 className={styles.title}>{department.name}</h2>
        {results !== null && (
          <span className={styles.subtitle}>
            {templates.length} {templates.length === 1 ? "plantilla" : "plantillas"}
          </span>
        )}
      </header>

      {error && <div className={styles.error}>{error}</div>}

      {results === null && !error && (
        <div className={styles.loading}>Cargando…</div>
      )}

      {results !== null && templates.length === 0 && !error && (
        <div className={styles.empty}>
          No hay plantillas para <code>{department.slug}</code> aplicables a esta categoría.
          Crea una en el panel de administración para empezar.
        </div>
      )}

      {results !== null && templates.length > 0 && (
        <div className={styles.grid}>
          {templates.map((t) => (
            <DepartmentCard
              key={t.id}
              template={t}
              results={results.filter((r) => r.template_id === t.id)}
              playerId={playerId}
              onResultSaved={handleResultSaved}
            />
          ))}
        </div>
      )}
    </section>
  );
}
