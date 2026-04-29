"use client";

import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type {
  CalendarEvent,
  Category,
  Department,
  PlayerSummary,
} from "@/lib/types";
import styles from "./MatchForm.module.css";

interface MatchFormProps {
  /** When provided, the form runs in edit mode and prefills from this event. */
  initial?: CalendarEvent;
  onSaved: () => void;
  onCancel: () => void;
  /** Called when the user clicks Delete (only used in edit mode). */
  onDelete?: () => Promise<void> | void;
}

function todayISO(): string {
  const d = new Date();
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, "0"),
    String(d.getDate()).padStart(2, "0"),
  ].join("-");
}

function combineDateTime(date: string, time: string): string {
  return time ? `${date}T${time}:00` : `${date}T15:00:00`;
}

function splitDate(iso: string): { date: string; time: string } {
  // Backend returns ISO strings (e.g. "2026-04-01T15:00:00+00:00").
  // For form fields we want local-day + local-time, but since we're
  // round-tripping the same string back, just slice.
  const date = iso.slice(0, 10);
  const time = iso.slice(11, 16);
  return { date, time };
}

export default function MatchForm({
  initial,
  onSaved,
  onCancel,
  onDelete,
}: MatchFormProps) {
  const isEdit = !!initial;

  const [departments, setDepartments] = useState<Department[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Form state
  const [departmentId, setDepartmentId] = useState(initial?.department.id ?? "");
  const [categoryId, setCategoryId] = useState(initial?.category?.id ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [date, setDate] = useState(
    initial ? splitDate(initial.starts_at).date : todayISO(),
  );
  const [startTime, setStartTime] = useState(
    initial ? splitDate(initial.starts_at).time : "15:00",
  );
  const [endTime, setEndTime] = useState(
    initial?.ends_at ? splitDate(initial.ends_at).time : "",
  );
  const [location, setLocation] = useState(initial?.location ?? "");

  // Match-specific metadata stored in event.metadata. Lives in JSONB so the
  // shape can grow (goals[], lineup, etc.) without schema migrations.
  const initialMeta = (initial?.metadata ?? {}) as Record<string, unknown>;
  const [opponent, setOpponent] = useState(String(initialMeta.opponent ?? ""));
  const [competition, setCompetition] = useState(String(initialMeta.competition ?? ""));
  const [isHome, setIsHome] = useState<boolean>(
    typeof initialMeta.is_home === "boolean" ? (initialMeta.is_home as boolean) : true,
  );
  const initialScore = (initialMeta.score ?? {}) as Record<string, unknown>;
  const [homeScore, setHomeScore] = useState<string>(
    initialScore.home != null ? String(initialScore.home) : "",
  );
  const [awayScore, setAwayScore] = useState<string>(
    initialScore.away != null ? String(initialScore.away) : "",
  );
  const [durationMin, setDurationMin] = useState<string>(
    initialMeta.duration_min != null ? String(initialMeta.duration_min) : "90",
  );

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Load departments + categories. We need both before rendering.
  useEffect(() => {
    let cancelled = false;
    setLoadError(null);

    Promise.all([
      api<Category[]>("/categories"),
    ])
      .then(async ([cats]) => {
        if (cancelled) return;
        setCategories(cats);

        // Default category: keep initial if editing; else first available.
        const fallbackCat = initial?.category?.id ?? cats[0]?.id ?? "";
        if (!categoryId && fallbackCat) setCategoryId(fallbackCat);

        // Departments depend on the selected category's club. Use that club
        // (or initial.club) to scope the dropdown.
        const club =
          initial?.club ??
          cats.find((c) => c.id === fallbackCat)?.club_id ??
          null;
        if (!club) return;
        const clubId = typeof club === "string" ? club : club.id;
        const depts = await api<Department[]>(`/clubs/${clubId}/departments`);
        if (cancelled) return;
        setDepartments(depts);
        const fallbackDept = initial?.department.id ?? depts[0]?.id ?? "";
        if (!departmentId && fallbackDept) setDepartmentId(fallbackDept);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(
          err instanceof ApiError ? err.message : "No se pudieron cargar los datos.",
        );
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When the user picks a different category, refresh the departments
  // dropdown to that category's club.
  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId) ?? null,
    [categories, categoryId],
  );

  useEffect(() => {
    if (!selectedCategory) return;
    let cancelled = false;
    api<Department[]>(`/clubs/${selectedCategory.club_id}/departments`)
      .then((depts) => {
        if (cancelled) return;
        setDepartments(depts);
        // If the currently-selected department isn't in the new list, reset.
        if (departmentId && !depts.some((d) => d.id === departmentId)) {
          setDepartmentId(depts[0]?.id ?? "");
        }
      })
      .catch(() => {
        // Non-fatal — prior departments stay shown.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategory?.club_id]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);

    if (!title.trim()) return setSubmitError("El título es obligatorio.");
    if (!departmentId) return setSubmitError("Selecciona un departamento.");
    if (!categoryId) return setSubmitError("Selecciona una categoría.");
    if (endTime && endTime < startTime) {
      return setSubmitError("La hora de término debe ser posterior a la de inicio.");
    }

    setSubmitting(true);

    // Roster: every active player in the chosen category.
    let participantIds: string[] = [];
    try {
      const roster = await api<PlayerSummary[]>(`/players?category_id=${categoryId}`);
      participantIds = roster.map((p) => p.id);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "No se pudo cargar la nómina.");
      setSubmitting(false);
      return;
    }

    const metadata: Record<string, unknown> = {
      ...initialMeta,
      is_home: isHome,
      opponent: opponent.trim(),
      competition: competition.trim(),
      duration_min: durationMin ? Number(durationMin) : null,
      score:
        homeScore !== "" || awayScore !== ""
          ? {
              home: homeScore !== "" ? Number(homeScore) : null,
              away: awayScore !== "" ? Number(awayScore) : null,
            }
          : null,
    };

    const payload = {
      department_id: departmentId,
      event_type: "match" as const,
      title: title.trim(),
      description: description.trim(),
      starts_at: combineDateTime(date, startTime),
      ends_at: endTime ? combineDateTime(date, endTime) : null,
      location: location.trim(),
      scope: "category" as const,
      category_id: categoryId,
      participant_ids: participantIds,
      metadata,
    };

    try {
      if (isEdit && initial) {
        await api<CalendarEvent>(`/events/${initial.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await api<CalendarEvent>("/events", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      onSaved();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "No se pudo guardar el partido.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    setSubmitError(null);
    setSubmitting(true);
    try {
      await onDelete();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "No se pudo eliminar.");
      setSubmitting(false);
    }
  };

  if (loadError) {
    return <div className={styles.error}>{loadError}</div>;
  }
  if (categories.length === 0 || departments.length === 0) {
    return <div className={styles.loading}>Cargando…</div>;
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.row}>
        <label className={styles.field}>
          <span className={styles.label}>Categoría</span>
          <select
            required
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Departamento</span>
          <select
            required
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
          >
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className={styles.field}>
        <span className={styles.label}>Rival / título</span>
        <input
          type="text"
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Ej. vs U.Católica"
        />
      </label>

      <div className={styles.row}>
        <label className={styles.field}>
          <span className={styles.label}>Fecha</span>
          <input
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Inicio</span>
          <input
            type="time"
            required
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Término (opcional)</span>
          <input
            type="time"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
          />
        </label>
      </div>

      <label className={styles.field}>
        <span className={styles.label}>Lugar (opcional)</span>
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="Ej. Estadio Nacional"
        />
      </label>

      <fieldset className={styles.metaBox}>
        <legend className={styles.metaLegend}>Datos del partido</legend>

        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>Rival</span>
            <input
              type="text"
              value={opponent}
              onChange={(e) => setOpponent(e.target.value)}
              placeholder="Ej. U.Católica"
            />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>Competición</span>
            <input
              type="text"
              value={competition}
              onChange={(e) => setCompetition(e.target.value)}
              placeholder="Ej. Liga 2026 - Fecha 8"
            />
          </label>
        </div>

        <div className={styles.localRow}>
          <label className={styles.localOption}>
            <input
              type="radio"
              name="is_home"
              checked={isHome}
              onChange={() => setIsHome(true)}
            />
            <span>Local</span>
          </label>
          <label className={styles.localOption}>
            <input
              type="radio"
              name="is_home"
              checked={!isHome}
              onChange={() => setIsHome(false)}
            />
            <span>Visita</span>
          </label>
        </div>

        <div className={styles.row}>
          <label className={styles.field}>
            <span className={styles.label}>
              {isHome ? "Goles propios" : "Goles propios (visita)"}
            </span>
            <input
              type="number"
              min={0}
              value={isHome ? homeScore : awayScore}
              onChange={(e) =>
                isHome ? setHomeScore(e.target.value) : setAwayScore(e.target.value)
              }
              placeholder="0"
            />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>Goles rival</span>
            <input
              type="number"
              min={0}
              value={isHome ? awayScore : homeScore}
              onChange={(e) =>
                isHome ? setAwayScore(e.target.value) : setHomeScore(e.target.value)
              }
              placeholder="0"
            />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>Duración total</span>
            <input
              type="number"
              min={0}
              value={durationMin}
              onChange={(e) => setDurationMin(e.target.value)}
              placeholder="90"
            />
          </label>
        </div>
      </fieldset>

      <label className={styles.field}>
        <span className={styles.label}>Notas (opcional)</span>
        <textarea
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Fecha del torneo, contexto, observaciones…"
        />
      </label>

      {submitError && <div className={styles.error}>{submitError}</div>}

      <div className={styles.actions}>
        {isEdit && onDelete && (
          <button
            type="button"
            className={styles.dangerBtn}
            onClick={() => setConfirmDelete(true)}
            disabled={submitting}
          >
            Eliminar
          </button>
        )}
        <div className={styles.actionsRight}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={onCancel}
            disabled={submitting}
          >
            Cancelar
          </button>
          <button
            type="submit"
            className={styles.primaryBtn}
            disabled={submitting}
          >
            {submitting ? "Guardando…" : isEdit ? "Guardar cambios" : "Crear partido"}
          </button>
        </div>
      </div>

      {confirmDelete && (
        <div className={styles.confirmModal}>
          <p>
            ¿Eliminar este partido? Los registros (GPS, etc.) vinculados conservarán
            sus datos pero quedarán sin partido asociado.
          </p>
          <div className={styles.confirmActions}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => setConfirmDelete(false)}
              disabled={submitting}
            >
              Cancelar
            </button>
            <button
              type="button"
              className={styles.dangerBtn}
              onClick={handleDelete}
              disabled={submitting}
            >
              {submitting ? "Eliminando…" : "Sí, eliminar"}
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
