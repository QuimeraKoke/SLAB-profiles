"use client";

import React from "react";

import type {
  TeamMatchSummaryPayload,
  TeamReportWidget,
} from "@/lib/types";
import styles from "./TeamMatchSummary.module.css";

interface Props {
  widget: TeamReportWidget;
}

/**
 * Compact row of stat cards summarizing one match across the roster.
 * Each card shows: SUM (big) + AVG + STD + MIN/MAX + N. Intended as a
 * "team totals" footer in match-scoped GPS layouts.
 */
export default function TeamMatchSummary({ widget }: Props) {
  const data = widget.data as TeamMatchSummaryPayload;

  if (data.empty || (data.cards ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header data={data} title={widget.title} description={widget.description} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin datos suficientes para este reporte."}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.widget}>
      <Header data={data} title={widget.title} description={widget.description} />
      <div className={styles.cardsRow}>
        {data.cards.map((card) => (
          <div key={card.field_key} className={styles.card}>
            <div className={styles.cardLabel}>
              {card.label}
              {card.unit && <span className={styles.cardUnit}> · {card.unit}</span>}
            </div>
            {card.sum === null ? (
              <div className={styles.noData}>—</div>
            ) : (
              <>
                <div className={styles.cardSum}>{formatNumber(card.sum)}</div>
                <div className={styles.cardSubRow}>
                  <Stat label="AVG" value={card.avg} />
                  <Stat label="STD" value={card.std} />
                </div>
                <div className={styles.cardSubRow}>
                  <Stat label="MIN" value={card.min} />
                  <Stat label="MAX" value={card.max} />
                  <Stat label="N" value={card.n} integer />
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Header({
  data, title, description,
}: { data: TeamMatchSummaryPayload; title: string; description: string }) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{title}</h4>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {data.sample_size > 0 && (
        <span className={styles.subtitleTag}>
          N = {data.sample_size}
          {data.per_player_aggregator && data.per_player_aggregator !== "latest"
            ? ` · por jugador: ${data.per_player_aggregator}`
            : ""}
        </span>
      )}
    </header>
  );
}

function Stat({
  label, value, integer,
}: { label: string; value: number | null; integer?: boolean }) {
  if (value === null) return null;
  return (
    <span className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>
        {integer ? value.toString() : formatNumber(value)}
      </span>
    </span>
  );
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}
