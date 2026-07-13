"use client";

import React, { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useToast } from "@/components/ui/Toast/Toast";
import type { Alert as AlertModel } from "@/lib/types";
import AlertList from "./AlertList";
import styles from "./ProfileAlerts.module.css";

/**
 * The "Alertas" profile tab: every ACTIVE alert for the player across all
 * departments (wellness bands, molestias, WADA/medication, training load,
 * goals), dismissible in place. Split out of the Objetivos tab — alerts
 * and goals are different conversations.
 */
type View = "active" | "resolved";

export default function ProfileAlerts({ playerId }: { playerId: string }) {
  const { toast } = useToast();
  const [view, setView] = useState<View>("active");
  const [alerts, setAlerts] = useState<AlertModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAlerts(null);
    setError(null);
    api<AlertModel[]>(`/players/${playerId}/alerts?status=${view}`)
      .then((a) => { if (!cancelled) setAlerts(a); })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "No se pudieron cargar las alertas.");
        }
      });
    return () => { cancelled = true; };
  }, [playerId, view]);

  const handleDismiss = async (alert: AlertModel) => {
    try {
      await api(`/alerts/${alert.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "dismissed" }),
      });
      setAlerts((prev) => (prev ?? []).filter((a) => a.id !== alert.id));
      toast.success("Alerta descartada.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al descartar la alerta.");
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.toggle} role="tablist" aria-label="Alertas">
        <button
          role="tab"
          aria-selected={view === "active"}
          className={`${styles.toggleBtn} ${view === "active" ? styles.toggleActive : ""}`}
          onClick={() => setView("active")}
        >
          Activas
        </button>
        <button
          role="tab"
          aria-selected={view === "resolved"}
          className={`${styles.toggleBtn} ${view === "resolved" ? styles.toggleActive : ""}`}
          onClick={() => setView("resolved")}
        >
          Historial
        </button>
      </div>

      {error ? (
        <div className={styles.error} role="alert">{error}</div>
      ) : alerts === null ? (
        <div className={styles.muted}>Cargando alertas…</div>
      ) : alerts.length === 0 ? (
        <div className={styles.empty}>
          {view === "active"
            ? "Sin alertas activas para este jugador. ✓"
            : "Sin alertas históricas."}
        </div>
      ) : (
        <AlertList
          alerts={alerts}
          mode={view === "resolved" ? "resolved" : "active"}
          onDismiss={view === "active" ? handleDismiss : undefined}
        />
      )}
    </div>
  );
}
