"use client";

import React, { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DailyNote } from "@/components/daily/types";
import styles from "./ActionModal.module.css";

/**
 * "Agregar a plan de trabajo" (§7.2) — from a briefing card, drop the
 * recommendation into a player's plan (DailyNote kind="plan") in one click.
 * Shows the player's current plan so the user sees what's already there.
 */
export default function AddToPlanModal({
  open,
  onClose,
  playerIds,
  nameById,
  recommendation,
}: {
  open: boolean;
  onClose: () => void;
  playerIds: string[];
  nameById: Map<string, string>;
  recommendation: string;
}) {
  const { toast } = useToast();
  const [player, setPlayer] = useState("");
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<DailyNote[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-arm each open (microtask keeps react-hooks/set-state-in-effect happy).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPlayer(playerIds[0] ?? "");
      setText(recommendation);
      setError(null);
      setBusy(false);
    });
    return () => { cancelled = true; };
  }, [open, playerIds, recommendation]);

  // Load the selected player's current plan.
  useEffect(() => {
    if (!open || !player) { setPlan(null); return; }
    let cancelled = false;
    setPlan(null);
    api<DailyNote[]>(`/players/${player}/daily-notes?kind=plan&limit=20`)
      .then((n) => { if (!cancelled) setPlan(n); })
      .catch(() => { if (!cancelled) setPlan([]); });
    return () => { cancelled = true; };
  }, [open, player]);

  async function add() {
    if (!player || !text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const note = await api<DailyNote>("/daily-notes", {
        method: "POST",
        body: JSON.stringify({
          player_id: player, kind: "plan", date: today, text: text.trim(),
        }),
      });
      setPlan((prev) => [note, ...(prev ?? [])]);
      toast.success("Agregado al plan de trabajo.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo agregar al plan.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title="Agregar a plan de trabajo" onClose={onClose}>
      <div className={styles.body}>
        {playerIds.length > 1 && (
          <label className={styles.field}>
            <span>Jugador</span>
            <select value={player} onChange={(e) => setPlayer(e.target.value)}>
              {playerIds.map((id) => (
                <option key={id} value={id}>{nameById.get(id) ?? "Jugador"}</option>
              ))}
            </select>
          </label>
        )}
        {playerIds.length === 1 && (
          <div className={styles.who}>{nameById.get(player) ?? "Jugador"}</div>
        )}

        <div className={styles.section}>
          <div className={styles.sectionLabel}>Plan actual</div>
          {plan === null ? (
            <p className={styles.muted}>Cargando…</p>
          ) : plan.length === 0 ? (
            <p className={styles.muted}>Sin tareas en el plan todavía.</p>
          ) : (
            <ul className={styles.planList}>
              {plan.map((n) => (
                <li key={n.id} className={styles.planItem}>
                  <span className={styles.planText}>{n.text}</span>
                  <span className={styles.planMeta}>
                    {n.department?.name ?? "General"} · {n.author}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className={styles.section}>
          <div className={styles.sectionLabel}>Nueva tarea</div>
          <textarea
            className={styles.textarea}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="Tarea para el plan de trabajo…"
          />
        </div>

        {error && <div className={styles.error} role="alert">{error}</div>}

        <div className={styles.actions}>
          <button type="button" className={styles.ghost} onClick={onClose} disabled={busy}>
            Cerrar
          </button>
          <button
            type="button"
            className={styles.primary}
            onClick={add}
            disabled={busy || !player || !text.trim()}
          >
            {busy ? "Agregando…" : "Agregar al plan"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
