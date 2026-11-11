"use client";

import React from "react";
import { CalendarDays, CalendarRange } from "lucide-react";

import { usePeriod } from "@/lib/periodWording";
import styles from "./loadControl.module.css";

/**
 * "DÍA · Dom 15 nov · MD+1" or "SEMANA 46 · 9 – 15 nov" / "PERÍODO · 20 oct – 11 nov":
 * what a card is answering, in the same words on every card. Day cards follow
 * the day strip; period cards add up every day of the period.
 */
export default function ScopeBadge({ kind, text }: { kind: "day" | "period"; text?: string }) {
  const p = usePeriod();
  const label = text ?? (kind === "day" ? p.dayText : p.periodText);
  if (!label) return null;
  const Icon = kind === "day" ? CalendarDays : CalendarRange;
  return (
    <span className={`${styles.scope} ${kind === "day" ? styles.scopeDay : styles.scopePeriod}`}
      title={kind === "day" ? "Muestra el día elegido en la tira de días" : "Suma todos los días del período"}>
      <Icon size={12} aria-hidden="true" />
      <span className={styles.scopeKind}>{kind === "day" ? "Día" : p.range ? "Período" : "Semana"}</span>
      <span>{kind === "day" ? label : label.replace(/^Semana \d+ · /, "")}</span>
    </span>
  );
}
