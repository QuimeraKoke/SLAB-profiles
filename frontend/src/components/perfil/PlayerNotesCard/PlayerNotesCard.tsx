"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  MessageSquarePlus,
  NotebookPen,
  Trash2,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import NoteModal from "@/components/daily/NoteModal";
import type { DailyNote } from "@/components/daily/types";
import type { Department } from "@/lib/types";
import styles from "./PlayerNotesCard.module.css";

type NoteKind = "pauta" | "plan";

interface Props {
  kind: NoteKind;
  playerId: string;
  playerName: string;
  departments: Department[];
}

const COPY: Record<
  NoteKind,
  {
    title: string;
    Icon: typeof NotebookPen;
    addLabel: string;
    emptyDay: string;
    emptyHistory: string;
    modalTitle: string;
    placeholder: string;
    deleteTitle: string;
  }
> = {
  pauta: {
    title: "Pauta del día",
    Icon: NotebookPen,
    addLabel: "Agregar nota",
    emptyDay:
      "Sin pauta para esta fecha. Registra qué debe hacer hoy este jugador — tarea, foco del entrenamiento, recuperación — por área.",
    emptyHistory: "Este jugador aún no tiene notas registradas.",
    modalTitle: "Nota de la reunión",
    placeholder: "Qué se decidió para este jugador hoy…",
    deleteTitle: "Eliminar nota",
  },
  plan: {
    title: "Plan de trabajo",
    Icon: ClipboardList,
    addLabel: "Agregar entrada",
    emptyDay:
      "Sin entradas del plan para esta fecha. Registra aquí las directrices para este jugador — progresión de fuerza, plan de recuperación, objetivos nutricionales — por área.",
    emptyHistory: "Este jugador aún no tiene plan de trabajo registrado.",
    modalTitle: "Entrada del plan de trabajo",
    placeholder:
      "Directriz vigente para este jugador — p. ej. bloque de fuerza 3×/semana, progresión de carrera, plan nutricional…",
    deleteTitle: "Eliminar entrada del plan",
  },
};

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function formatDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("es-CL", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/**
 * One player's dated notes of a given `kind`, seen from the profile:
 * - 'pauta' — what the morning meeting decided for the day.
 * - 'plan'  — the player's work plan entries (foco, progresiones, …).
 *
 * Both share `core.DailyNote` and the same UX: a day view grouped by área
 * (‹ › to move across days + Hoy), an "Historial" view of recent entries
 * across days grouped by date, and add/delete via the shared NoteModal.
 */
export default function PlayerNotesCard({ kind, playerId, playerName, departments }: Props) {
  const copy = COPY[kind];
  const canNote = usePermission("core.add_dailynote");
  const { confirm } = useConfirm();
  const { toast } = useToast();

  const [date, setDate] = useState(todayIso);
  const [history, setHistory] = useState(false);
  const [notes, setNotes] = useState<DailyNote[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const qs = history ? `?kind=${kind}&limit=100` : `?kind=${kind}&date=${date}`;
    api<DailyNote[]>(`/players/${playerId}/daily-notes${qs}`)
      .then((rows) => {
        if (!cancelled) setNotes(rows);
      })
      .catch(() => {
        if (!cancelled) setNotes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [playerId, kind, date, history, reloadKey]);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  // Day view: notes grouped by área. History view: grouped by meeting day.
  const groups = useMemo(() => {
    if (!notes) return [];
    const map = new Map<string, DailyNote[]>();
    for (const n of notes) {
      const key = history ? n.date : (n.department?.name ?? "General");
      const bucket = map.get(key) ?? [];
      bucket.push(n);
      map.set(key, bucket);
    }
    return [...map.entries()];
  }, [notes, history]);

  async function remove(note: DailyNote) {
    const ok = await confirm({
      title: copy.deleteTitle,
      message: `Se eliminará la nota sobre ${playerName}. Esta acción no se puede deshacer.`,
      confirmLabel: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api(`/daily-notes/${note.id}`, { method: "DELETE" });
      toast.success("Eliminada.");
      refetch();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar.");
    }
  }

  const isToday = date === todayIso();
  const titleId = `player-notes-${kind}-title`;

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <header className={styles.head}>
        <h2 id={titleId} className={styles.title}>
          <copy.Icon size={16} aria-hidden="true" />
          {copy.title}
        </h2>
        <div className={styles.controls}>
          {!history && (
            <span className={styles.dateNav}>
              <button
                className={styles.navBtn}
                onClick={() => setDate(shiftIso(date, -1))}
                aria-label="Día anterior"
              >
                <ChevronLeft size={14} aria-hidden="true" />
              </button>
              <span className={styles.dateLabel}>{formatDay(date)}</span>
              <button
                className={styles.navBtn}
                onClick={() => setDate(shiftIso(date, 1))}
                disabled={isToday}
                aria-label="Día siguiente"
              >
                <ChevronRight size={14} aria-hidden="true" />
              </button>
              {!isToday && (
                <button className={styles.todayBtn} onClick={() => setDate(todayIso())}>
                  Hoy
                </button>
              )}
            </span>
          )}
          <button
            className={`${styles.historyBtn} ${history ? styles.historyBtnActive : ""}`}
            aria-pressed={history}
            onClick={() => setHistory((h) => !h)}
          >
            Historial
          </button>
          {canNote && (
            <button className={styles.addBtn} onClick={() => setModalOpen(true)}>
              <MessageSquarePlus size={14} aria-hidden="true" />
              {copy.addLabel}
            </button>
          )}
        </div>
      </header>

      {notes === null ? (
        <p className={styles.loading}>Cargando…</p>
      ) : notes.length === 0 ? (
        <p className={styles.empty}>{history ? copy.emptyHistory : copy.emptyDay}</p>
      ) : (
        groups.map(([key, rows]) => (
          <div key={key} className={styles.group}>
            <span className={history ? styles.dateTitle : styles.groupTitle}>
              {history ? formatDay(key) : key}
            </span>
            <ul className={styles.list}>
              {rows.map((n) => (
                <li key={n.id} className={styles.row}>
                  {history && (
                    <span className={styles.dept}>{n.department?.name ?? "General"}</span>
                  )}
                  <div className={styles.body}>
                    <span className={styles.text}>{n.text}</span>
                    <span className={styles.byline}>
                      {n.author}
                      {" · "}
                      {new Date(n.created_at).toLocaleTimeString("es-CL", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  {n.mine && (
                    <button
                      className={styles.trash}
                      onClick={() => remove(n)}
                      aria-label="Eliminar"
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}

      <NoteModal
        open={modalOpen}
        date={history ? todayIso() : date}
        playerId={playerId}
        players={[{ id: playerId, name: playerName }]}
        departments={departments}
        onClose={() => setModalOpen(false)}
        onSaved={refetch}
        kind={kind}
        title={copy.modalTitle}
        placeholder={copy.placeholder}
      />
    </section>
  );
}
