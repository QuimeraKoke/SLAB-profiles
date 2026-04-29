"use client";

import React, { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import type {
  CalendarEvent,
  Department,
  EventType,
  EventScope,
  PlayerDetail,
  PlayerSummary,
} from "@/lib/types";
import styles from "./page.module.css";

interface PageProps {
  params: Promise<{ id: string }>;
}

const EVENT_TYPE_OPTIONS: { value: EventType; label: string }[] = [
  { value: "match", label: "Partido" },
  { value: "training", label: "Entrenamiento" },
  { value: "medical_checkup", label: "Chequeo médico" },
  { value: "physical_test", label: "Test físico" },
  { value: "team_speech", label: "Charla / reunión" },
  { value: "nutrition", label: "Nutricional" },
  { value: "other", label: "Otro" },
];

type FormScope = EventScope; // individual | category | custom

function combineDateTime(date: string, time: string): string {
  return time ? `${date}T${time}:00` : `${date}T12:00:00`;
}

function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function NuevoEventoPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabSlug = searchParams.get("tab") ?? "eventos";

  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [categoryRoster, setCategoryRoster] = useState<PlayerSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Form state
  const [departmentId, setDepartmentId] = useState<string>("");
  const [eventType, setEventType] = useState<EventType>("training");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [date, setDate] = useState(todayISO());
  const [startTime, setStartTime] = useState("10:00");
  const [endTime, setEndTime] = useState("");
  const [location, setLocation] = useState("");
  const [scope, setScope] = useState<FormScope>("individual");

  // Custom-scope state: explicit set of selected player ids + a name filter.
  // Seeded with the current player so the default subset is at least non-empty
  // when the user flips to "custom" mode.
  const [customSelected, setCustomSelected] = useState<Set<string>>(() => new Set([id]));
  const [customFilter, setCustomFilter] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Load player + departments + category roster
  useEffect(() => {
    let cancelled = false;
    setPlayer(null);
    setDepartments([]);
    setCategoryRoster(null);
    setLoadError(null);

    api<PlayerDetail>(`/players/${id}`)
      .then(async (p) => {
        if (cancelled) return;
        setPlayer(p);
        const [depts, roster] = await Promise.all([
          api<Department[]>(`/clubs/${p.club.id}/departments`),
          api<PlayerSummary[]>(`/players?category_id=${p.category.id}`),
        ]);
        if (cancelled) return;
        setDepartments(depts);
        setCategoryRoster(roster);
        // Default the department dropdown to the first accessible department
        // that the player's category opted into; else just the first one.
        const allowed = p.category.departments.map((d) => d.id);
        const preferred = depts.find((d) => allowed.includes(d.id)) ?? depts[0];
        if (preferred) setDepartmentId(preferred.id);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.message : "No se pudieron cargar los datos.");
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const backHref = `/perfil/${id}?tab=${encodeURIComponent(tabSlug)}`;
  const goBack = () => router.push(backHref);

  const participantIds = useMemo(() => {
    if (!player) return [];
    if (scope === "individual") return [player.id];
    if (scope === "category") {
      return (categoryRoster ?? []).map((p) => p.id);
    }
    // custom — preserve roster order so the API receives a stable list
    return (categoryRoster ?? [])
      .map((p) => p.id)
      .filter((pid) => customSelected.has(pid));
  }, [scope, player, categoryRoster, customSelected]);

  const filteredRoster = useMemo(() => {
    if (!categoryRoster) return [];
    const q = customFilter.trim().toLowerCase();
    if (!q) return categoryRoster;
    return categoryRoster.filter((p) =>
      `${p.first_name} ${p.last_name}`.toLowerCase().includes(q),
    );
  }, [categoryRoster, customFilter]);

  const toggleCustom = (playerId: string) => {
    setCustomSelected((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) {
        next.delete(playerId);
      } else {
        next.add(playerId);
      }
      return next;
    });
  };

  const selectAllVisible = () => {
    setCustomSelected((prev) => {
      const next = new Set(prev);
      for (const p of filteredRoster) next.add(p.id);
      return next;
    });
  };

  const clearAll = () => {
    setCustomSelected(new Set());
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!player || !departmentId) return;

    setSubmitError(null);
    if (!title.trim()) {
      setSubmitError("El título es obligatorio.");
      return;
    }
    if (endTime && endTime < startTime) {
      setSubmitError("La hora de término debe ser posterior a la de inicio.");
      return;
    }
    if (scope === "custom" && participantIds.length === 0) {
      setSubmitError("Selecciona al menos un jugador.");
      return;
    }

    setSubmitting(true);
    const payload = {
      department_id: departmentId,
      event_type: eventType,
      title: title.trim(),
      description: description.trim(),
      starts_at: combineDateTime(date, startTime),
      ends_at: endTime ? combineDateTime(date, endTime) : null,
      location: location.trim(),
      scope,
      category_id: scope === "category" ? player.category.id : null,
      participant_ids: participantIds,
    };

    try {
      await api<CalendarEvent>("/events", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      goBack();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "No se pudo crear el evento.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <div className={styles.container}>
        <div className={styles.error}>{loadError}</div>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
      </div>
    );
  }

  if (!player || departments.length === 0) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Cargando…</div>
      </div>
    );
  }

  const categoryParticipantCount = (categoryRoster ?? []).length;

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link href={backHref} className={styles.backLink}>
          ← Volver al perfil
        </Link>
        <div className={styles.titles}>
          <span className={styles.eyebrow}>
            {player.first_name} {player.last_name} · {player.category.name}
          </span>
          <h1 className={styles.title}>Nuevo evento</h1>
        </div>
      </header>

      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.row}>
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

          <label className={styles.field}>
            <span className={styles.label}>Tipo</span>
            <select
              required
              value={eventType}
              onChange={(e) => setEventType(e.target.value as EventType)}
            >
              {EVENT_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className={styles.field}>
          <span className={styles.label}>Título</span>
          <input
            type="text"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Ej. Chequeo pre-temporada"
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Descripción</span>
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Detalles, instrucciones, agenda…"
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
            placeholder="Ej. Centro Deportivo Azul"
          />
        </label>

        <fieldset className={styles.scopeBox}>
          <legend className={styles.scopeLegend}>Participantes</legend>
          <label className={styles.radio}>
            <input
              type="radio"
              name="scope"
              value="individual"
              checked={scope === "individual"}
              onChange={() => setScope("individual")}
            />
            <span>
              Solo este jugador{" "}
              <span className={styles.dim}>
                ({player.first_name} {player.last_name})
              </span>
            </span>
          </label>
          <label className={styles.radio}>
            <input
              type="radio"
              name="scope"
              value="category"
              checked={scope === "category"}
              onChange={() => setScope("category")}
            />
            <span>
              Toda la categoría: {player.category.name}{" "}
              <span className={styles.dim}>
                ({categoryParticipantCount} jugadores)
              </span>
            </span>
          </label>
          <label className={styles.radio}>
            <input
              type="radio"
              name="scope"
              value="custom"
              checked={scope === "custom"}
              onChange={() => setScope("custom")}
            />
            <span>
              Algunos jugadores{" "}
              <span className={styles.dim}>
                ({customSelected.size} seleccionados)
              </span>
            </span>
          </label>

          {scope === "custom" && (
            <div className={styles.customPicker}>
              <div className={styles.pickerToolbar}>
                <input
                  type="search"
                  className={styles.pickerSearch}
                  placeholder="Filtrar por nombre…"
                  value={customFilter}
                  onChange={(e) => setCustomFilter(e.target.value)}
                />
                <button
                  type="button"
                  className={styles.pickerActionBtn}
                  onClick={selectAllVisible}
                  disabled={filteredRoster.length === 0}
                >
                  Seleccionar visibles
                </button>
                <button
                  type="button"
                  className={styles.pickerActionBtn}
                  onClick={clearAll}
                  disabled={customSelected.size === 0}
                >
                  Limpiar
                </button>
              </div>
              <div className={styles.pickerList}>
                {filteredRoster.length === 0 ? (
                  <div className={styles.pickerEmpty}>
                    Ningún jugador coincide con el filtro.
                  </div>
                ) : (
                  filteredRoster.map((p) => (
                    <label key={p.id} className={styles.pickerRow}>
                      <input
                        type="checkbox"
                        checked={customSelected.has(p.id)}
                        onChange={() => toggleCustom(p.id)}
                      />
                      <span>
                        {p.first_name} {p.last_name}
                      </span>
                    </label>
                  ))
                )}
              </div>
            </div>
          )}
        </fieldset>

        {submitError && <div className={styles.error}>{submitError}</div>}

        <div className={styles.actions}>
          <Link href={backHref} className={styles.secondaryBtn}>
            Cancelar
          </Link>
          <button
            type="submit"
            className={styles.primaryBtn}
            disabled={submitting || !title.trim() || !departmentId}
          >
            {submitting ? "Guardando…" : "Crear evento"}
          </button>
        </div>
      </form>
    </div>
  );
}
