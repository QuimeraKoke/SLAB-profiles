"use client";

import React, { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import BulkIngestForm from "@/components/forms/BulkIngestForm";
import BulkIngestPlaceholder from "@/components/forms/BulkIngestPlaceholder";
import DynamicUploader from "@/components/forms/DynamicUploader";
import { api, ApiError } from "@/lib/api";
import type { ExamInputMode, ExamTemplate, PlayerDetail } from "@/lib/types";
import styles from "./page.module.css";

function resolveInputMode(template: ExamTemplate): ExamInputMode {
  const cfg = template.input_config;
  if (cfg?.default_input_mode && cfg.input_modes?.includes(cfg.default_input_mode)) {
    return cfg.default_input_mode;
  }
  return cfg?.input_modes?.[0] ?? "single";
}

interface PageProps {
  params: Promise<{ id: string; templateId: string }>;
}

export default function RegistrarExamPage({ params }: PageProps) {
  const { id, templateId } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabSlug = searchParams.get("tab");

  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [template, setTemplate] = useState<ExamTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPlayer(null);
    setTemplate(null);
    setError(null);

    Promise.all([
      api<PlayerDetail>(`/players/${id}`),
      api<ExamTemplate>(`/templates/${templateId}`),
    ])
      .then(([playerData, templateData]) => {
        if (cancelled) return;
        setPlayer(playerData);
        setTemplate(templateData);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudo cargar la plantilla");
      });

    return () => {
      cancelled = true;
    };
  }, [id, templateId]);

  const backHref = tabSlug
    ? `/perfil/${id}?tab=${encodeURIComponent(tabSlug)}`
    : `/perfil/${id}`;

  const goBack = () => router.push(backHref);

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.error} role="alert">
          {error}
        </div>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
      </div>
    );
  }

  if (!player || !template) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Cargando…</div>
      </div>
    );
  }

  const departmentName = template.department?.name ?? "Departamento";
  const mode = resolveInputMode(template);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
        <div className={styles.titles}>
          <span className={styles.eyebrow}>
            {player.first_name} {player.last_name} · {departmentName}
            <span className={styles.modeTag}>{mode}</span>
          </span>
          <h1 className={styles.title}>Nueva entrada · {template.name}</h1>
        </div>
      </header>

      <div className={styles.formWrap}>
        {mode === "bulk_ingest" ? (
          template.input_config?.column_mapping ? (
            <BulkIngestForm
              template={template}
              categoryId={player.category.id}
              onCommitted={goBack}
              onCancel={goBack}
            />
          ) : (
            <BulkIngestPlaceholder template={template} />
          )
        ) : (
          <DynamicUploader
            template={template}
            playerId={player.id}
            onSaved={goBack}
            onCancel={goBack}
          />
        )}
      </div>
    </div>
  );
}
