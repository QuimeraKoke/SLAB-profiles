"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Trophy, Calendar, ChevronDown, X } from "lucide-react";

import type { TeamMatchSelectorConfig } from "@/lib/types";
import styles from "./MatchMultiSelector.module.css";

interface Props {
  config: TeamMatchSelectorConfig;
  /** Called with the new list of selected match IDs. Empty array means
   *  "no specific selection" — required-mode layouts treat that as
   *  "all matches" on the backend. */
  onChange: (eventIds: string[]) => void;
}

/**
 * Multi-select counterpart to `MatchSelector`. Rendered when the layout's
 * `match_selector.mode === "multi"`. Surfaces a "hero" summary line plus
 * a dropdown with checkboxes — one per match — that the user can tick to
 * scope every widget on the page to a subset of matches.
 *
 * URL ownership stays with the parent (we just emit `onChange(ids[])`),
 * matching the single-mode pattern. Selection persists via `?match_ids=`.
 */
export default function MatchMultiSelector({ config, onChange }: Props) {
  const { options, selected_ids, label, required } = config;
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  // Grouped view (one section per Y-M of the match date). On by default
  // since matches come in seasonal cohorts and grouping makes it easier
  // to tick a whole month at once via the group checkbox.
  const [groupByMonth, setGroupByMonth] = useState(true);

  // Close on outside click — same UX as the existing PlayerMultiSelect
  // inside ReportFilters.
  useEffect(() => {
    if (!open) return;
    function onPointer(e: PointerEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const selectedIds = useMemo(
    () => new Set(selected_ids ?? []),
    [selected_ids],
  );

  const selectedOptions = useMemo(
    () => options.filter((o) => selectedIds.has(o.id)),
    [options, selectedIds],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) =>
      o.title.toLowerCase().includes(q) || o.starts_at.toLowerCase().includes(q),
    );
  }, [options, search]);

  // Group filtered options by Y-M of starts_at. `options` arrives newest
  // first from the backend, so groups end up in reverse chronological
  // order naturally — the latest month sits at the top of the dropdown.
  type MonthGroup = {
    key: string; // e.g. "2026-04"
    label: string; // e.g. "Abril 2026"
    items: typeof options;
  };
  const monthGroups: MonthGroup[] = useMemo(() => {
    if (!groupByMonth) return [];
    const map = new Map<string, MonthGroup>();
    for (const o of filtered) {
      const d = new Date(o.starts_at);
      if (Number.isNaN(d.getTime())) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      let g = map.get(key);
      if (!g) {
        g = {
          key,
          label: d.toLocaleDateString("es-CL", { month: "long", year: "numeric" })
            .replace(/^./, (c) => c.toUpperCase()),
          items: [],
        };
        map.set(key, g);
      }
      g.items.push(o);
    }
    return Array.from(map.values());
  }, [filtered, groupByMonth]);

  // Empty state — no matches loaded for this category yet.
  if (options.length === 0) {
    return (
      <div className={styles.empty}>
        <Trophy size={18} aria-hidden="true" />
        <span>Sin partidos cargados para esta categoría.</span>
      </div>
    );
  }

  const toggle = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(Array.from(next));
  };

  const selectAll = () => onChange(options.map((o) => o.id));
  const clearAll = () => onChange([]);

  const buttonText =
    selectedOptions.length === 0
      ? required
        ? "Todos los partidos"
        : "Seleccionar partidos"
      : selectedOptions.length === 1
        ? formatShortLabel(selectedOptions[0].starts_at, selectedOptions[0].title)
        : `${selectedOptions.length} de ${options.length} partidos`;

  return (
    <div className={styles.hero} ref={wrapperRef}>
      <div className={styles.headline}>
        <Trophy size={20} aria-hidden="true" />
        <div className={styles.headlineText}>
          <span className={styles.eyebrow}>{label}</span>
          <span className={styles.title}>{buttonText}</span>
          {selectedOptions.length > 0 && selectedOptions.length <= 6 && (
            <div className={styles.chipRow}>
              {selectedOptions.map((o) => (
                <span key={o.id} className={styles.chip}>
                  <Calendar size={11} aria-hidden="true" />
                  {formatDate(o.starts_at)}
                  <button
                    type="button"
                    className={styles.chipRemove}
                    aria-label={`Quitar ${o.title}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(o.id);
                    }}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className={styles.pickerWrap}>
        <button
          type="button"
          className={styles.pickerButton}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-haspopup="listbox"
        >
          <span>Elegir partidos</span>
          <ChevronDown size={16} aria-hidden="true" />
        </button>

        {open && (
          <div className={styles.dropdown} role="listbox">
            <input
              className={styles.search}
              type="text"
              placeholder="Buscar partido…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.actionBtn}
                onClick={selectAll}
              >
                Seleccionar todos
              </button>
              <button
                type="button"
                className={styles.actionBtn}
                onClick={clearAll}
                disabled={required && selectedOptions.length === 0}
              >
                Limpiar
              </button>
              <label className={styles.groupToggle}>
                <input
                  type="checkbox"
                  checked={groupByMonth}
                  onChange={(e) => setGroupByMonth(e.target.checked)}
                />
                <span>Agrupar por mes</span>
              </label>
            </div>
            <div className={styles.list}>
              {filtered.length === 0 ? (
                <div className={styles.noResults}>Sin coincidencias</div>
              ) : groupByMonth ? (
                monthGroups.map((g) => {
                  const all = g.items.every((o) => selectedIds.has(o.id));
                  const some = g.items.some((o) => selectedIds.has(o.id));
                  const checked = all;
                  const indeterminate = !all && some;
                  return (
                    <div key={g.key} className={styles.group}>
                      <label className={styles.groupHeader}>
                        <input
                          type="checkbox"
                          checked={checked}
                          ref={(el) => {
                            // Native indeterminate isn't expressible
                            // as a JSX prop — set it imperatively.
                            if (el) el.indeterminate = indeterminate;
                          }}
                          onChange={() => {
                            // All on → clear; otherwise → select all
                            // (covers both none and partial states).
                            const groupIds = g.items.map((o) => o.id);
                            const next = new Set(selectedIds);
                            if (all) {
                              for (const id of groupIds) next.delete(id);
                            } else {
                              for (const id of groupIds) next.add(id);
                            }
                            onChange(Array.from(next));
                          }}
                        />
                        <span className={styles.groupLabel}>{g.label}</span>
                        <span className={styles.groupCount}>
                          {g.items.filter((o) => selectedIds.has(o.id)).length}
                          {" / "}
                          {g.items.length}
                        </span>
                      </label>
                      <div className={styles.groupItems}>
                        {g.items.map((o) => {
                          const isChecked = selectedIds.has(o.id);
                          return (
                            <label key={o.id} className={styles.option}>
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() => toggle(o.id)}
                              />
                              <span className={styles.optionDate}>
                                {formatDate(o.starts_at)}
                              </span>
                              <span className={styles.optionTitle} title={o.title}>
                                {o.title}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  );
                })
              ) : (
                filtered.map((o) => {
                  const isChecked = selectedIds.has(o.id);
                  return (
                    <label key={o.id} className={styles.option}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggle(o.id)}
                      />
                      <span className={styles.optionDate}>
                        {formatDate(o.starts_at)}
                      </span>
                      <span className={styles.optionTitle} title={o.title}>
                        {o.title}
                      </span>
                    </label>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
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

function formatShortLabel(iso: string, title: string): string {
  return `${formatDate(iso)} · ${title}`;
}
