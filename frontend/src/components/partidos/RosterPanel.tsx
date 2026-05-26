"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Trash2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import type { Category, PlayerSummary } from "@/lib/types";

import PlayerSearchPicker from "./PlayerSearchPicker";
import styles from "./RosterPanel.module.css";

export interface RosterEntry {
  player_id: string;
  first_name: string;
  last_name: string;
  category_id: string | null;
  category_name: string;
  match_role: string;
  absence_reason: string;
  position_played_id: string | null;
}

const ROLE_OPTIONS: { value: string; label: string; group: "available" | "unavailable" }[] = [
  { value: "titular", label: "Titular", group: "available" },
  { value: "suplente_ingresa", label: "Suplente — ingresa", group: "available" },
  { value: "suplente_no_ingresa", label: "Suplente — no ingresa", group: "available" },
  { value: "citado_no_vestir", label: "Citado sin vestir", group: "unavailable" },
  { value: "lesionado", label: "Lesionado", group: "unavailable" },
  { value: "suspendido", label: "Suspendido", group: "unavailable" },
  { value: "seleccion", label: "Selección", group: "unavailable" },
  { value: "promovido", label: "Promovido", group: "unavailable" },
  { value: "no_citado", label: "No citado", group: "unavailable" },
];

// Roles where a free-text reason field makes sense to expose.
const ROLES_WITH_REASON = new Set(["lesionado", "suspendido", "citado_no_vestir"]);

interface Props {
  eventId: string;
  /** Refetch trigger from the parent. When the parent re-saves the
   *  match (date / category changed), we re-pull the roster. */
  refreshKey: number;
  /** Called after a successful save so the parent can resync the
   *  event payload (e.g. TeamTableForm's participantIds list). */
  onSaved?: () => void;
  /** Fired on every change to the in-memory roster — initial load,
   *  add, role change, remove, copy-from-last, save. The parent uses
   *  this to derive which players are "dressed" (titular / suplente
   *  ingresa / citado_no_vestir) and feed that list to the stats
   *  table. Always called with the full current entries array. */
  onEntriesChange?: (entries: RosterEntry[]) => void;
}

/**
 * Roster panel for `/partidos/[id]/editar`. Lists every convocated
 * player with their match_role, supports cross-category add via the
 * search picker, and a one-click "Copiar del último partido" preload.
 */
export default function RosterPanel({ eventId, refreshKey, onSaved, onEntriesChange }: Props) {
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [categoriesById, setCategoriesById] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [copying, setCopying] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // Pre-fetch category map (small payload, used by the picker badge).
  useEffect(() => {
    let cancelled = false;
    api<Category[]>("/categories")
      .then((cats) => {
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const c of cats) map[c.id] = c.name;
        setCategoriesById(map);
      })
      .catch(() => {
        if (!cancelled) setCategoriesById({});
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Load the existing roster from the backend.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<RosterEntry[]>(`/events/${eventId}/roster`)
      .then((data) => {
        if (cancelled) return;
        setEntries(data);
        setDirty(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Error al cargar la convocatoria");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [eventId, refreshKey]);

  // Stash the parent's callback in a ref so we DON'T need to put it
  // in the effect's deps array — otherwise an inline arrow on the
  // parent's render creates a new fn reference each render, re-firing
  // the effect, which calls setState on the parent, re-rendering it,
  // re-creating the arrow… infinite loop. Ref keeps a stable closure
  // target while always pointing at the latest callback.
  const onEntriesChangeRef = useRef(onEntriesChange);
  useEffect(() => {
    onEntriesChangeRef.current = onEntriesChange;
  });

  useEffect(() => {
    // Microtask so the parent setState isn't called synchronously
    // during this component's render (set-state-in-effect lint guard).
    const cb = onEntriesChangeRef.current;
    if (!cb) return;
    Promise.resolve().then(() => cb(entries));
  }, [entries]);

  const excludeIds = useMemo(
    () => new Set(entries.map((e) => e.player_id)),
    [entries],
  );

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const e of entries) {
      const k = e.match_role || "(sin rol)";
      out[k] = (out[k] ?? 0) + 1;
    }
    return out;
  }, [entries]);

  const handleAdd = (player: PlayerSummary, addAs: string) => {
    const newEntry: RosterEntry = {
      player_id: player.id,
      first_name: player.first_name,
      last_name: player.last_name,
      category_id: player.category_id,
      category_name: categoriesById[player.category_id] || "",
      match_role: addAs,
      absence_reason: "",
      position_played_id: null,
    };
    setEntries((prev) =>
      [...prev, newEntry].sort((a, b) =>
        a.last_name.localeCompare(b.last_name) ||
        a.first_name.localeCompare(b.first_name)
      ),
    );
    setDirty(true);
    setInfo(null);
  };

  const handleRoleChange = (playerId: string, role: string) => {
    setEntries((prev) =>
      prev.map((e) =>
        e.player_id === playerId
          ? {
              ...e,
              match_role: role,
              // Clear the reason text if the new role doesn't expose it
              // — prevents stale "esguince tobillo" hanging around when
              // the coach moves the player back to Titular.
              absence_reason: ROLES_WITH_REASON.has(role) ? e.absence_reason : "",
            }
          : e,
      ),
    );
    setDirty(true);
  };

  const handleReasonChange = (playerId: string, reason: string) => {
    setEntries((prev) =>
      prev.map((e) =>
        e.player_id === playerId ? { ...e, absence_reason: reason } : e,
      ),
    );
    setDirty(true);
  };

  const handleRemove = (playerId: string) => {
    setEntries((prev) => prev.filter((e) => e.player_id !== playerId));
    setDirty(true);
  };

  const handleCopyFromLast = async () => {
    setCopying(true);
    setError(null);
    setInfo(null);
    try {
      const suggested = await api<RosterEntry[]>(
        `/events/${eventId}/suggested-roster`,
      );
      if (suggested.length === 0) {
        setInfo("No se encontró un partido anterior con convocatoria para copiar.");
      } else {
        setEntries(suggested);
        setDirty(true);
        setInfo(`Copiados ${suggested.length} jugadores del último partido. Revisá y guardá.`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al copiar la convocatoria");
    } finally {
      setCopying(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const payload = {
        entries: entries.map((e) => ({
          player_id: e.player_id,
          match_role: e.match_role,
          absence_reason: e.absence_reason || "",
          position_played_id: e.position_played_id,
        })),
      };
      const saved = await api<RosterEntry[]>(`/events/${eventId}/roster`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setEntries(saved);
      setDirty(false);
      setInfo(`Convocatoria guardada (${saved.length} jugadores).`);
      onSaved?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al guardar la convocatoria");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className={styles.panel}>
      <header className={styles.header}>
        <div>
          <h2 className={styles.title}>Convocatoria</h2>
          <span className={styles.subtitle}>
            {entries.length} {entries.length === 1 ? "jugador" : "jugadores"}
            {Object.keys(counts).length > 0 && (
              <span className={styles.subtitleHint}>
                {" · "}
                {Object.entries(counts)
                  .map(([role, n]) => `${labelFor(role)}: ${n}`)
                  .join(" · ")}
              </span>
            )}
          </span>
        </div>
        <button
          type="button"
          className={styles.copyBtn}
          onClick={handleCopyFromLast}
          disabled={copying || saving}
        >
          <Copy size={14} aria-hidden="true" />
          {copying ? "Copiando…" : "Copiar del último partido"}
        </button>
      </header>

      {error && <div className={styles.error}>{error}</div>}
      {info && <div className={styles.info}>{info}</div>}

      <PlayerSearchPicker
        categoriesById={categoriesById}
        excludeIds={excludeIds}
        onPick={handleAdd}
      />

      {loading ? (
        <div className={styles.muted}>Cargando convocatoria…</div>
      ) : entries.length === 0 ? (
        <div className={styles.empty}>
          Sin jugadores. Buscá y agregá uno arriba, o copiá del último partido.
        </div>
      ) : (
        <ul className={styles.list}>
          {entries.map((e) => (
            <li key={e.player_id} className={styles.row}>
              <span className={styles.rowName} title={`${e.first_name} ${e.last_name}`}>
                {e.last_name}, {e.first_name}
              </span>
              {e.category_name && (
                <span className={styles.rowCategory}>{e.category_name}</span>
              )}
              <select
                className={styles.rowRole}
                value={e.match_role}
                onChange={(ev) => handleRoleChange(e.player_id, ev.target.value)}
              >
                <optgroup label="Disponibles">
                  {ROLE_OPTIONS.filter((o) => o.group === "available").map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </optgroup>
                <optgroup label="No disponibles">
                  {ROLE_OPTIONS.filter((o) => o.group === "unavailable").map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </optgroup>
              </select>
              {ROLES_WITH_REASON.has(e.match_role) ? (
                <input
                  type="text"
                  className={styles.rowReason}
                  placeholder="Motivo (opcional)"
                  value={e.absence_reason}
                  onChange={(ev) => handleReasonChange(e.player_id, ev.target.value)}
                />
              ) : (
                <span className={styles.rowReasonSpacer} aria-hidden="true" />
              )}
              <button
                type="button"
                className={styles.rowRemove}
                onClick={() => handleRemove(e.player_id)}
                aria-label={`Quitar ${e.first_name} ${e.last_name}`}
                title="Quitar"
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <footer className={styles.footer}>
        <button
          type="button"
          className={styles.saveBtn}
          onClick={handleSave}
          disabled={!dirty || saving}
        >
          {saving ? "Guardando…" : dirty ? "Guardar convocatoria" : "Sin cambios"}
        </button>
      </footer>
    </section>
  );
}

function labelFor(role: string): string {
  return ROLE_OPTIONS.find((o) => o.value === role)?.label ?? role;
}
