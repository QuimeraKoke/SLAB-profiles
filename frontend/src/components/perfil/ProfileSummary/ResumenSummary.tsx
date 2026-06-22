"use client";

import React, { useEffect, useState } from "react";
import { Activity, Gauge, Stethoscope, Sparkles } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import DownloadPdfButton from "@/components/reports/DownloadPdfButton";
import type {
  ResumenCardsResponse,
  ResumenGpsCard,
  ResumenMedicalCard,
  ResumenNarrative,
  ResumenNarrativeResponse,
  ResumenSeasonStats,
} from "@/lib/types";
import styles from "./ResumenSummary.module.css";

interface Props {
  playerId: string;
  playerName: string;
}

/**
 * Resumen S-LAB summary block: three season stat cards (estadísticas de juego,
 * rendimiento físico, reporte médico) PLUS the agents' narrative (estado /
 * preocupaciones / recomendaciones). The cards come from a fast endpoint and
 * render immediately; the narrative is a cached LLM call fetched separately so
 * it streams in with its own loading state without blocking the cards.
 */
export default function ResumenSummary({ playerId, playerName }: Props) {
  const [data, setData] = useState<ResumenCardsResponse | null>(null);
  const [narrative, setNarrative] = useState<ResumenNarrative | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(true);
  const [cardsError, setCardsError] = useState<string | null>(null);

  // Fast: stat cards.
  useEffect(() => {
    let cancelled = false;
    api<ResumenCardsResponse>(`/players/${playerId}/resumen-slab`)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (!cancelled) setCardsError(err instanceof ApiError ? err.message : "No se pudo cargar el resumen.");
      });
    return () => {
      cancelled = true;
    };
  }, [playerId]);

  // Slow: agent narrative (cached server-side).
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) setNarrativeLoading(true);
    });
    api<ResumenNarrativeResponse>(`/players/${playerId}/resumen-narrative`)
      .then((d) => {
        if (!cancelled) {
          setNarrative(d.narrative);
          setNarrativeLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setNarrativeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [playerId]);

  if (cardsError) {
    return <div className={styles.error}>{cardsError}</div>;
  }

  return (
    <section className={styles.wrap} aria-label="Resumen S-LAB">
      <header className={styles.header}>
        <h3 className={styles.title}>
          <Sparkles size={15} aria-hidden className={styles.spark} /> Resumen S-LAB
        </h3>
        {data?.number && <span className={styles.number}>#{data.number}</span>}
        <span className={styles.download}>
          <DownloadPdfButton
            endpoint={`/players/${playerId}/triage.docx`}
            filename={`resumen-${playerName}.docx`.replace(/\s+/g, "_")}
          />
        </span>
      </header>

      {/* Agent narrative — estado / preocupaciones / recomendaciones. */}
      <NarrativeBlock loading={narrativeLoading} narrative={narrative} />

      {/* Three season stat cards. */}
      <div className={styles.cards}>
        {data ? (
          <>
            <StatsCard stats={data.cards.estadisticas} />
            <GpsCard gps={data.cards.rendimiento_fisico} />
            <MedicalCard medico={data.cards.reporte_medico} />
          </>
        ) : (
          <>
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}
      </div>
    </section>
  );
}

function NarrativeBlock({
  loading,
  narrative,
}: {
  loading: boolean;
  narrative: ResumenNarrative | null;
}) {
  if (loading) {
    return (
      <div className={styles.narrative}>
        <div className={styles.narrLoading}>
          <Sparkles size={14} aria-hidden className={styles.sparkPulse} />
          Generando análisis S-LAB…
        </div>
      </div>
    );
  }
  if (!narrative || (!narrative.resumen && !narrative.hallazgos?.length && !narrative.objetivos?.length)) {
    return null;
  }
  return (
    <div className={styles.narrative}>
      {narrative.resumen && (
        <div className={styles.narrSection}>
          <span className={styles.narrLabel}>Estado</span>
          <p className={styles.narrText}>{narrative.resumen}</p>
        </div>
      )}
      {narrative.hallazgos?.length > 0 && (
        <div className={styles.narrSection}>
          <span className={styles.narrLabel}>Preocupaciones</span>
          <ul className={styles.narrList}>
            {narrative.hallazgos.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      )}
      {narrative.objetivos?.length > 0 && (
        <div className={styles.narrSection}>
          <span className={styles.narrLabel}>Recomendaciones</span>
          <ul className={styles.recList}>
            {narrative.objetivos.map((o, i) => (
              <li key={i} className={styles.rec}>
                <span className={styles.recFoco}>{o.foco}</span>
                {o.estado_actual && <span className={styles.recState}>{o.estado_actual}</span>}
                {o.estrategia && <span className={styles.recStrategy}>→ {o.estrategia}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StatsCard({ stats }: { stats: ResumenSeasonStats }) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <Activity size={14} aria-hidden /> Estadísticas de juego
      </div>
      <Row label="Partidos jugados" value={stats.partidos_jugados} accent />
      <Row label="Minutos totales" value={`${num(stats.minutos_totales)} min`} accent />
      <Row label="Goles" value={stats.goles} />
      <Row label="Asistencias" value={stats.asistencias ?? "—"} />
      <Row label="Amarillas" value={stats.amarillas} />
      <Row label="Rojas" value={stats.rojas} danger={stats.rojas > 0} />
    </div>
  );
}

function GpsCard({ gps }: { gps: ResumenGpsCard }) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <Gauge size={14} aria-hidden /> Rendimiento físico
      </div>
      <Row label="Partidos con GPS" value={gps.partidos_con_gps} accent />
      <Row label="Distancia / partido" value={metersOr(gps.distancia_promedio)} accent />
      <Row label="V max promedio" value={oneDecimalOr(gps.v_max_promedio)} />
      <Row label="HIAA promedio" value={intOr(gps.hiaa_promedio)} />
      <Row label="HMLD promedio" value={metersOr(gps.hmld_promedio)} />
      <Row label="Aceleraciones promedio" value={intOr(gps.aceleraciones_promedio)} />
    </div>
  );
}

function MedicalCard({ medico }: { medico: ResumenMedicalCard }) {
  const tone =
    medico.player_status === "available"
      ? styles.statusOk
      : medico.player_status === "injured"
        ? styles.statusBad
        : styles.statusWarn;
  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <Stethoscope size={14} aria-hidden /> Reporte médico
        <span className={`${styles.statusChip} ${tone}`}>{medico.player_status_label}</span>
      </div>
      {medico.episodes.length === 0 ? (
        <p className={styles.medEmpty}>Sin episodios registrados.</p>
      ) : (
        <ul className={styles.episodes}>
          {medico.episodes.map((e) => (
            <li key={e.id} className={styles.episode}>
              <div className={styles.epTop}>
                <span className={styles.epTitle}>{e.title}</span>
                {e.stage && <span className={styles.epStage}>{e.stage}</span>}
              </div>
              <span className={styles.epMeta}>
                {e.status === "closed" ? "Cerrado" : "Abierto"}
                {e.started_at ? ` · ${shortDate(e.started_at)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  accent,
  danger,
}: {
  label: string;
  value: React.ReactNode;
  accent?: boolean;
  danger?: boolean;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span
        className={`${styles.rowValue} ${accent ? styles.rowAccent : ""} ${danger ? styles.rowDanger : ""}`}
      >
        {value}
      </span>
    </div>
  );
}

function CardSkeleton() {
  return <div className={`${styles.card} ${styles.skeleton}`} aria-hidden />;
}

// ─── format helpers ──────────────────────────────────────────────────────

function num(n: number): string {
  return n.toLocaleString("es-CL");
}
function intOr(n: number | null): string {
  return n == null ? "—" : Math.round(n).toLocaleString("es-CL");
}
function metersOr(n: number | null): string {
  return n == null ? "—" : `${Math.round(n).toLocaleString("es-CL")} m`;
}
function oneDecimalOr(n: number | null): string {
  return n == null ? "—" : n.toFixed(1);
}
function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("es-CL", { day: "numeric", month: "short", year: "numeric" });
}
