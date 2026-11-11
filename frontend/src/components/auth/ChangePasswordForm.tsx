"use client";

import React, { useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { MeResponse } from "@/lib/types";
import { authStyles as styles } from "./AuthShell";

export const PASSWORD_HINT =
  "Mínimo 8 caracteres. Que no sea solo números ni una contraseña común.";

type Bad = "current" | "next" | null;

/** Current password + the new one twice → POST /auth/password/change.
 *  Used by the forced screen and by "Cambiar contraseña" in the sidebar. */
export default function ChangePasswordForm({
  currentLabel = "Contraseña actual",
  onDone,
  onCancel,
}: {
  currentLabel?: string;
  onDone: (me: MeResponse) => void;
  onCancel?: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [bad, setBad] = useState<Bad>(null);
  const [submitting, setSubmitting] = useState(false);
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const errorId = "change-password-error";

  const fail = (field: Exclude<Bad, null>, message: string) => {
    setBad(field);
    setError(message);
    (field === "current" ? currentRef : nextRef).current?.focus();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!current) return fail("current", `Ingresa tu ${currentLabel.toLowerCase()}.`);
    if (next.length < 8) return fail("next", "La nueva contraseña debe tener al menos 8 caracteres.");
    if (next !== confirm) return fail("next", "Las dos contraseñas nuevas no coinciden.");
    setBad(null);
    setError(null);
    setSubmitting(true);
    try {
      const me = await api<MeResponse>("/auth/password/change", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      onDone(me);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "No se pudo cambiar la contraseña.";
      fail(message.startsWith("La contraseña actual") ? "current" : "next", message);
    } finally {
      setSubmitting(false);
    }
  };

  const invalid = (field: Exclude<Bad, null>) =>
    bad === field ? { "aria-invalid": true, "aria-describedby": errorId } : {};

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <label className={styles.field}>
        <span className={styles.label}>{currentLabel}</span>
        <input
          ref={currentRef}
          type="password"
          className={styles.input}
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          {...invalid("current")}
        />
      </label>
      <label className={styles.field}>
        <span className={styles.label}>Nueva contraseña</span>
        <input
          ref={nextRef}
          type="password"
          className={styles.input}
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          {...invalid("next")}
        />
        <span className={styles.hint}>{PASSWORD_HINT}</span>
      </label>
      <label className={styles.field}>
        <span className={styles.label}>Repite la nueva contraseña</span>
        <input
          type="password"
          className={styles.input}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          {...invalid("next")}
        />
      </label>

      {error && (
        <div id={errorId} role="alert" className={styles.error}>{error}</div>
      )}

      <div className={styles.actions}>
        {onCancel && (
          <button type="button" className={styles.link} onClick={onCancel} disabled={submitting}>
            Cancelar
          </button>
        )}
        <button type="submit" className={styles.submit} disabled={submitting}>
          {submitting ? "Guardando…" : "Cambiar contraseña"}
        </button>
      </div>
    </form>
  );
}
