"use client";

/**
 * "Descartar" for an alert, inside the Daily — the same action as the
 * profile's Alertas tab and the navbar bell (`PATCH /alerts/{id}` →
 * dismissed), so an alert dismissed in the meeting is gone everywhere.
 *
 * Shown only to staff with `goals.change_alert`, the permission the endpoint
 * enforces; without it the button would just fail. No confirmation, like the
 * other two places: dismissing is the routine end of an alert, and the
 * alert stays in the player's Historial.
 */

import React, { useState } from "react";

import { useToast } from "@/components/ui/Toast/Toast";
import { api, ApiError } from "@/lib/api";

import styles from "./DismissAlertButton.module.css";

export default function DismissAlertButton({
  alertId,
  message,
  onDismissed,
}: {
  alertId: string;
  message: string;
  onDismissed: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const descartar = async () => {
    setBusy(true);
    try {
      await api(`/alerts/${alertId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "dismissed" }),
      });
      toast.success("Alerta descartada.");
      onDismissed();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo descartar la alerta.");
      setBusy(false);
    }
  };

  return (
    <button type="button" className={styles.btn} onClick={descartar} disabled={busy}
      aria-label={`Descartar alerta: ${message}`}>
      {busy ? "Descartando…" : "Descartar"}
    </button>
  );
}
