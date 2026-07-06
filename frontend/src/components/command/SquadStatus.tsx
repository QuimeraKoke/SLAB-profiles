"use client";

import React from "react";
import Link from "next/link";
import { Users, ArrowRight } from "lucide-react";

import type { CCSquad } from "./types";
import styles from "./SquadStatus.module.css";

const STATUS_DOT: Record<string, string> = {
  available: styles.dotOk,
  reintegration: styles.dotInfo,
  recovery: styles.dotWarn,
  injured: styles.dotCrit,
};

export default function SquadStatus({ squad }: { squad: CCSquad }) {
  const c = squad.counts;
  const counts: { label: string; n: number; dot: string }[] = [
    { label: "Disponibles", n: c.disponibles, dot: styles.dotOk },
    { label: "Riesgo alto", n: c.riesgo_alto, dot: styles.dotCrit },
    { label: "Return to Train", n: c.reintegracion, dot: styles.dotInfo },
    { label: "Lesionados", n: c.lesionados, dot: styles.dotCrit },
    { label: "Recuperación", n: c.recuperacion, dot: styles.dotWarn },
  ];

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <Users size={15} aria-hidden="true" />
        <span>Estado del plantel</span>
      </div>

      <div className={styles.counts}>
        {counts.map((row) => (
          <div key={row.label} className={styles.countRow}>
            <span className={`${styles.dot} ${row.dot}`} />
            <span className={styles.countLabel}>{row.label}</span>
            <span className={styles.countN}>{row.n}</span>
          </div>
        ))}
      </div>

      {squad.por_linea.length > 0 && (
        <>
          <div className={styles.subhead}>Disponibilidad por línea</div>
          <div className={styles.lines}>
            {squad.por_linea.map((l) => (
              <div key={l.linea} className={styles.lineRow}>
                <span className={styles.lineLabel}>{l.linea}</span>
                <span className={styles.bar}>
                  <span
                    className={`${styles.barFill} ${barTone(l.pct)}`}
                    style={{ width: `${l.pct}%` }}
                  />
                </span>
                <span className={styles.linePct}>{l.pct}%</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className={styles.players}>
        {squad.players.map((p) => (
          <Link key={p.id} href={`/perfil/${p.id}`} className={styles.player}>
            <span className={styles.avatar}>{p.initials}</span>
            <span className={styles.playerName}>{p.name}</span>
            <span className={styles.playerStatus}>
              <span className={`${styles.dot} ${STATUS_DOT[p.status] ?? styles.dotMuted}`} />
              {p.status_label}
              {p.at_risk && <span className={styles.riskFlag}>riesgo</span>}
            </span>
          </Link>
        ))}
      </div>

      <Link href="/equipo" className={styles.footerLink}>
        Ver plantel completo
        <ArrowRight size={14} aria-hidden="true" />
      </Link>
    </div>
  );
}

function barTone(pct: number): string {
  if (pct >= 90) return styles.barOk;
  if (pct >= 70) return styles.barWarn;
  return styles.barCrit;
}
