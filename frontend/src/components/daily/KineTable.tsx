"use client";

import React, { useEffect, useRef, useState } from "react";
import { Check, Plus, X } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DailyLesionado, KineEntry } from "./types";
import styles from "./KineTable.module.css";

interface Props {
  date: string;
  /** Injured / out players — always shown (a must). */
  injured: DailyLesionado[];
  /** Existing kine rows for the day. */
  entries: KineEntry[];
  /** Full roster, for the "add player" picker. */
  players: { id: string; name: string }[];
}

type RowStatus = "idle" | "saving" | "saved" | "error";

interface Row {
  player_id: string;
  name: string;
  injured: boolean;
  entryId: string | null;
  clinica: string;
  gimnasio: string;
  cancha: string;
  objetivo: string;
  kinesiologo: string;
  status: RowStatus;
}

const FIELDS: { key: keyof Row; label: string }[] = [
  { key: "clinica", label: "Clínica" },
  { key: "gimnasio", label: "Gimnasio" },
  { key: "cancha", label: "Cancha" },
  { key: "objetivo", label: "Objetivo Diario Kinésico" },
  { key: "kinesiologo", label: "Kinesiólogo a cargo" },
];

function buildRows(injured: DailyLesionado[], entries: KineEntry[]): Row[] {
  const byPlayer = new Map(entries.map((e) => [e.player_id, e]));
  const injuredIds = new Set(injured.map((l) => l.player_id));
  const row = (
    player_id: string,
    name: string,
    isInjured: boolean,
    e?: KineEntry,
  ): Row => ({
    player_id,
    name,
    injured: isInjured,
    entryId: e?.id ?? null,
    clinica: e?.clinica ?? "",
    gimnasio: e?.gimnasio ?? "",
    cancha: e?.cancha ?? "",
    objetivo: e?.objetivo ?? "",
    kinesiologo: e?.kinesiologo ?? "",
    status: "idle",
  });
  const injuredRows = injured.map((l) => row(l.player_id, l.name, true, byPlayer.get(l.player_id)));
  const addedRows = entries
    .filter((e) => !injuredIds.has(e.player_id))
    .map((e) => row(e.player_id, e.player_name, false, e));
  return [...injuredRows, ...addedRows];
}

export default function KineTable({ date, injured, entries, players }: Props) {
  const canEdit = usePermission("core.add_dailynote");
  const { toast } = useToast();
  const [rows, setRows] = useState<Row[]>(() => buildRows(injured, entries));
  const [picking, setPicking] = useState("");
  // Mirror of `rows` for reading the latest values inside async blur handlers
  // (kept in sync via an effect, never written during render).
  const rowsRef = useRef(rows);
  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  // Re-seed only when the underlying daily data changes (date / refetch).
  // Editing in place never triggers a parent refetch, so local edits are safe.
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) setRows(buildRows(injured, entries));
    });
    return () => {
      cancelled = true;
    };
  }, [date, injured, entries]);

  function setField(playerId: string, key: keyof Row, value: string) {
    setRows((rs) =>
      rs.map((r) => (r.player_id === playerId ? { ...r, [key]: value, status: "idle" } : r)),
    );
  }

  async function saveRow(playerId: string) {
    const row = rowsRef.current.find((r) => r.player_id === playerId);
    if (!row) return;
    setRows((rs) => rs.map((r) => (r.player_id === playerId ? { ...r, status: "saving" } : r)));
    try {
      const saved = await api<KineEntry>("/daily/kine", {
        method: "POST",
        body: JSON.stringify({
          player_id: row.player_id,
          date,
          clinica: row.clinica,
          gimnasio: row.gimnasio,
          cancha: row.cancha,
          objetivo: row.objetivo,
          kinesiologo: row.kinesiologo,
        }),
      });
      setRows((rs) =>
        rs.map((r) =>
          r.player_id === playerId ? { ...r, entryId: saved.id, status: "saved" } : r,
        ),
      );
    } catch (e) {
      setRows((rs) => rs.map((r) => (r.player_id === playerId ? { ...r, status: "error" } : r)));
      toast.error(e instanceof ApiError ? e.message : "No se pudo guardar la fila.");
    }
  }

  function addPlayer(playerId: string) {
    if (!playerId) return;
    const p = players.find((x) => x.id === playerId);
    if (!p || rows.some((r) => r.player_id === playerId)) {
      setPicking("");
      return;
    }
    setRows((rs) => [
      ...rs,
      {
        player_id: p.id, name: p.name, injured: false, entryId: null,
        clinica: "", gimnasio: "", cancha: "", objetivo: "", kinesiologo: "", status: "idle",
      },
    ]);
    setPicking("");
  }

  async function removeRow(row: Row) {
    // Only added (non-injured) rows can be dropped.
    if (row.entryId) {
      try {
        await api(`/daily/kine/${row.entryId}`, { method: "DELETE" });
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "No se pudo quitar.");
        return;
      }
    }
    setRows((rs) => rs.filter((r) => r.player_id !== row.player_id));
  }

  const shownIds = new Set(rows.map((r) => r.player_id));
  const available = players.filter((p) => !shownIds.has(p.id));

  return (
    <div className={styles.wrap}>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.nameCol}>Nombre</th>
              {FIELDS.map((f) => (
                <th key={f.key}>{f.label}</th>
              ))}
              {canEdit && <th className={styles.statusCol} aria-label="estado" />}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={FIELDS.length + 2} className={styles.empty}>
                  Sin jugadores lesionados. {canEdit ? "Podés agregar uno abajo." : ""}
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.player_id} className={r.injured ? styles.injuredRow : ""}>
                <td className={styles.nameCol}>
                  <span className={styles.name}>{r.name}</span>
                  {r.injured && <span className={styles.badge}>Lesionado</span>}
                </td>
                {FIELDS.map((f) => (
                  <td key={f.key}>
                    <input
                      className={styles.input}
                      value={r[f.key] as string}
                      placeholder={canEdit ? "—" : ""}
                      disabled={!canEdit}
                      onChange={(e) => setField(r.player_id, f.key, e.target.value)}
                      onBlur={() => canEdit && saveRow(r.player_id)}
                    />
                  </td>
                ))}
                {canEdit && (
                  <td className={styles.statusCol}>
                    {r.status === "saving" && <span className={styles.saving}>…</span>}
                    {r.status === "saved" && <Check size={15} className={styles.saved} />}
                    {r.status === "error" && <span className={styles.errDot} title="Error">!</span>}
                    {!r.injured && (
                      <button
                        type="button"
                        className={styles.removeBtn}
                        onClick={() => removeRow(r)}
                        aria-label={`Quitar ${r.name}`}
                        title="Quitar jugador"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canEdit && available.length > 0 && (
        <div className={styles.addRow}>
          <Plus size={15} className={styles.addIcon} />
          <select
            className={styles.addSelect}
            value={picking}
            onChange={(e) => addPlayer(e.target.value)}
          >
            <option value="">Agregar otro jugador…</option>
            {available.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
