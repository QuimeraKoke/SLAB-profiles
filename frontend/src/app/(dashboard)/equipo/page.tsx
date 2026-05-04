"use client";

import React, { useEffect, useMemo, useState } from "react";
import styles from "./page.module.css";
import PlayerTable, { type EquipoPlayerRow } from "@/components/equipo/PlayerTable";
import PlayerListToolbar from "@/components/equipo/PlayerListToolbar";
import FieldView from "@/components/equipo/FieldView";
import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import type { PlayerSummary } from "@/lib/types";

export type TabType = "list" | "field";

function toRow(p: PlayerSummary): EquipoPlayerRow {
  return {
    id: p.id,
    name: `${p.first_name} ${p.last_name}`.trim(),
    position: p.position?.abbreviation ?? "—",
    status: p.status ?? "available",
    warning: "",
  };
}

export default function EquipoPage() {
  const [activeTab, setActiveTab] = useState<TabType>("list");
  const [players, setPlayers] = useState<PlayerSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | PlayerSummary["status"]>("all");
  const { categoryId, loading: categoryLoading } = useCategoryContext();

  useEffect(() => {
    if (categoryLoading) return;
    let cancelled = false;
    const url = categoryId ? `/players?category_id=${categoryId}` : "/players";
    api<PlayerSummary[]>(url)
      .then((data) => {
        if (!cancelled) setPlayers(data);
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Failed to load players";
        setError(message);
        setPlayers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId, categoryLoading]);

  const filteredPlayers = useMemo(() => {
    const all = players ?? [];
    if (statusFilter === "all") return all;
    return all.filter((p) => p.status === statusFilter);
  }, [players, statusFilter]);

  const rows = useMemo(() => filteredPlayers.map(toRow), [filteredPlayers]);

  const statusCounts = useMemo(() => {
    const counts = { available: 0, injured: 0, recovery: 0, reintegration: 0 };
    for (const p of players ?? []) {
      const k = p.status as keyof typeof counts;
      if (k in counts) counts[k] += 1;
    }
    return counts;
  }, [players]);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${activeTab === "list" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("list")}
          >
            Plantel Profesional
          </button>
          <button
            className={`${styles.tab} ${activeTab === "field" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("field")}
          >
            Vista de Campo
          </button>
        </div>
      </header>

      <div className={styles.content}>
        {error && (
          <div role="alert" style={{ color: "#dc2626", padding: 12 }}>
            {error}
          </div>
        )}

        {players === null ? (
          <div style={{ padding: 24, color: "#6b7280" }}>Cargando jugadores…</div>
        ) : activeTab === "list" ? (
          <>
            <PlayerListToolbar />
            <div
              style={{
                display: "flex", gap: 8, padding: "8px 16px",
                background: "#f9fafb", borderBottom: "1px solid #e5e7eb",
                fontSize: "0.82rem",
              }}
            >
              <StatusChip
                label={`Todos · ${players.length}`}
                active={statusFilter === "all"}
                onClick={() => setStatusFilter("all")}
              />
              <StatusChip
                label={`Disponibles · ${statusCounts.available}`}
                active={statusFilter === "available"}
                onClick={() => setStatusFilter("available")}
                tone="green"
              />
              <StatusChip
                label={`Reintegración · ${statusCounts.reintegration}`}
                active={statusFilter === "reintegration"}
                onClick={() => setStatusFilter("reintegration")}
                tone="yellow"
              />
              <StatusChip
                label={`Recuperación · ${statusCounts.recovery}`}
                active={statusFilter === "recovery"}
                onClick={() => setStatusFilter("recovery")}
                tone="orange"
              />
              <StatusChip
                label={`Lesionados · ${statusCounts.injured}`}
                active={statusFilter === "injured"}
                onClick={() => setStatusFilter("injured")}
                tone="red"
              />
            </div>
            <PlayerTable players={rows} />
          </>
        ) : (
          <FieldView players={rows} />
        )}
      </div>
    </div>
  );
}

interface StatusChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
  tone?: "green" | "yellow" | "orange" | "red";
}

function StatusChip({ label, active, onClick, tone }: StatusChipProps) {
  const palettes: Record<string, { bg: string; color: string; border: string }> = {
    green: { bg: "#dcfce7", color: "#166534", border: "#86efac" },
    yellow: { bg: "#fef3c7", color: "#854d0e", border: "#fde68a" },
    orange: { bg: "#fed7aa", color: "#9a3412", border: "#fdba74" },
    red: { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5" },
  };
  const palette = tone ? palettes[tone] : null;
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: active ? palette?.bg ?? "#e0e7ff" : "transparent",
        color: active ? palette?.color ?? "#3730a3" : "#6b7280",
        border: `1px solid ${active ? palette?.border ?? "#a5b4fc" : "#d1d5db"}`,
        borderRadius: 999,
        padding: "4px 10px",
        fontSize: "0.78rem",
        fontWeight: active ? 700 : 500,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}
