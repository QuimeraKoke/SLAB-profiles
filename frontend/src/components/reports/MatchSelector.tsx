"use client";

import React from "react";
import { ChevronDown, Trophy, MapPin, Calendar } from "lucide-react";

import type { TeamMatchSelectorConfig } from "@/lib/types";
import styles from "./MatchSelector.module.css";

interface Props {
  config: TeamMatchSelectorConfig;
  onChange: (eventId: string | null) => void;
}

/**
 * Hero-sized match selector. Renders only when the layout opts in via
 * `match_selector_config.enabled` (set per-layout in Django admin).
 *
 * The currently-selected match shows above the dropdown as the "headline"
 * — title, date, venue — so the page makes it obvious which match the
 * report is showing without forcing the user to read the dropdown text.
 */
export default function MatchSelector({ config, onChange }: Props) {
  const { options, selected_id, label, required } = config;
  const selected = options.find((o) => o.id === selected_id) ?? null;

  if (options.length === 0) {
    return (
      <div className={styles.empty}>
        <Trophy size={18} aria-hidden="true" />
        <span>Sin partidos cargados para esta categoría.</span>
      </div>
    );
  }

  return (
    <div className={styles.hero}>
      <div className={styles.headline}>
        <Trophy size={20} aria-hidden="true" />
        <div className={styles.headlineText}>
          <span className={styles.eyebrow}>{label}</span>
          <span className={styles.title}>
            {selected ? selected.title : "—"}
          </span>
          {selected && (
            <span className={styles.meta}>
              <span className={styles.metaItem}>
                <Calendar size={12} aria-hidden="true" />
                {formatDate(selected.starts_at)}
              </span>
              {selected.location && (
                <span className={styles.metaItem}>
                  <MapPin size={12} aria-hidden="true" />
                  {selected.location}
                </span>
              )}
            </span>
          )}
        </div>
      </div>
      <label className={styles.pickerWrap}>
        <span className={styles.pickerLabel}>Cambiar</span>
        <div className={styles.pickerInner}>
          <select
            className={styles.picker}
            value={selected_id ?? ""}
            onChange={(e) => onChange(e.target.value || null)}
            aria-label={`${label} — seleccionar`}
          >
            {!required && <option value="">— Sin filtro —</option>}
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {formatDate(o.starts_at)} · {o.title}
              </option>
            ))}
          </select>
          <ChevronDown size={16} aria-hidden="true" className={styles.chevron} />
        </div>
      </label>
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}
