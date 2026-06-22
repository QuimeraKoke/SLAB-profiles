"use client";

import React, { use, useEffect, useState } from "react";
import Link from "next/link";

import TeamReportDashboard from "@/components/reports/TeamReportDashboard";
import { useBreadcrumbLabel } from "@/components/layout/Breadcrumbs";
import { api, ApiError } from "@/lib/api";
import type { CalendarEvent, MatchReportResponse } from "@/lib/types";
import styles from "./page.module.css";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * Match detail + combined report (read-only viewing surface).
 *
 * Shows the match header and the cross-department "Reporte de partido"
 * (GPS físico + rendimiento táctico) LOCKED to this match — there is no
 * in-page match selector, the route's `id` is the match. Editing the
 * match lives on the separate `/partidos/[id]/editar` CRUD surface.
 */
export default function PartidoDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const setBreadcrumbLabel = useBreadcrumbLabel();

  const [event, setEvent] = useState<CalendarEvent | null>(null);
  const [report, setReport] = useState<MatchReportResponse["layout"] | null>(null);
  const [reportFetched, setReportFetched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Match metadata (for the header + breadcrumb).
  useEffect(() => {
    let cancelled = false;
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

  // Combined match report, locked to this match.
  useEffect(() => {
    let cancelled = false;
    // Reset off the synchronous effect body (React 19 set-state-in-effect).
    Promise.resolve().then(() => {
      if (cancelled) return;
      setReportFetched(false);
    });
    api<MatchReportResponse>(`/matches/${id}/report`)
      .then((data) => {
        if (cancelled) return;
        setReport(data.layout);
        setReportFetched(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudo cargar el reporte.");
        setReportFetched(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Breadcrumb: Inicio › Partidos › <match title>.
  useEffect(() => {
    if (event) setBreadcrumbLabel(id, event.title);
  }, [event, id, setBreadcrumbLabel]);

  const dateLabel = event
    ? new Date(event.starts_at).toLocaleDateString("es-CL", {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href="/partidos" className={styles.backLink}>
          ← Volver a partidos
        </Link>
        <div className={styles.titleRow}>
          <div>
            <h1 className={styles.title}>{event?.title ?? "Partido"}</h1>
            {event && (
              <p className={styles.meta}>
                <span className={styles.metaDate}>{dateLabel}</span>
                {event.location && <span className={styles.dot}>·</span>}
                {event.location && <span>{event.location}</span>}
                {event.category && <span className={styles.dot}>·</span>}
                {event.category && <span>{event.category.name}</span>}
              </p>
            )}
          </div>
          <Link href={`/partidos/${id}/editar`} className={styles.editBtn}>
            Editar partido
          </Link>
        </div>
      </header>

      {error && <div className={styles.errorBox}>{error}</div>}

      {report ? (
        <>
          <div className={styles.reportLead}>
            <h2 className={styles.reportTitle}>Reporte de partido</h2>
            <span className={styles.reportHint}>
              Físico (GPS) + Táctico, fijado a este partido.
            </span>
          </div>
          <TeamReportDashboard sections={report.sections} />
        </>
      ) : (
        reportFetched && !error && (
          <div className={styles.placeholder}>
            <strong>Sin reporte para este partido.</strong>
            <p>
              No hay datos de GPS ni de rendimiento vinculados a este partido
              todavía. Cargá los datos desde{" "}
              <Link href={`/partidos/${id}/editar`} className={styles.inlineLink}>
                Editar partido
              </Link>{" "}
              y volvé acá para ver el reporte combinado.
            </p>
          </div>
        )
      )}
    </div>
  );
}
