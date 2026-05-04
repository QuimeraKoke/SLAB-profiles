"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import MatchesCalendar from "@/components/partidos/MatchesCalendar";
import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import type { CalendarEvent } from "@/lib/types";
import styles from "./page.module.css";

type Filter = "upcoming" | "past" | "all";
type View = "calendar" | "table";

export default function PartidosPage() {
  const [matches, setMatches] = useState<CalendarEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<View>("calendar");
  const [reloadKey, setReloadKey] = useState(0);

  // Calendar viewing month — defaults to current month.
  const [calMonth, setCalMonth] = useState<{ year: number; month: number }>(() => {
    const d = new Date();
    return { year: d.getFullYear(), month: d.getMonth() + 1 };
  });

  const goPrevMonth = () => {
    setCalMonth(({ year, month }) =>
      month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 },
    );
  };
  const goNextMonth = () => {
    setCalMonth(({ year, month }) =>
      month === 12 ? { year: year + 1, month: 1 } : { year, month: month + 1 },
    );
  };
  const goToday = () => {
    const d = new Date();
    setCalMonth({ year: d.getFullYear(), month: d.getMonth() + 1 });
  };

  const { categoryId, loading: categoryLoading } = useCategoryContext();

  useEffect(() => {
    if (categoryLoading) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setMatches(null);
      setError(null);
    });

    const params = new URLSearchParams({ event_type: "match" });
    if (categoryId) params.set("category_id", categoryId);
    api<CalendarEvent[]>(`/events?${params}`)
      .then((data) => {
        if (cancelled) return;
        // Newest first by start time.
        const sorted = [...data].sort(
          (a, b) => new Date(b.starts_at).getTime() - new Date(a.starts_at).getTime(),
        );
        setMatches(sorted);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudieron cargar los partidos.");
        setMatches([]);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey, categoryId, categoryLoading]);

  // Snapshot "now" on mount so the upcoming/past filter is stable across
  // re-renders. The lint rule `react-hooks/purity` flags Date.now() inside
  // useMemo because re-renders would shift the boundary; freezing on mount
  // gives a deterministic split for the page's lifetime. Adequate UX —
  // matches don't move fast enough that a half-second drift matters.
  const [now] = useState(() => Date.now());

  const filtered = useMemo(() => {
    if (!matches) return [];
    if (filter === "upcoming") {
      return matches.filter((m) => new Date(m.starts_at).getTime() >= now)
        .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime());
    }
    if (filter === "past") {
      return matches.filter((m) => new Date(m.starts_at).getTime() < now);
    }
    return matches;
  }, [matches, filter, now]);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Partidos</h1>
          <p className={styles.subtitle}>
            Calendario de partidos. Crea, edita y conecta cada partido con sus
            cargas de datos (GPS, etc.).
          </p>
        </div>
        <Link href="/partidos/nuevo" className={styles.primaryBtn}>
          + Nuevo partido
        </Link>
      </header>

      <div className={styles.toolbar}>
        <div className={styles.viewToggle}>
          <button
            type="button"
            className={`${styles.viewBtn} ${view === "calendar" ? styles.viewBtnActive : ""}`}
            onClick={() => setView("calendar")}
          >
            Calendario
          </button>
          <button
            type="button"
            className={`${styles.viewBtn} ${view === "table" ? styles.viewBtnActive : ""}`}
            onClick={() => setView("table")}
          >
            Tabla
          </button>
        </div>
        {view === "table" && (
          <div className={styles.filterBar}>
            {(["all", "upcoming", "past"] as Filter[]).map((f) => (
              <button
                key={f}
                type="button"
                className={`${styles.filterBtn} ${filter === f ? styles.filterBtnActive : ""}`}
                onClick={() => setFilter(f)}
              >
                {f === "all" ? "Todos" : f === "upcoming" ? "Próximos" : "Pasados"}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {matches === null && !error ? (
        <div className={styles.loading}>Cargando partidos…</div>
      ) : view === "calendar" ? (
        <>
          <MatchesCalendar
            matches={matches!}
            month={calMonth.month}
            year={calMonth.year}
            onPrev={goPrevMonth}
            onNext={goNextMonth}
            onToday={goToday}
          />
          {matches!.length === 0 && (
            <div className={styles.calendarEmptyHint}>
              No hay partidos en el calendario todavía.{" "}
              <Link href="/partidos/nuevo">Crear el primero →</Link>
            </div>
          )}
        </>
      ) : filtered.length === 0 ? (
        <div className={styles.empty}>
          {filter === "all"
            ? "No hay partidos en el calendario todavía."
            : filter === "upcoming"
            ? "No hay partidos próximos."
            : "No hay partidos pasados."}{" "}
          <Link href="/partidos/nuevo">Crear el primero →</Link>
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Partido</th>
                <th>Categoría</th>
                <th>Departamento</th>
                <th>Lugar</th>
                <th className={styles.numericCell}>Convocados</th>
                <th className={styles.numericCell}>Datos</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((m) => (
                <MatchRow key={m.id} match={m} onChanged={() => setReloadKey((k) => k + 1)} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function MatchRow({
  match,
  onChanged,
}: {
  match: CalendarEvent;
  onChanged: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Same lint rationale as the parent page: snapshot "now" on mount so
  // `isPast` is deterministic across re-renders. Adequate for showing
  // "(pasado)" copy on a card.
  const [now] = useState(() => Date.now());
  const isPast = new Date(match.starts_at).getTime() < now;
  const dateLabel = formatDate(match.starts_at);

  const handleDelete = async () => {
    if (!confirm(`¿Eliminar el partido "${match.title}"? Los datos vinculados quedarán sin partido asociado.`)) {
      return;
    }
    setError(null);
    setDeleting(true);
    try {
      await api(`/events/${match.id}`, { method: "DELETE" });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo eliminar.");
      setDeleting(false);
    }
  };

  return (
    <tr className={isPast ? styles.pastRow : ""}>
      <td>
        <span className={styles.dateLabel}>{dateLabel}</span>
      </td>
      <td>
        <span className={styles.matchTitle}>{match.title}</span>
        {match.description && <div className={styles.matchDesc}>{match.description}</div>}
      </td>
      <td>{match.category?.name ?? "—"}</td>
      <td>{match.department.name}</td>
      <td className={styles.dim}>{match.location || "—"}</td>
      <td className={styles.numericCell}>{match.participants.length}</td>
      <td className={styles.numericCell}>
        {match.result_count > 0 ? (
          <span className={styles.dataChip}>{match.result_count}</span>
        ) : (
          <span className={styles.dim}>—</span>
        )}
      </td>
      <td className={styles.actionsCell}>
        <Link href={`/partidos/${match.id}/editar`} className={styles.actionLink}>
          Editar
        </Link>
        <button
          type="button"
          className={styles.deleteBtn}
          onClick={handleDelete}
          disabled={deleting}
        >
          {deleting ? "…" : "Eliminar"}
        </button>
        {error && <div className={styles.errorInline}>{error}</div>}
      </td>
    </tr>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleDateString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date} · ${time}`;
}
