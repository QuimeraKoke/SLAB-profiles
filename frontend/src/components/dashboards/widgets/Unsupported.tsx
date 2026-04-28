"use client";

import React from "react";

import type { DashboardWidget, UnsupportedPayload } from "@/lib/types";
import styles from "./Widget.module.css";

interface UnsupportedProps {
  widget: DashboardWidget;
}

export default function Unsupported({ widget }: UnsupportedProps) {
  const data = widget.data as UnsupportedPayload;
  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
      </header>
      <div className={styles.unsupported}>
        Visualización <code>{widget.chart_type}</code> aún no implementada.
        {data?.reason && <div className={styles.unsupportedReason}>{data.reason}</div>}
      </div>
    </div>
  );
}
