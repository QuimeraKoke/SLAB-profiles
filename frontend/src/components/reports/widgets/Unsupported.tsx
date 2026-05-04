"use client";

import React from "react";

import type { TeamReportWidget, UnsupportedPayload } from "@/lib/types";
import styles from "./Unsupported.module.css";

interface Props {
  widget: TeamReportWidget;
}

export default function Unsupported({ widget }: Props) {
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
