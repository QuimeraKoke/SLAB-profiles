"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Calendar, ChevronDown, Search } from "lucide-react";

import type { CalendarEvent } from "@/lib/types";

import styles from "./MatchPicker.module.css";

interface Props {
  matches: CalendarEvent[];
  value: string | null;
  onChange: (eventId: string | null) => void;
  /** Label shown above the field. Defaults to "Partido". */
  label?: string;
  /** Optional placeholder shown when no match is picked. */
  placeholder?: string;
  /** When true, the form considers the field required. Only affects the
   *  visual asterisk; saving validation is the parent's job. */
  required?: boolean;
}

/**
 * Single-select match picker used by every exam-template flow that
 * binds a result to a match: the team-table mode on the registrar
 * page, the per-player DynamicUploader's "Asociar partido" section,
 * and any future match-scoped form.
 *
 * UX details:
 *  - The dropdown groups matches under sticky `Mes Año` headers.
 *    Matches arrive newest-first from the caller, so the latest
 *    month sits at the top.
 *  - Searchable: typing filters across title + ISO date.
 *  - Mobile-friendly: the trigger shows the chosen match's title +
 *    date; the dropdown is overlay-positioned so it can extend
 *    beyond the parent card's overflow box.
 */
export default function MatchPicker({
  matches, value, onChange, label = "Partido", placeholder, required = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(e: PointerEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const selected = useMemo(
    () => matches.find((m) => m.id === value) ?? null,
    [matches, value],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return matches;
    return matches.filter((m) =>
      m.title.toLowerCase().includes(q) || m.starts_at.toLowerCase().includes(q),
    );
  }, [matches, search]);

  // Group filtered options by Y-M. Order preserved from the caller.
  const groups = useMemo(() => {
    const map = new Map<string, { key: string; label: string; items: CalendarEvent[] }>();
    for (const m of filtered) {
      const d = new Date(m.starts_at);
      if (Number.isNaN(d.getTime())) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      let g = map.get(key);
      if (!g) {
        g = {
          key,
          label: d
            .toLocaleDateString("es-CL", { month: "long", year: "numeric" })
            .replace(/^./, (c) => c.toUpperCase()),
          items: [],
        };
        map.set(key, g);
      }
      g.items.push(m);
    }
    return Array.from(map.values());
  }, [filtered]);

  return (
    <div className={styles.wrapper} ref={wrapperRef}>
      <label className={styles.label}>
        {label}
        {required && <span className={styles.required}> *</span>}
      </label>

      <button
        type="button"
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        {selected ? (
          <span className={styles.triggerSelected}>
            <Calendar size={14} aria-hidden="true" />
            <span className={styles.triggerDate}>{formatShortDate(selected.starts_at)}</span>
            <span className={styles.triggerTitle}>{selected.title}</span>
          </span>
        ) : (
          <span className={styles.triggerPlaceholder}>
            {placeholder ?? "Elegí un partido…"}
          </span>
        )}
        <ChevronDown size={16} aria-hidden="true" className={styles.chevron} />
      </button>

      {open && (
        <div className={styles.dropdown} role="listbox">
          <div className={styles.searchWrap}>
            <Search size={14} className={styles.searchIcon} aria-hidden="true" />
            <input
              className={styles.search}
              type="text"
              placeholder="Buscar partido…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
          </div>
          {!required && (
            <button
              type="button"
              className={`${styles.option} ${styles.optionClear}`}
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
            >
              — Sin partido —
            </button>
          )}
          {groups.length === 0 ? (
            <div className={styles.noResults}>Sin coincidencias</div>
          ) : (
            groups.map((g) => (
              <div key={g.key} className={styles.group}>
                <div className={styles.groupHeader}>
                  <span className={styles.groupLabel}>{g.label}</span>
                  <span className={styles.groupCount}>{g.items.length}</span>
                </div>
                {g.items.map((m) => {
                  const isSelected = m.id === value;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      className={`${styles.option} ${isSelected ? styles.optionActive : ""}`}
                      onClick={() => {
                        onChange(m.id);
                        setOpen(false);
                      }}
                    >
                      <span className={styles.optionDate}>{formatShortDate(m.starts_at)}</span>
                      <span className={styles.optionTitle} title={m.title}>
                        {m.title}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function formatShortDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("es-CL", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}
