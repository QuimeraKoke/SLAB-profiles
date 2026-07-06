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
export default function ProfileAlerts({ playerId }: { playerId: string }) {
  const { toast } = useToast();
  const [alerts, setAlerts] = useState<AlertModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<AlertModel[]>(`/players/${playerId}/alerts?status=active`)
      .then((a) => { if (!cancelled) setAlerts(a); })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "No se pudieron cargar las alertas.");
        }
      });
    return () => { cancelled = true; };
  }, [playerId]);

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

  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (alerts === null) return <div className={styles.muted}>Cargando alertas…</div>;
  if (alerts.length === 0) {
    return <div className={styles.empty}>Sin alertas activas para este jugador. ✓</div>;
  }
  return (
    <div className={styles.container}>
      <AlertList alerts={alerts} onDismiss={handleDismiss} />
    </div>
  );
}
