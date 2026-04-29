"use client";

import React, { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import MatchForm from "@/components/partidos/MatchForm";
import { api, ApiError } from "@/lib/api";
import type { CalendarEvent } from "@/lib/types";
import styles from "./page.module.css";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function EditarPartidoPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();

  const [event, setEvent] = useState<CalendarEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEvent(null);
    setError(null);
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
    </div>
  );
}
