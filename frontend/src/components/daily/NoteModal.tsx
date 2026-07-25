"use client";

import React, { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DailyNote } from "./types";
import styles from "./NoteModal.module.css";

export default function NoteModal({
  open,
  date,
  playerId,
  note = null,
  players,
  departments,
  onClose,
  onSaved,
  kind = "pauta",
  title = "Nota de la reunión",
  placeholder = "Qué se decidió para este jugador hoy…",
}: {
  open: boolean;
  date: string;
  playerId: string | null; // preselected player (from a card) or null
  /** When set, the modal edits this existing note instead of creating one. */
  note?: DailyNote | null;
  players: { id: string; name: string }[];
  departments: { id: string; name: string; slug: string }[];
  onClose: () => void;
  onSaved: (note: DailyNote) => void;
  /** 'pauta' (default, morning meeting) or 'plan' (work-plan entry). */
  kind?: "pauta" | "plan";
  title?: string;
  placeholder?: string;
}) {
  const { toast } = useToast();
  const editing = note != null;
  const [player, setPlayer] = useState<string>("");
  const [department, setDepartment] = useState<string>("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const playerRef = useRef<HTMLSelectElement>(null);

  // Re-arm the form each time the modal opens — prefilled from `note` when
  // editing, otherwise blank for the (optionally preselected) player. Microtask
  // wrap keeps `react-hooks/set-state-in-effect` happy (runs before paint).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPlayer(note ? note.player_id : (playerId ?? ""));
      setDepartment(note ? (note.department?.id ?? "") : "");
      setText(note ? note.text : "");
      setError(null);
      setBusy(false);
    });
    return () => { cancelled = true; };
  }, [open, playerId, note]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!player) {
      setError("Selecciona un jugador.");
      playerRef.current?.focus();
      return;
    }
    if (!text.trim()) {
      setError("Escribe la nota.");
      textRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = editing
        ? await api<DailyNote>(`/daily-notes/${note!.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              department_id: department || null,
              text: text.trim(),
            }),
          })
        : await api<DailyNote>("/daily-notes", {
            method: "POST",
            body: JSON.stringify({
              player_id: player,
              department_id: department || null,
              kind,
              date,
              text: text.trim(),
            }),
          });
      toast.success(editing ? "Nota actualizada." : "Nota guardada.");
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar la nota.");
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form onSubmit={submit} className={styles.form}>
        {error && (
          <div className={styles.error} role="alert" id="daily-note-error">
            {error}
          </div>
        )}
        <label className={styles.field}>
          <span>Jugador</span>
          <select
            ref={playerRef}
            value={player}
            onChange={(e) => setPlayer(e.target.value)}
            // The player a note belongs to is fixed once created.
            disabled={editing}
            aria-invalid={!!error && !player}
            aria-describedby={error && !player ? "daily-note-error" : undefined}
          >
            <option value="">Selecciona…</option>
            {players.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Área</span>
          <select value={department} onChange={(e) => setDepartment(e.target.value)}>
            <option value="">General</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Nota</span>
          <textarea
            ref={textRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder={placeholder}
            aria-invalid={!!error && !text.trim()}
            aria-describedby={error && !text.trim() ? "daily-note-error" : undefined}
          />
        </label>
        <div className={styles.actions}>
          <button type="button" className={styles.ghost} onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="submit" className={styles.primary} disabled={busy}>
            {busy ? "Guardando…" : editing ? "Guardar cambios" : "Guardar nota"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
