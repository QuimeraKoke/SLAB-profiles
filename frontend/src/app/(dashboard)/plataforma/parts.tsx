"use client";

import React from "react";

import type { PlatformCategoryIn } from "@/lib/types";
import styles from "./plataforma.module.css";

export function ClubLogo({ name, url, large = false }: {
  name: string;
  url: string | null;
  large?: boolean;
}) {
  const cls = large ? styles.logoLarge : styles.logo;
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element -- signed storage URL
    return <img src={url} alt="" className={cls} />;
  }
  return (
    <span className={`${cls} ${styles.logoFallback}`} aria-hidden>
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}

export type CategoryDraft = { name: string; cohort_year: string; is_senior: boolean };

export function toCategoryIn(c: CategoryDraft): PlatformCategoryIn {
  const year = Number.parseInt(c.cohort_year, 10);
  return {
    name: c.name.trim(),
    cohort_year: Number.isFinite(year) ? year : null,
    is_senior: c.is_senior,
  };
}

/** Editable list of categories for "Nuevo club": name, cohort year (age
 *  groups only) and which one is the first team — at most one. */
export function CategoryRows({ rows, onChange }: {
  rows: CategoryDraft[];
  onChange: (rows: CategoryDraft[]) => void;
}) {
  const set = (i: number, patch: Partial<CategoryDraft>) => {
    onChange(rows.map((r, j) => {
      if (j === i) return { ...r, ...patch };
      // One first team per club.
      return patch.is_senior ? { ...r, is_senior: false } : r;
    }));
  };
  return (
    <>
      {rows.map((r, i) => (
        <div key={i} className={styles.catRow}>
          <label className={styles.field}>
            {i === 0 && <span className={styles.label}>Nombre</span>}
            <input
              value={r.name}
              onChange={(e) => set(i, { name: e.target.value })}
              placeholder="Ej: Serie 2012"
              aria-label={`Nombre de la categoría ${i + 1}`}
            />
          </label>
          <label className={styles.field}>
            {i === 0 && <span className={styles.label}>Año cohorte</span>}
            <input
              inputMode="numeric"
              value={r.cohort_year}
              onChange={(e) => set(i, { cohort_year: e.target.value.replace(/\D/g, "").slice(0, 4) })}
              placeholder="Ej: 2012"
              aria-label={`Año de nacimiento de la categoría ${i + 1}`}
            />
          </label>
          <label className={styles.inlineCheck}>
            <input
              type="checkbox"
              checked={r.is_senior}
              onChange={(e) => set(i, { is_senior: e.target.checked })}
            />
            Primer equipo
          </label>
          <button
            type="button"
            className={styles.iconBtn}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            aria-label={`Quitar la categoría ${i + 1}`}
            title="Quitar"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className={styles.linkBtn}
        onClick={() => onChange([...rows, { name: "", cohort_year: "", is_senior: false }])}
      >
        + Agregar categoría
      </button>
    </>
  );
}
