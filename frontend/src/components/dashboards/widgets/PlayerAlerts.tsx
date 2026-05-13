"use client";

import React from "react";

import type { DashboardWidget, PlayerAlertsPayload } from "@/lib/types";

import PlayerAlertsList from "@/components/perfil/PlayerAlertsList/PlayerAlertsList";
import sharedStyles from "./Widget.module.css";

interface Props {
  widget: DashboardWidget;
}

/**
 * Per-player alerts widget — embedded inside a Department layout.
 * Filtered server-side to alerts whose source's template lives in the
 * widget's department. The list itself is rendered by the shared
 * `PlayerAlertsList`, also used by the profile Resumen panel.
 */
export default function PlayerAlerts({ widget }: Props) {
  const data = widget.data as PlayerAlertsPayload;
  const alerts = data.alerts ?? [];
  return (
    <div className={sharedStyles.widget}>
      <header className={sharedStyles.header}>
        <div>
          <h4 className={sharedStyles.title}>{widget.title}</h4>
          {widget.description && (
            <p className={sharedStyles.description}>{widget.description}</p>
          )}
        </div>
        {alerts.length > 0 && (
          <span className={sharedStyles.headerTag}>
            {alerts.length} activa{alerts.length === 1 ? "" : "s"}
          </span>
        )}
      </header>
      <PlayerAlertsList
        alerts={alerts}
        emptyMessage="Sin alertas activas en este departamento"
      />
    </div>
  );
}
