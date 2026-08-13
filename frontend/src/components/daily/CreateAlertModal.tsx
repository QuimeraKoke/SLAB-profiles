"use client";

import React, { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import styles from "./CreateAlertModal.module.css";

type Level = "leve" | "agudo";

export default function CreateAlertModal({
  open,
  defaultDate,
  playerId,
  players,
  onClose,
  onSaved,
}: {
  open: boolean;
  /** The Daily's current date — the alert date defaults here but is editable. */
  defaultDate: string;
  playerId: string | null; // preselected player (from a card) or null
  players: { id: string; name: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [player, setPlayer] = useState<string>("");
  const [level, setLevel] = useState<Level>("leve");
  const [message, setMessage] = useState("");
  const [alertDate, setAlertDate] = useState(defaultDate);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const playerRef = useRef<HTMLSelectElement>(null);

  // Re-arm the form each time the modal opens. Microtask wrap keeps
  // `react-hooks/set-state-in-effect` happy (runs before paint).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPlayer(playerId ?? "");
      setLevel("leve");
      setMessage("");
      setAlertDate(defaultDate);
      setError(null);
      setBusy(false);
    });
    return () => { cancelled = true; };
  }, [open, playerId, defaultDate]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!player) {
      setError("Selecciona un jugador.");
      playerRef.current?.focus();
      return;
    }
    if (!message.trim()) {
      setError("Escribe una descripción.");
      messageRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/alerts", {
        method: "POST",
        body: JSON.stringify({
          player_id: player,
          level,
          message: message.trim(),
          date: alertDate,
        }),
      });
      toast.success("Alerta creada.");
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la alerta.");
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="Crear alerta" onClose={onClose}>
      <form onSubmit={submit} className={styles.form}>
        {error && (
          <div className={styles.error} role="alert" id="create-alert-error">
            {error}
          </div>
        )}
        <label className={styles.field}>
          <span>Jugador</span>
          <select
            ref={playerRef}
            value={player}
            onChange={(e) => setPlayer(e.target.value)}
            aria-invalid={!!error && !player}
            aria-describedby={error && !player ? "create-alert-error" : undefined}
          >
            <option value="">Selecciona…</option>
            {players.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>

        <div className={styles.field}>
          <span>Severidad</span>
          <div className={styles.seg} role="radiogroup" aria-label="Severidad">
            <button
              type="button"
              role="radio"
              aria-checked={level === "leve"}
              className={`${styles.segBtn} ${styles.segLeve} ${level === "leve" ? styles.segOn : ""}`}
              onClick={() => setLevel("leve")}
            >
              <strong>Leve</strong>
              <small>Aviso · seguimiento</small>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={level === "agudo"}
              className={`${styles.segBtn} ${styles.segAgudo} ${level === "agudo" ? styles.segOn : ""}`}
              onClick={() => setLevel("agudo")}
            >
              <strong>Agudo</strong>
              <small>Crítico · atención inmediata</small>
            </button>
          </div>
        </div>

        <label className={styles.field}>
          <span>Fecha de la alerta</span>
          <input
            type="date"
            value={alertDate}
            onChange={(e) => setAlertDate(e.target.value)}
          />
        </label>

        <label className={styles.field}>
          <span>Descripción</span>
          <textarea
            ref={messageRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={4}
            placeholder="Qué observaste y por qué requiere atención…"
            aria-invalid={!!error && !message.trim()}
            aria-describedby={error && !message.trim() ? "create-alert-error" : undefined}
          />
        </label>

        <div className={styles.actions}>
          <button type="button" className={styles.ghost} onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="submit" className={styles.primary} disabled={busy}>
            {busy ? "Creando…" : "Crear alerta"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
