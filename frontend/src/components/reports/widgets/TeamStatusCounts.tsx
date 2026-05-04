"use client";

import React, { useState } from "react";

import type {
  TeamReportWidget,
  TeamStatusCountsPayload,
} from "@/lib/types";
import styles from "./TeamStatusCounts.module.css";

interface Props {
  widget: TeamReportWidget;
}

export default function TeamStatusCounts({ widget }: Props) {
  const data = widget.data as TeamStatusCountsPayload;
  const [expanded, setExpanded] = useState<string | null>(null);

  if (data.empty || (data.stages ?? []).length === 0) {
    return (
      <div className={styles.widget}>
        <Header widget={widget} />
        <div className={styles.empty}>
          {data.error
            ? `Configuración inválida: ${data.error}`
            : "Sin jugadores en esta categoría."}
        </div>
      </div>
    );
  }

  const total = data.total || 0;
  const availablePct =
    total > 0 ? Math.round((data.available_count / total) * 100) : 0;
  const visibleStages = data.stages.filter((s) => s.count > 0 || s.kind === "available");

  const toggle = (value: string) => {
    setExpanded((prev) => (prev === value ? null : value));
  };

  return (
    <div className={styles.widget}>
      <Header widget={widget} />

      {/* Headline: X / Y disponibles + segmented progress bar */}
      <div className={styles.headline}>
        <div className={styles.bigNumber}>
          <span className={styles.bigNumberValue}>
            {data.available_count}
            <span className={styles.bigNumberDenominator}>/{total}</span>
          </span>
          <span className={styles.bigNumberLabel}>
            jugadores disponibles · {availablePct}%
          </span>
        </div>
        <div className={styles.segmentBar} aria-hidden="true">
          {data.stages
            .filter((s) => s.count > 0)
            .map((s) => {
              const widthPct = total > 0 ? (s.count / total) * 100 : 0;
              return (
                <div
                  key={s.value}
                  className={styles.segment}
                  style={{
                    width: `${widthPct}%`,
                    background: s.color,
                  }}
                  title={`${s.label}: ${s.count}`}
                />
              );
            })}
        </div>
      </div>

      {/* Stage chips — clickable to drill into the player list */}
      <div className={styles.chips}>
        {visibleStages.map((s) => {
          const isOpen = expanded === s.value;
          const disabled = s.players.length === 0;
          return (
            <button
              key={s.value}
              type="button"
              className={`${styles.chip} ${isOpen ? styles.chipActive : ""}`}
              onClick={() => !disabled && toggle(s.value)}
              disabled={disabled}
              aria-expanded={isOpen}
            >
              <span
                className={styles.chipDot}
                style={{ background: s.color }}
                aria-hidden="true"
              />
              <span className={styles.chipLabel}>{s.label}</span>
              <span className={styles.chipCount}>{s.count}</span>
            </button>
          );
        })}
      </div>

      {/* Drilldown: player list for the expanded stage */}
      {expanded && (
        <div className={styles.drilldown}>
          {(() => {
            const stage = data.stages.find((s) => s.value === expanded);
            if (!stage || stage.players.length === 0) {
              return (
                <div className={styles.drilldownEmpty}>Sin jugadores.</div>
              );
            }
            return (
              <ul className={styles.playerList}>
                {stage.players.map((p) => (
                  <li key={p.id} className={styles.playerItem}>
                    <span
                      className={styles.playerDot}
                      style={{ background: stage.color }}
                      aria-hidden="true"
                    />
                    <span>{p.name}</span>
                  </li>
                ))}
              </ul>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function Header({ widget }: { widget: TeamReportWidget }) {
  return (
    <header className={styles.header}>
      <div>
        <h4 className={styles.title}>{widget.title}</h4>
        {widget.description && (
          <p className={styles.description}>{widget.description}</p>
        )}
      </div>
    </header>
  );
}
