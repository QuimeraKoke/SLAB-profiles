"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { api, ApiError } from "@/lib/api";
import type { CalendarEvent, EventType } from "@/lib/types";
import styles from "./ProfileEvents.module.css";

interface ProfileEventsProps {
  playerId: string;
}

const EVENT_TYPE_LABEL: Record<EventType, string> = {
  match: "Partido",
  training: "Entrenamiento",
  medical_checkup: "Chequeo médico",
  physical_test: "Test físico",
  team_speech: "Charla / reunión",
  nutrition: "Nutricional",
  other: "Otro",
};

const EVENT_TYPE_TONE: Record<EventType, string> = {
  match: "match",
  training: "training",
  medical_checkup: "medical",
  physical_test: "physical",
  team_speech: "speech",
  nutrition: "nutrition",
  other: "other",
};

export default function ProfileEvents({ playerId }: ProfileEventsProps) {
  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEvents(null);
    setError(null);

    api<CalendarEvent[]>(`/events?player_id=${playerId}`)
      .then((data) => {
        if (cancelled) return;
        setEvents(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudieron cargar los eventos.");
        setEvents([]);
      });

    return () => {
      cancelled = true;
    };
  }, [playerId]);

  const { upcoming, past } = useMemo(() => {
    if (!events) return { upcoming: [], past: [] };
    const now = Date.now();
    const upcoming: CalendarEvent[] = [];
    const past: CalendarEvent[] = [];
    for (const e of events) {
      if (new Date(e.starts_at).getTime() >= now) {
        upcoming.push(e);
      } else {
        past.push(e);
      }
    }
    upcoming.sort(
      (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
    );
    past.sort(
      (a, b) => new Date(b.starts_at).getTime() - new Date(a.starts_at).getTime(),
    );
    return { upcoming, past };
  }, [events]);

  const createHref = `/perfil/${playerId}/eventos/nuevo?tab=eventos`;

  if (events === null && !error) {
    return <div className={styles.loading}>Cargando eventos…</div>;
  }
  if (error) {
    return <div className={styles.error}>{error}</div>;
  }
  if (events!.length === 0) {
    return (
      <section className={styles.container}>
        <div className={styles.toolbar}>
          <Link href={createHref} className={styles.createBtn}>
            + Crear evento
          </Link>
        </div>
        <div className={styles.empty}>
          Este jugador no tiene eventos programados todavía. Usa{" "}
          <strong>Crear evento</strong> para agendar uno.
        </div>
      </section>
    );
  }

  return (
    <section className={styles.container}>
      <div className={styles.toolbar}>
        <Link href={createHref} className={styles.createBtn}>
          + Crear evento
        </Link>
      </div>
      {upcoming.length > 0 && (
        <div>
          <h3 className={styles.sectionTitle}>
            Próximos ({upcoming.length})
          </h3>
          <div className={styles.list}>
            {upcoming.map((e) => (
              <EventCard key={e.id} event={e} />
            ))}
          </div>
        </div>
      )}

      {past.length > 0 && (
        <div>
          <h3 className={styles.sectionTitle}>
            Pasados ({past.length})
          </h3>
          <div className={styles.list}>
            {past.map((e) => (
              <EventCard key={e.id} event={e} past />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function EventCard({ event, past = false }: { event: CalendarEvent; past?: boolean }) {
  const tone = EVENT_TYPE_TONE[event.event_type as EventType] ?? "other";
  const typeLabel = EVENT_TYPE_LABEL[event.event_type as EventType] ?? event.event_type;
  const dateLabel = formatDate(event.starts_at, event.ends_at);

  return (
    <article className={`${styles.card} ${past ? styles.past : ""}`}>
      <div className={styles.cardHeader}>
        <span className={`${styles.typeChip} ${styles[`tone_${tone}`]}`}>{typeLabel}</span>
        <span className={styles.deptTag}>{event.department.name}</span>
      </div>
      <h4 className={styles.title}>{event.title}</h4>
      <div className={styles.metaRow}>
        <span className={styles.dateLabel}>{dateLabel}</span>
        {event.location && <span className={styles.location}>· {event.location}</span>}
      </div>
      {event.description && <p className={styles.desc}>{event.description}</p>}
      <div className={styles.footer}>
        {event.scope === "category" && event.category ? (
          <span className={styles.scopeTag}>
            {event.category.name} · {event.participants.length} participantes
          </span>
        ) : event.scope === "individual" ? (
          <span className={styles.scopeTag}>Individual</span>
        ) : (
          <span className={styles.scopeTag}>
            {event.participants.length} participantes
          </span>
        )}
      </div>
    </article>
  );
}

function formatDate(startISO: string, endISO: string | null): string {
  const start = new Date(startISO);
  const datePart = start.toLocaleDateString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const startTime = start.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (!endISO) return `${datePart} · ${startTime}`;
  const end = new Date(endISO);
  const sameDay = start.toDateString() === end.toDateString();
  const endTime = end.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (sameDay) return `${datePart} · ${startTime} – ${endTime}`;
  const endDate = end.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
  });
  return `${datePart} ${startTime} → ${endDate} ${endTime}`;
}
