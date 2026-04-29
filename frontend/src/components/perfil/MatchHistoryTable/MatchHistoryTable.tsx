"use client";

import React, { useMemo } from "react";
import Link from "next/link";

import type { ExamResult, ExamTemplate } from "@/lib/types";
import styles from "./MatchHistoryTable.module.css";

interface MatchHistoryTableProps {
  template: ExamTemplate;
  results: ExamResult[];
  playerId: string;
}

/**
 * Match-performance history per player. Renders one row per result that's
 * linked to a match Event, pulling opponent + score from `event.metadata`
 * and per-player stats from `result.result_data`.
 */
export default function MatchHistoryTable({
  template,
  results,
  playerId,
}: MatchHistoryTableProps) {
  const linked = useMemo(
    () =>
      results
        .filter((r) => r.event)
        .sort(
          (a, b) =>
            new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime(),
        ),
    [results],
  );
  const orphans = useMemo(
    () => results.filter((r) => !r.event).length,
    [results],
  );

  const totals = useMemo(() => {
    const t = {
      matches: linked.length,
      starts: 0,
      minutes: 0,
      goals: 0,
      assists: 0,
      yellows: 0,
      reds: 0,
    };
    for (const r of linked) {
      const d = r.result_data;
      if (d.started_eleven === true) t.starts += 1;
      t.minutes += numeric(d.minutes_played);
      t.goals += numeric(d.goals);
      t.assists += numeric(d.assists);
      t.yellows += numeric(d.yellow_cards);
      if (d.red_card === true) t.reds += 1;
    }
    return t;
  }, [linked]);

  const addHref = `/perfil/${playerId}/registrar/${template.id}?tab=tactico`;

  return (
    <section className={styles.wrapper}>
      <header className={styles.header}>
        <h3 className={styles.title}>{template.name}</h3>
        <Link href={addHref} className={styles.addBtn}>
          + Agregar
        </Link>
      </header>

      <div className={styles.totalsRow}>
        <Stat label="Partidos" value={totals.matches} />
        <Stat label="Titular" value={totals.starts} />
        <Stat label="Minutos" value={totals.minutes} />
        <Stat label="Goles" value={totals.goals} tone={totals.goals > 0 ? "good" : undefined} />
        <Stat label="Asistencias" value={totals.assists} />
        <Stat label="Amarillas" value={totals.yellows} tone={totals.yellows > 0 ? "warn" : undefined} />
        <Stat label="Rojas" value={totals.reds} tone={totals.reds > 0 ? "bad" : undefined} />
      </div>

      {linked.length === 0 ? (
        <div className={styles.empty}>
          {orphans > 0
            ? "Hay registros sin partido asociado. Edítalos para vincularlos a un partido del calendario."
            : "Aún no hay rendimientos por partido cargados. Crea partidos en Configuraciones → Partidos y luego usa “+ Agregar” para registrar el rendimiento."}
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Partido</th>
                <th>Resultado</th>
                <th className={styles.numericCell}>Min</th>
                <th>Pos.</th>
                <th className={styles.numericCell}>G</th>
                <th className={styles.numericCell}>A</th>
                <th className={styles.numericCell}>TA</th>
                <th className={styles.numericCell}>TR</th>
                <th className={styles.numericCell}>Nota</th>
              </tr>
            </thead>
            <tbody>
              {linked.map((r) => (
                <MatchRow key={r.id} result={r} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function MatchRow({ result }: { result: ExamResult }) {
  const event = result.event!;
  const meta = (event.metadata ?? {}) as {
    opponent?: string;
    is_home?: boolean;
    competition?: string;
    score?: { home?: number | null; away?: number | null };
  };

  const dateLabel = new Date(event.starts_at).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });

  const score = meta.score;
  const scoreLabel =
    score && (score.home != null || score.away != null)
      ? meta.is_home
        ? `${score.home ?? "-"} – ${score.away ?? "-"}`
        : `${score.away ?? "-"} – ${score.home ?? "-"}`
      : "—";
  const scoreOutcome = computeOutcome(score, meta.is_home);

  const d = result.result_data;
  const startedTitular = d.started_eleven === true;
  const redCard = d.red_card === true;

  return (
    <tr>
      <td className={styles.dim}>{dateLabel}</td>
      <td>
        <span className={styles.matchTitle}>
          {meta.is_home === false ? "@" : ""} {meta.opponent || event.title}
        </span>
        {meta.competition && (
          <div className={styles.matchSub}>{meta.competition}</div>
        )}
      </td>
      <td>
        <span className={`${styles.scorePill} ${styles[`outcome_${scoreOutcome}`]}`}>
          {scoreLabel}
        </span>
      </td>
      <td className={styles.numericCell}>
        {fmtNum(d.minutes_played)}
        {startedTitular && <span className={styles.starterDot} title="Titular" />}
      </td>
      <td className={styles.dim}>{fmtStr(d.position_played)}</td>
      <td className={styles.numericCell}>{fmtNum(d.goals) || "—"}</td>
      <td className={styles.numericCell}>{fmtNum(d.assists) || "—"}</td>
      <td className={styles.numericCell}>{fmtNum(d.yellow_cards) || "—"}</td>
      <td className={styles.numericCell}>{redCard ? "1" : "—"}</td>
      <td className={styles.numericCell}>{fmtNum(d.rating) || "—"}</td>
    </tr>
  );
}

function Stat({
  label, value, tone,
}: { label: string; value: number; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={`${styles.statValue} ${tone ? styles[`tone_${tone}`] : ""}`}>
        {value}
      </span>
    </div>
  );
}

function numeric(v: unknown): number {
  if (typeof v === "number") return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function fmtNum(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : v.toFixed(1);
  }
  return String(v);
}

function fmtStr(v: unknown): string {
  if (typeof v === "string" && v) return v;
  return "—";
}

function computeOutcome(
  score: { home?: number | null; away?: number | null } | undefined,
  isHome: boolean | undefined,
): "win" | "draw" | "loss" | "neutral" {
  if (!score || score.home == null || score.away == null) return "neutral";
  const ours = isHome === false ? score.away : score.home;
  const theirs = isHome === false ? score.home : score.away;
  if (typeof ours !== "number" || typeof theirs !== "number") return "neutral";
  if (ours > theirs) return "win";
  if (ours < theirs) return "loss";
  return "draw";
}
