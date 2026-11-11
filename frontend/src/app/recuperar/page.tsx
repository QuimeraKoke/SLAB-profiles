"use client";

import React, { useRef, useState } from "react";
import Link from "next/link";

import AuthShell, { authStyles as styles } from "@/components/auth/AuthShell";
import { api, ApiError } from "@/lib/api";

export default function RecuperarPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const errorId = "recover-error";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!/.+@.+\..+/.test(email.trim())) {
      setError("Ingresa un email válido.");
      emailRef.current?.focus();
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await api("/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ email: email.trim() }),
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo enviar. Prueba de nuevo.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Recuperar contraseña"
      lead={sent ? undefined : "Te mandamos un enlace para elegir una contraseña nueva."}
    >
      {sent ? (
        <>
          <div className={styles.success} role="status">
            Si <strong>{email.trim()}</strong> tiene una cuenta en SLAB, te enviamos
            un enlace. Vale por una hora y sirve una sola vez. Revisa también la
            carpeta de spam.
          </div>
          <Link href="/login" className={styles.link}>Volver a ingresar</Link>
        </>
      ) : (
        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <label className={styles.field}>
            <span className={styles.label}>Correo</span>
            <input
              ref={emailRef}
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
            />
          </label>
          {error && <div id={errorId} role="alert" className={styles.error}>{error}</div>}
          <div className={styles.actions}>
            <Link href="/login" className={styles.link}>Volver</Link>
            <button type="submit" className={styles.submit} disabled={submitting}>
              {submitting ? "Enviando…" : "Enviar enlace"}
            </button>
          </div>
        </form>
      )}
    </AuthShell>
  );
}
