"use client";

import React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowUpRight, CalendarClock, ClipboardList, MessageSquarePlus } from "lucide-react";

import type { DailyLesionado, GpsCompare } from "./types";
import styles from "./LesionadoCard.module.css";

const nf = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });

function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "short",
  });
}

const STATUS_TONE: Record<string, string> = {
  injured: styles.stageCrit,
  recovery: styles.stageWarn,
  reintegration: styles.stageInfo,
};

export default function LesionadoCard({
  row,
  onAddNote,
  onAddPlan,
  canNote,
}: {
  row: DailyLesionado;
  onAddNote: (playerId: string) => void;
  onAddPlan: (playerId: string) => void;
  canNote: boolean;
}) {
  const ep = row.episode;
  return (
    <article className={styles.card}>
      <header className={styles.head}>
        <div className={styles.identity}>
          {row.photo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={row.photo} alt="" className={styles.photo} />
          ) : (
            <span className={styles.initials}>{row.initials}</span>
          )}
          <div>
            <Link href={`/perfil/${row.player_id}`} className={styles.name}>
              {row.name}
              <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
            <div className={styles.meta}>
              {row.position}
              {ep && (
                <>
                  {" · "}
                  <strong>{ep.title}</strong>
                  {ep.severity ? ` · ${ep.severity}` : ""}
                </>
              )}
            </div>
          </div>
        </div>
        <span className={`${styles.stage} ${STATUS_TONE[ep?.stage ?? row.status] ?? ""}`}>
          {ep?.stage_label ?? row.status_label}
        </span>
      </header>

      {ep && (
        <div className={styles.timeline}>
          <span className={styles.dayCount}>
            Día <strong>{ep.days_out}</strong>
          </span>
          <span className={styles.timelineItem}>desde el {fmtDay(ep.diagnosed_at)}</span>
          <span className={styles.timelineItem}>
            <CalendarClock size={13} aria-hidden="true" />
            {ep.expected_return
              ? ep.days_to_return != null && ep.days_to_return >= 0
                ? `Retorno estimado: ${fmtDay(ep.expected_return)} (en ${ep.days_to_return} días)`
                : `Retorno estimado: ${fmtDay(ep.expected_return)} (vencido)`
              : "Sin retorno estimado"}
          </span>
        </div>
      )}

      {ep?.plan && <p className={styles.plan}>{ep.plan}</p>}

      <GpsCompareBlock compare={row.gps_compare} />

      {row.alerts.length > 0 && (
        <ul className={styles.alerts}>
          {row.alerts.map((a, i) => (
            <li key={i} className={a.severity === "critical" ? styles.alertCrit : styles.alertWarn}>
              <AlertTriangle size={13} aria-hidden="true" />
              {a.message}
            </li>
          ))}
        </ul>
      )}

      <footer className={styles.foot}>
        <div className={styles.notes}>
          {row.notes.length === 0 ? (
            <span className={styles.noNotes}>Sin notas para hoy.</span>
          ) : (
            row.notes.map((n) => (
              <div key={n.id} className={styles.note}>
                <span className={styles.noteDept}>{n.department?.name ?? "General"}</span>
                <span className={styles.noteText}>{n.text}</span>
              </div>
            ))
          )}
        </div>
        {canNote && (
          <span className={styles.noteBtns}>
            <button className={styles.noteBtn} onClick={() => onAddNote(row.player_id)}>
              <MessageSquarePlus size={14} aria-hidden="true" />
              Nota
            </button>
            <button className={styles.noteBtn} onClick={() => onAddPlan(row.player_id)}>
              <ClipboardList size={14} aria-hidden="true" />
              Plan
            </button>
          </span>
        )}
      </footer>
    </article>
  );
}

// "Hoy vs. cuando estaba OK" — per-session training GPS, current week of
// work vs. the healthy pre-injury baseline. Meter toward 100% (= habitual).
function GpsCompareBlock({ compare }: { compare: GpsCompare | null }) {
  if (!compare) {
    return <p className={styles.noGps}>Sin datos GPS para comparar.</p>;
  }
  const withCurrent = compare.metrics.some((m) => m.current !== null);
  return (
    <div className={styles.gps}>
      <div className={styles.gpsHead}>
        <span>GPS · actual vs. habitual pre-lesión</span>
        <span className={styles.gpsWindow}>
          {withCurrent && compare.current_to
            ? `semana al ${fmtDay(compare.current_to)} vs. ${compare.baseline_days / 7} sem. previas a la lesión`
            : "sin trabajo de cancha desde la lesión"}
        </span>
      </div>
      {withCurrent && (
        <div className={styles.gpsRows}>
          {compare.metrics.map((m) => (
            <div key={m.key} className={styles.gpsRow}>
              <span className={styles.gpsLabel}>{m.label}</span>
              <span className={styles.gpsValue}>
                {m.current !== null ? `${nf.format(m.current)} ${m.unit}` : "—"}
                <span className={styles.gpsBaseline}>
                  {" "}/ {m.baseline !== null ? nf.format(m.baseline) : "—"}
                </span>
              </span>
              <Meter pct={m.pct} />
              <span className={styles.gpsPct}>{m.pct !== null ? `${m.pct}%` : "—"}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Fill toward the 100% tick (the habitual value); capped at 130% so an
// overshoot stays readable. Single accent hue — the % text carries the value.
const METER_MAX = 130;

function Meter({ pct }: { pct: number | null }) {
  if (pct === null) return <span className={styles.meterEmpty} aria-hidden="true" />;
  const width = Math.min(pct, METER_MAX) / METER_MAX * 100;
  return (
    <span className={styles.meter} aria-hidden="true">
      <span className={styles.meterFill} style={{ width: `${width}%` }} />
      <span className={styles.meterTick} style={{ left: `${(100 / METER_MAX) * 100}%` }} />
    </span>
  );
}
