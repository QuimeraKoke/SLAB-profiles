"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
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
import styles from "./PautaDelDia.module.css";

interface Props {
  playerId: string;
  playerName: string;
  departments: Department[];
}

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
 * The player's "Pauta del día" — what the morning meeting decided for this
 * player today (tarea, foco del entrenamiento, recuperación, …), one note
 * per área. Same `core.DailyNote` records as the /daily meeting view, seen
 * from the player's side: a day view grouped by área (‹ › to move across
 * meeting days) and a history view of the most recent notes across days.
 */
export default function PautaDelDia({ playerId, playerName, departments }: Props) {
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
    const qs = history ? "" : `?date=${date}`;
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
  }, [playerId, date, history, reloadKey]);

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
      title: "Eliminar nota",
      message: `Se eliminará la nota sobre ${playerName}. Esta acción no se puede deshacer.`,
      confirmLabel: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api(`/daily-notes/${note.id}`, { method: "DELETE" });
      toast.success("Nota eliminada.");
      refetch();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar la nota.");
    }
  }

  const isToday = date === todayIso();

  return (
    <section className={styles.panel} aria-labelledby="pauta-title">
      <header className={styles.head}>
        <h2 id="pauta-title" className={styles.title}>
          <NotebookPen size={16} aria-hidden="true" />
          Pauta del día
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
              Agregar nota
            </button>
          )}
        </div>
      </header>

      {notes === null ? (
        <p className={styles.loading}>Cargando…</p>
      ) : notes.length === 0 ? (
        <p className={styles.empty}>
          {history
            ? "Este jugador aún no tiene notas registradas."
            : "Sin pauta para esta fecha. Registra qué debe hacer hoy este jugador — tarea, foco del entrenamiento, recuperación — por área."}
        </p>
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
                      aria-label="Eliminar nota"
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
      />
    </section>
  );
}
