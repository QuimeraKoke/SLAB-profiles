"use client";

import React from "react";
import Link from "next/link";
import { AlertTriangle, CalendarDays, MapPin, ArrowRight } from "lucide-react";

import type { CCContext } from "./types";
import styles from "./Hero.module.css";

/** Hero band: next match (left) + key pre-match risk with CTA (right).
 *  The "Objetivo de hoy" block from the reference mock is intentionally
 *  omitted — that data isn't modeled yet. */
export default function Hero({ context }: { context: CCContext }) {
  const m = context.next_match;
  const risk = context.pre_match_risk;

  return (
    <section className={styles.hero}>
      <div className={styles.match}>
        <div className={styles.eyebrow}>
          Próximo partido{m?.competition ? ` · ${m.competition}` : ""}
        </div>
        {m ? (
          <>
            <h2 className={styles.title}>{m.title}</h2>
            <div className={styles.metaRow}>
              <span className={styles.meta}>
                <CalendarDays size={14} aria-hidden="true" />
                {formatDate(m.starts_at)}
              </span>
              {m.location && (
                <span className={styles.meta}>
                  <MapPin size={14} aria-hidden="true" />
                  {m.location}
                </span>
              )}
              {m.is_home != null && (
                <span className={styles.meta}>{m.is_home ? "Local" : "Visita"}</span>
              )}
            </div>
            <div className={styles.chips}>
              <span className={styles.mdChip}>{m.md_label}</span>
              <span className={styles.daysChip}>
                {m.days_until === 0
                  ? "Hoy"
                  : `Faltan ${m.days_until} día${m.days_until === 1 ? "" : "s"}`}
              </span>
              {context.last_result && (
                <span className={styles.lastChip}>
                  Último: {context.last_result.title}
                </span>
              )}
            </div>
          </>
        ) : (
          <p className={styles.empty}>No hay próximo partido en el calendario.</p>
        )}
      </div>

      <div className={styles.risk}>
        <div className={styles.riskHead}>
          <AlertTriangle size={14} aria-hidden="true" />
          Riesgo clave pre-partido
        </div>
        <p className={styles.riskHeadline}>{risk.headline}</p>
        {risk.players.length > 0 && (
          <div className={styles.riskPlayers}>
            {risk.players.map((p) => (
              <span key={p} className={styles.riskPlayer}>{p}</span>
            ))}
          </div>
        )}
        <Link href="/reportes/fisico" className={styles.cta}>
          Ver plan del microciclo
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("es-CL", {
    weekday: "long",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
