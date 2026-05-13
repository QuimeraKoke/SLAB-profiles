"use client";

import React from "react";

import type {
  DashboardWidget,
  GoalCardPayload,
  GoalOperator,
} from "@/lib/types";

import styles from "./GoalCard.module.css";
import sharedStyles from "./Widget.module.css";

interface Props {
  widget: DashboardWidget;
}

const OPERATOR_LABELS: Record<GoalOperator, string> = {
  "<=": "≤", "<": "<", "==": "=", ">=": "≥", ">": ">",
};

/** Goal vs. current cards for a single player. Renders one card per
 *  active goal scoped to the layout's department (or to the widget's
 *  configured data source when present). */
export default function GoalCard({ widget }: Props) {
  const data = widget.data as GoalCardPayload;
  const cards = data.cards ?? [];

  if (data.empty || cards.length === 0) {
    return (
      <div className={sharedStyles.widget}>
        <header className={sharedStyles.header}>
          <h4 className={sharedStyles.title}>{widget.title}</h4>
        </header>
        <div className={sharedStyles.empty}>
          No hay objetivos activos en este departamento.
        </div>
      </div>
    );
  }

  return (
    <div className={sharedStyles.widget}>
      <header className={sharedStyles.header}>
        <h4 className={sharedStyles.title}>{widget.title}</h4>
      </header>
      {widget.description && (
        <p className={sharedStyles.description}>{widget.description}</p>
      )}

      <div className={styles.grid}>
        {cards.map((card) => {
          const achieved = card.progress?.achieved === true;
          const noReading = card.current_value === null;
          const overdue = card.days_to_due < 0;
          const statusBadge = computeBadge({ achieved, noReading, overdue });
          const unit = card.field_unit ? ` ${card.field_unit}` : "";
          const distance = card.progress?.distance;
          const directionArrow =
            distance == null ? "" : distance > 0 ? "▲" : distance < 0 ? "▼" : "•";
          return (
            <article
              key={card.id}
              className={`${styles.card} ${statusBadge.cardClass(styles)}`}
            >
              <header className={styles.cardHeader}>
                <span className={styles.cardLabel}>{card.field_label}</span>
                <span className={`${styles.badge} ${statusBadge.badgeClass(styles)}`}>
                  {statusBadge.label}
                </span>
              </header>

              <div className={styles.metricsRow}>
                <Metric label="Actual" value={card.current_value} unit={unit} />
                <Metric
                  label={`Objetivo (${OPERATOR_LABELS[card.operator]})`}
                  value={card.target_value}
                  unit={unit}
                />
              </div>

              {distance != null && (
                <div className={styles.deltaRow}>
                  <span className={`${styles.deltaArrow} ${statusBadge.deltaClass(styles)}`}>
                    {directionArrow}
                  </span>
                  <span className={styles.deltaValue}>
                    {formatNumber(Math.abs(distance))}{unit}
                  </span>
                  {card.progress?.distance_pct != null && (
                    <span className={styles.deltaPct}>
                      ({formatPct(card.progress.distance_pct)})
                    </span>
                  )}
                </div>
              )}

              <footer className={styles.footer}>
                <span className={styles.dueDate}>
                  Vence: {formatDate(card.due_date)}
                  {card.days_to_due >= 0
                    ? ` · en ${card.days_to_due} días`
                    : ` · hace ${Math.abs(card.days_to_due)} días`}
                </span>
                {card.current_recorded_at && (
                  <span className={styles.measuredAt}>
                    Última toma: {formatDate(card.current_recorded_at)}
                  </span>
                )}
              </footer>
            </article>
          );
        })}
      </div>
    </div>
  );
}

interface BadgeSpec {
  label: string;
  cardClass: (s: Record<string, string>) => string;
  badgeClass: (s: Record<string, string>) => string;
  deltaClass: (s: Record<string, string>) => string;
}

function computeBadge(args: {
  achieved: boolean;
  noReading: boolean;
  overdue: boolean;
}): BadgeSpec {
  if (args.noReading) {
    return {
      label: "Sin medición",
      cardClass: (s) => s.cardNeutral,
      badgeClass: (s) => s.badgeNeutral,
      deltaClass: (s) => s.deltaNeutral,
    };
  }
  if (args.achieved) {
    return {
      label: "✓ Cumplido",
      cardClass: (s) => s.cardOk,
      badgeClass: (s) => s.badgeOk,
      deltaClass: (s) => s.deltaOk,
    };
  }
  if (args.overdue) {
    return {
      label: "⚠ Vencido",
      cardClass: (s) => s.cardOverdue,
      badgeClass: (s) => s.badgeOverdue,
      deltaClass: (s) => s.deltaOverdue,
    };
  }
  return {
    label: "En curso",
    cardClass: (s) => s.cardInProgress,
    badgeClass: (s) => s.badgeInProgress,
    deltaClass: (s) => s.deltaInProgress,
  };
}

function Metric({
  label,
  value,
  unit,
}: {
  label: string;
  value: number | null;
  unit: string;
}) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={styles.metricValue}>
        {value == null ? "—" : `${formatNumber(value)}${unit}`}
      </span>
    </div>
  );
}

function formatNumber(n: number): string {
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2).replace(/\.?0+$/, "");
}

function formatPct(p: number): string {
  const sign = p > 0 ? "+" : "";
  return `${sign}${p.toFixed(1)}%`;
}

function formatDate(iso: string): string {
  return new Date(iso + (iso.includes("T") ? "" : "T00:00:00")).toLocaleDateString(
    undefined,
    { day: "2-digit", month: "short", year: "numeric" },
  );
}
