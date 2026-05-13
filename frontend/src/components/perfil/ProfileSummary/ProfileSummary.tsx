"use client";

import React, { useEffect, useState } from "react";
import { Activity, AlertTriangle, Thermometer, Stethoscope, FileHeart } from "lucide-react";

import PlayerAlertsList from "@/components/perfil/PlayerAlertsList/PlayerAlertsList";
import { api, ApiError } from "@/lib/api";
import type { AlertItem } from "@/lib/types";
import styles from "./ProfileSummary.module.css";

interface MatchStats {
  matches_played: number;
  minutes_total: number;
  goals: number;
  assists: number;
  yellow_cards: number;
  red_cards: number;
  rating_avg: number | null;
}

interface PhysicalStats {
  matches_with_gps: number;
  distance_avg_m: number | null;
  max_velocity_avg: number | null;
  hiaa_avg: number | null;
  hmld_avg: number | null;
  acc_avg: number | null;
}

interface RecentInjury {
  title: string;
  stage: string;
  started_at: string | null;
  ended_at: string | null;
  status: "active" | "closed";
}

interface SummaryPayload {
  player_id: string;
  match_stats: MatchStats | null;
  physical: PhysicalStats | null;
  recent_injuries: RecentInjury[];
}

interface Props {
  playerId: string;
}

export default function ProfileSummary({ playerId }: Props) {
  const [data, setData] = useState<SummaryPayload | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setData(null);
      setAlerts(null);
      setError(null);
    });
    api<SummaryPayload>(`/players/${playerId}/summary`)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : "Error al cargar el resumen",
          );
        }
      });
    // Alerts load independently — a 4xx on /alerts shouldn't blank the
    // whole summary. Errors swallow silently; the panel just hides.
    api<AlertItem[]>(`/players/${playerId}/alerts?status=active`)
      .then((list) => {
        if (!cancelled) setAlerts(list);
      })
      .catch(() => {
        if (!cancelled) setAlerts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [playerId]);

  if (error) {
    return (
      <div className={styles.container}>
        <div role="alert" style={{ color: "#b91c1c" }}>{error}</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <AlertsPanel alerts={alerts} />

      <div className={styles.topRow}>
        <MatchStatsCard stats={data?.match_stats ?? null} loading={data === null} />
        <PhysicalCard stats={data?.physical ?? null} loading={data === null} />
        <MedicalCard injuries={data?.recent_injuries ?? []} loading={data === null} />
      </div>

      <div className={`${styles.card} ${styles.bottomRow}`}>
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <FileHeart size={14} />
            EVALUACIÓN PSICOSOCIAL
          </div>
        </div>
        <div className={styles.commentsGrid}>
          <div className={styles.commentSection}>
            <span className={styles.commentTitle}>Comentarios Psicólogo</span>
            <span className={styles.commentText}>Sin notas registradas</span>
          </div>
          <div className={styles.commentSection}>
            <span className={styles.commentTitle}>Comentarios Trabajador Social</span>
            <span className={styles.commentText}>Sin notas registradas</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function MatchStatsCard({
  stats,
  loading,
}: {
  stats: MatchStats | null;
  loading: boolean;
}) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Activity size={14} />
          ESTADÍSTICAS DE JUEGO
        </div>
      </div>
      {loading ? (
        <div className={styles.commentText}>Cargando…</div>
      ) : !stats ? (
        <div className={styles.commentText}>Sin partidos registrados</div>
      ) : (
        <div className={styles.cardList}>
          <Row label="Partidos jugados" value={stats.matches_played} highlight />
          <Row label="Minutos totales" value={stats.minutes_total} suffix=" min" highlight />
          <Row label="Goles" value={stats.goals} />
          <Row label="Asistencias" value={stats.assists} />
          <Row
            label="Amarillas"
            value={stats.yellow_cards}
            color={stats.yellow_cards === 0 ? "#10b981" : undefined}
          />
          <Row
            label="Rojas"
            value={stats.red_cards}
            color={stats.red_cards === 0 ? "#10b981" : "#dc2626"}
          />
          {stats.rating_avg !== null && (
            <Row label="Rating promedio" value={stats.rating_avg.toFixed(1)} />
          )}
        </div>
      )}
    </div>
  );
}

function PhysicalCard({
  stats,
  loading,
}: {
  stats: PhysicalStats | null;
  loading: boolean;
}) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Thermometer size={14} />
          RENDIMIENTO FÍSICO
        </div>
      </div>
      {loading ? (
        <div className={styles.commentText}>Cargando…</div>
      ) : !stats ? (
        <div className={styles.commentText}>Sin datos GPS</div>
      ) : (
        <div className={styles.cardList}>
          <Row label="Partidos con GPS" value={stats.matches_with_gps} highlight />
          {stats.distance_avg_m !== null && (
            <Row
              label="Distancia / partido"
              value={Math.round(stats.distance_avg_m).toLocaleString()}
              suffix=" m"
              highlight
            />
          )}
          {stats.max_velocity_avg !== null && (
            <Row label="V max promedio" value={stats.max_velocity_avg.toFixed(1)} />
          )}
          {stats.hiaa_avg !== null && (
            <Row label="HIAA promedio" value={Math.round(stats.hiaa_avg)} />
          )}
          {stats.hmld_avg !== null && (
            <Row
              label="HMLD promedio"
              value={Math.round(stats.hmld_avg).toLocaleString()}
            />
          )}
          {stats.acc_avg !== null && (
            <Row label="Aceleraciones promedio" value={Math.round(stats.acc_avg)} />
          )}
        </div>
      )}
    </div>
  );
}

function MedicalCard({
  injuries,
  loading,
}: {
  injuries: RecentInjury[];
  loading: boolean;
}) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Stethoscope size={14} />
          REPORTE MÉDICO
        </div>
        {injuries.length > 0 && (
          <div className={styles.cardHeaderRight}>ÚLTIMAS {injuries.length}</div>
        )}
      </div>
      {loading ? (
        <div className={styles.commentText}>Cargando…</div>
      ) : injuries.length === 0 ? (
        <div className={styles.commentText}>Sin lesiones registradas</div>
      ) : (
        <div className={styles.cardList}>
          {injuries.map((inj, i) => (
            <div key={i} className={styles.listItem}>
              <div>
                <span className={styles.listLabel}>{inj.title}</span>
                <span className={styles.listLabelLight}>
                  {[inj.stage, formatStartedAt(inj)].filter(Boolean).join(" · ")}
                </span>
              </div>
              <span
                className={
                  inj.status === "active"
                    ? styles.listValueBadgeRed
                    : styles.listValueBadge
                }
              >
                {inj.status === "active" ? "ACTIVO" : "ALTA"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  label: string;
  value: number | string;
  suffix?: string;
  highlight?: boolean;
  color?: string;
}

function Row({ label, value, suffix, highlight, color }: RowProps) {
  const valueClass = highlight
    ? `${styles.listValue} ${styles.listValueHighlight}`
    : styles.listValue;
  return (
    <div className={styles.listItem}>
      <span className={styles.listLabel}>{label}</span>
      <span className={valueClass} style={color ? { color } : undefined}>
        {value}
        {suffix ?? ""}
      </span>
    </div>
  );
}

function AlertsPanel({ alerts }: { alerts: AlertItem[] | null }) {
  // Render nothing while loading — keeps the layout from flickering with
  // a placeholder card. The other Summary cards already handle their
  // own loading states.
  if (alerts === null) return null;
  if (alerts.length === 0) return null;
  return (
    <div className={`${styles.card} ${styles.alertsCard}`}>
      <div className={styles.cardHeader}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <AlertTriangle size={14} />
          ALERTAS ACTIVAS
        </div>
        <div className={styles.cardHeaderRight}>
          {alerts.length} ACTIVA{alerts.length === 1 ? "" : "S"}
        </div>
      </div>
      <PlayerAlertsList alerts={alerts} limit={6} />
    </div>
  );
}

function formatStartedAt(inj: RecentInjury): string {
  if (!inj.started_at) return "";
  const start = new Date(inj.started_at + "T00:00:00").toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  if (inj.ended_at) {
    const end = new Date(inj.ended_at + "T00:00:00");
    const days = Math.max(
      1,
      Math.round(
        (end.getTime() - new Date(inj.started_at + "T00:00:00").getTime()) /
          (1000 * 60 * 60 * 24),
      ),
    );
    return `${start} – ${days} día${days === 1 ? "" : "s"}`;
  }
  return start;
}
