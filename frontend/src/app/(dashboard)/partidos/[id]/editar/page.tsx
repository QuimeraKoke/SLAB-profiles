"use client";

import React, { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import MatchForm from "@/components/partidos/MatchForm";
import TeamTableForm from "@/components/forms/TeamTableForm";
import { api, ApiError } from "@/lib/api";
import type { CalendarEvent, ExamTemplate } from "@/lib/types";
import styles from "./page.module.css";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function EditarPartidoPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();

  const [event, setEvent] = useState<CalendarEvent | null>(null);
  const [perfTemplate, setPerfTemplate] = useState<ExamTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setEvent(null);
      setError(null);
    });
    api<CalendarEvent>(`/events/${id}`)
      .then((data) => {
        if (cancelled) return;
        setEvent(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudo cargar el partido.");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Resolve the rendimiento_de_partido template once the event loads.
  // The /templates endpoint is keyed by player, so we look up via the
  // match's first participant (matches always have at least one). When
  // there are no participants we skip — the bulk-entry table doesn't
  // apply to a 0-player match anyway.
  useEffect(() => {
    if (!event) return;
    const firstParticipant = event.participants?.[0];
    if (!firstParticipant) return;
    let cancelled = false;
    api<ExamTemplate[]>(`/players/${firstParticipant.id}/templates`)
      .then((data) => {
        if (cancelled) return;
        const t = data.find((x) => x.slug === "rendimiento_de_partido");
        setPerfTemplate(t ?? null);
      })
      .catch(() => {
        if (!cancelled) setPerfTemplate(null);
      });
    return () => {
      cancelled = true;
    };
  }, [event]);

  const goBack = () => router.push("/partidos");

  const handleDelete = async () => {
    await api(`/events/${id}`, { method: "DELETE" });
    goBack();
  };

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBox}>{error}</div>
        <Link href="/partidos" className={styles.backLink}>
          ← Volver a partidos
        </Link>
      </div>
    );
  }

  if (!event) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Cargando…</div>
      </div>
    );
  }

  if (event.event_type !== "match") {
    return (
      <div className={styles.container}>
        <div className={styles.errorBox}>
          Este evento no es un partido y no se puede editar desde aquí.
        </div>
        <Link href="/partidos" className={styles.backLink}>
          ← Volver a partidos
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href="/partidos" className={styles.backLink}>
          ← Volver a partidos
        </Link>
        <h1 className={styles.title}>Editar partido</h1>
        {event.result_count > 0 && (
          <div className={styles.linkedBanner}>
            Este partido tiene <strong>{event.result_count}</strong>{" "}
            {event.result_count === 1 ? "registro vinculado" : "registros vinculados"}{" "}
            (GPS u otros). Eliminar el partido los conserva pero los desvincula.
          </div>
        )}
      </header>

      <MatchForm
        initial={event}
        onSaved={goBack}
        onCancel={goBack}
        onDelete={handleDelete}
      />

      {/* Bulk per-roster performance entry. Only renders when:
       *  - The match has participants (otherwise nobody to record)
       *  - The match has a category (team_table needs one for player scoping)
       *  - The Rendimiento de partido template loaded with team_table mode */}
      {perfTemplate
        && event.category
        && event.participants.length > 0
        && (perfTemplate.input_config?.input_modes ?? []).includes("team_table") && (
          <section className={styles.perfSection}>
            <header className={styles.perfHeader}>
              <h2 className={styles.perfTitle}>Rendimiento por jugador</h2>
              <span className={styles.perfHint}>
                {event.result_count} {event.result_count === 1 ? "registro guardado" : "registros guardados"}{" "}
                · una fila por convocado. Los valores se vinculan automáticamente al partido.
              </span>
            </header>
            <TeamTableForm
              key={refreshKey}
              template={perfTemplate}
              categoryId={event.category.id}
              eventId={event.id}
              participantIds={event.participants.map((p) => p.id)}
              onCommitted={() => setRefreshKey((k) => k + 1)}
            />
          </section>
        )}
    </div>
  );
}
