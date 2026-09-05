"use client";

import React from "react";
import {
  ShieldCheck,
  TrendingUp,
  Zap,
  HeartPulse,
  Database,
} from "lucide-react";

import type { CCKpis, CCWellnessKpi, Tone, WellnessRoleId } from "./types";
import WellnessRoleTabs, { ROLE_LABEL } from "./WellnessRoleTabs";
import styles from "./KpiStrip.module.css";

interface Chip {
  label: string;
  tone?: Tone;
}

export default function KpiStrip({
  kpis,
  wellnessRoles = ["checkin"],
  wellnessRole = "checkin",
  checkoutWellness,
  onWellnessRoleChange,
}: {
  kpis: CCKpis;
  /** Which forms this category fills; the toggle hides itself below two. */
  wellnessRoles?: WellnessRoleId[];
  wellnessRole?: WellnessRoleId;
  checkoutWellness?: CCWellnessKpi;
  onWellnessRoleChange?: (role: WellnessRoleId) => void;
}) {
  const { disponibilidad: d, riesgo: r, carga: c, completitud: cp } = kpis;
  // The Check-OUT is a different form with its own items (RPE, carga interna),
  // so the card swaps its whole body rather than showing a second number.
  const showCheckout = wellnessRole === "checkout" && checkoutWellness != null;
  const w = showCheckout ? checkoutWellness! : kpis.wellness;

  return (
    <div className={styles.strip}>
      <Card
        icon={<ShieldCheck size={18} aria-hidden="true" />}
        title="Disponibilidad"
        value={d.value}
        chips={d.breakdown.map((b) => ({ label: `${b.n} ${b.label}`, tone: b.tone }))}
        detail={`${d.available} disponibles de ${d.total}`}
      />
      <Card
        icon={<TrendingUp size={18} aria-hidden="true" />}
        title="Riesgo competitivo"
        value={`${r.value} ${r.label}`}
        status={{ text: r.status, tone: r.tone }}
        chips={r.players.map((p) => ({ label: p, tone: "crit" }))}
        detail="Jugadores con alertas críticas activas."
      />
      <Card
        icon={<Zap size={18} aria-hidden="true" />}
        title="Carga del microciclo"
        value={c.value == null ? "—" : c.value.toFixed(2)}
        status={{ text: c.status, tone: c.tone }}
        detail={c.detail}
      />
      <Card
        icon={<HeartPulse size={18} aria-hidden="true" />}
        title={
          wellnessRoles.length > 1
            ? `Wellness plantel · ${ROLE_LABEL[wellnessRole]}`
            : "Wellness plantel"
        }
        value={w.value == null ? "—" : `${w.value}${w.unit ? ` ${w.unit}` : ""}`}
        status={{ text: w.status, tone: w.tone }}
        chips={w.dimensions.map((dim) => ({ label: `${dim.label} ${dim.value}` }))}
        detail={
          // El Check-OUT manda su propio pie: mide carga, no adherencia, y
          // "12/25 respuestas" no dice lo que hay que mirar ahí.
          w.detail ??
          (w.responses != null
            ? `${w.responses}/${w.expected} respuestas`
            : "Sin respuestas registradas.")
        }
        tabs={
          onWellnessRoleChange && (
            <WellnessRoleTabs
              roles={wellnessRoles}
              active={wellnessRole}
              onChange={onWellnessRoleChange}
              label="Wellness del plantel"
            />
          )
        }
      />
      <Card
        icon={<Database size={18} aria-hidden="true" />}
        title="Completitud de datos"
        value={cp.value == null ? "—" : `${cp.value}%`}
        status={{ text: cp.status, tone: cp.tone }}
        chips={cp.breakdown.map((b) => ({
          label: `${b.label} ${b.n}/${b.expected ?? "?"}`,
        }))}
        detail="Cobertura de hoy (GPS + wellness)."
      />
    </div>
  );
}

function Card({
  icon,
  title,
  value,
  status,
  chips,
  detail,
  tabs,
}: {
  icon: React.ReactNode;
  title: string;
  value: string;
  status?: { text: string; tone: Tone };
  chips?: Chip[];
  detail?: string;
  tabs?: React.ReactNode;
}) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <span className={styles.icon}>{icon}</span>
        <span className={styles.headRight}>
          {tabs}
          {status && (
            <span className={`${styles.status} ${styles[`tone_${status.tone}`]}`}>
              {status.text}
            </span>
          )}
        </span>
      </div>
      <div className={styles.title}>{title}</div>
      <div className={styles.value}>{value}</div>
      {chips && chips.length > 0 && (
        <div className={styles.chips}>
          {chips.map((ch, i) => (
            <span
              key={`${ch.label}-${i}`}
              className={`${styles.chip} ${ch.tone ? styles[`tone_${ch.tone}`] : ""}`}
            >
              {ch.label}
            </span>
          ))}
        </div>
      )}
      {detail && <div className={styles.detail}>{detail}</div>}
    </div>
  );
}
