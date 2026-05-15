"use client";

import React from "react";

import ActivityLogList from "@/components/dashboards/activity/ActivityLogList";
import type { ActivityLogPayload, DashboardWidget } from "@/lib/types";
import sharedStyles from "./Widget.module.css";

interface Props {
  widget: DashboardWidget;
}

/** Per-player activity log. Backend resolver filters to this widget's
 *  data source and player; we just render the timeline. */
export default function ActivityLog({ widget }: Props) {
  const data = widget.data as ActivityLogPayload;
  const entries = data.entries ?? [];
  return (
    <div className={sharedStyles.widget}>
      <header className={sharedStyles.header}>
        <div>
          <h4 className={sharedStyles.title}>{widget.title}</h4>
          {widget.description && (
            <p className={sharedStyles.description}>{widget.description}</p>
          )}
        </div>
        {entries.length > 0 && (
          <span className={sharedStyles.headerTag}>{entries.length}</span>
        )}
      </header>
      <ActivityLogList
        entries={entries}
        emptyMessage="Sin registros recientes para este jugador."
      />
    </div>
  );
}
