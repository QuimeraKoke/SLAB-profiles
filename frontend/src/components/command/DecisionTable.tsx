"use client";

import React from "react";
import Link from "next/link";
import { ListChecks } from "lucide-react";

import type { CCDecision } from "./types";
import styles from "./DecisionTable.module.css";

const PRIORITY_TONE: Record<CCDecision["priority"], string> = {
  alta: styles.prioAlta,
  media: styles.prioMedia,
  baja: styles.prioBaja,
};

export default function DecisionTable({ decisions }: { decisions: CCDecision[] }) {
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <ListChecks size={16} aria-hidden="true" />
        <div>
          <div className={styles.title}>Jugadores que requieren decisión</div>
          <div className={styles.subtitle}>Triaje accionable · ordenado por prioridad</div>
        </div>
      </div>

      {decisions.length === 0 ? (
        <p className={styles.empty}>Sin jugadores que requieran una decisión hoy.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Jugador</th>
              <th>Estado</th>
              <th>Señal</th>
              <th className={styles.right}>Prioridad</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d.player_id}>
                <td>
                  <Link href={`/perfil/${d.player_id}`} className={styles.player}>
                    <span className={styles.avatar}>{d.initials}</span>
                    <span className={styles.playerName}>{d.player}</span>
                  </Link>
                </td>
                <td><span className={styles.statusChip}>{d.status_label}</span></td>
                <td className={styles.signal}>{d.signal}</td>
                <td className={styles.right}>
                  <span className={`${styles.prio} ${PRIORITY_TONE[d.priority]}`}>
                    {d.priority}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
