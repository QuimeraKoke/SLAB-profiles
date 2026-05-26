"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";

import { api } from "@/lib/api";
import type { PlayerSummary } from "@/lib/types";

import styles from "./PlayerSearchPicker.module.css";

interface Props {
  /** Map category_id → category_name. Drives the `[Categoría]` badge
   *  shown next to each search result. Parent fetches once and reuses. */
  categoriesById: Record<string, string>;
  /** Player IDs already in the roster — excluded from the dropdown so
   *  the coach can't add duplicates. */
  excludeIds: Set<string>;
  /** Called when the coach picks a result. `addAs` is the role they
   *  chose from the side dropdown — defaulted upstream. */
  onPick: (player: PlayerSummary, addAs: string) => void;
}

const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: "titular", label: "Titular" },
  { value: "suplente_ingresa", label: "Suplente — ingresa" },
  { value: "suplente_no_ingresa", label: "Suplente — no ingresa" },
  { value: "citado_no_vestir", label: "Citado sin vestir" },
  { value: "lesionado", label: "Lesionado" },
  { value: "suspendido", label: "Suspendido" },
  { value: "seleccion", label: "Selección" },
  { value: "promovido", label: "Promovido" },
  { value: "no_citado", label: "No citado" },
];

/**
 * Typeahead picker for the convocatoria panel. Hits
 * `/api/players?search=...&limit=10` on every (debounced) keystroke
 * and offers cross-category matches. The "Agregar como" dropdown
 * sets the role the player will be added with, so a coach can
 * batch-add 11 titulares without opening each row.
 */
export default function PlayerSearchPicker({
  categoriesById, excludeIds, onPick,
}: Props) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [results, setResults] = useState<PlayerSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const [addAs, setAddAs] = useState<string>("titular");
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Debounce — 200ms is responsive enough without thrashing the API.
  useEffect(() => {
    const id = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(id);
  }, [query]);

  useEffect(() => {
    if (debounced.length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api<PlayerSummary[]>(
      `/players?search=${encodeURIComponent(debounced)}&limit=10&cross_category=true`,
    )
      .then((data) => {
        if (cancelled) return;
        setResults(data);
        setHighlighted(0);
      })
      .catch(() => {
        if (!cancelled) setResults([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onPointer(e: PointerEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const filtered = useMemo(
    () => results.filter((p) => !excludeIds.has(p.id)),
    [results, excludeIds],
  );

  const handlePick = (p: PlayerSummary) => {
    onPick(p, addAs);
    setQuery("");
    setResults([]);
    setOpen(false);
    // Keep focus on the input so the coach can chain-add players.
    inputRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || filtered.length === 0) {
      if (e.key === "ArrowDown" && filtered.length > 0) {
        setOpen(true);
        setHighlighted(0);
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = filtered[highlighted];
      if (pick) handlePick(pick);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className={styles.wrapper} ref={wrapperRef}>
      <div className={styles.row}>
        <div className={styles.searchWrap}>
          <Search size={16} className={styles.searchIcon} aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            className={styles.input}
            placeholder="Buscar jugador por nombre o apellido…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
          />
        </div>
        <label className={styles.addAs}>
          <span className={styles.addAsLabel}>Agregar como</span>
          <select
            className={styles.addAsSelect}
            value={addAs}
            onChange={(e) => setAddAs(e.target.value)}
          >
            {ROLE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {open && (query.length >= 2 || loading) && (
        <div className={styles.dropdown} role="listbox">
          {loading && filtered.length === 0 ? (
            <div className={styles.muted}>Buscando…</div>
          ) : filtered.length === 0 ? (
            <div className={styles.muted}>
              {results.length > 0
                ? "Todos los resultados ya están en la convocatoria."
                : "Sin coincidencias."}
            </div>
          ) : (
            filtered.map((p, idx) => {
              const isActive = idx === highlighted;
              return (
                <button
                  key={p.id}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  className={`${styles.option} ${isActive ? styles.optionActive : ""}`}
                  onMouseEnter={() => setHighlighted(idx)}
                  onClick={() => handlePick(p)}
                >
                  <span className={styles.optionName}>
                    {p.last_name}, {p.first_name}
                  </span>
                  <span className={styles.optionCategory}>
                    {categoriesById[p.category_id] || "—"}
                  </span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
