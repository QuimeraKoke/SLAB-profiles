"use client";

import React, { Suspense, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import AuthShell, { authStyles as styles } from "@/components/auth/AuthShell";
import { PASSWORD_HINT } from "@/components/auth/ChangePasswordForm";
import { useAuth } from "@/context/AuthContext";
import { api, ApiError } from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

function ResetForm() {
  const params = useSearchParams();
  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";
  const { startSession } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [linkDead, setLinkDead] = useState(!uid || !token);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const errorId = "reset-error";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem =
      password.length < 8 ? "La contraseña debe tener al menos 8 caracteres."
        : password !== confirm ? "Las dos contraseñas no coinciden." : null;
    if (problem) {
      setError(problem);
      inputRef.current?.focus();
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const res = await api<LoginResponse>("/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ uid, token, password }),
      });
      startSession(res);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "No se pudo guardar la contraseña.";
      if (message.startsWith("El enlace")) setLinkDead(true);
      setError(message);
      inputRef.current?.focus();
      setSubmitting(false);
    }
  };

  if (linkDead) {
    return (
      <AuthShell title="El enlace ya no sirve">
        <div className={styles.error} role="alert">
          {error ?? "Este enlace no es válido."} Los enlaces valen por una hora y
          sirven una sola vez.
        </div>
        <div className={styles.actions}>
          <Link href="/login" className={styles.link}>Volver a ingresar</Link>
          <Link href="/recuperar" className={styles.submit}>Pedir otro enlace</Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Elegí una contraseña nueva">
      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <label className={styles.field}>
          <span className={styles.label}>Nueva contraseña</span>
          <input
            ref={inputRef}
            type="password"
            className={styles.input}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            autoFocus
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
          <span className={styles.hint}>{PASSWORD_HINT}</span>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Repetila</span>
          <input
            type="password"
            className={styles.input}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
        </label>
        {error && <div id={errorId} role="alert" className={styles.error}>{error}</div>}
        <div className={styles.actions}>
          <button type="submit" className={styles.submit} disabled={submitting}>
            {submitting ? "Guardando…" : "Guardar e ingresar"}
          </button>
        </div>
      </form>
    </AuthShell>
  );
}

export default function RestablecerPage() {
  return (
    <Suspense fallback={null}>
      <ResetForm />
    </Suspense>
  );
}
