"use client";

import React, { useEffect, useMemo, useState } from "react";
import styles from "./page.module.css";
import PlayerTable, { type EquipoPlayerRow } from "@/components/equipo/PlayerTable";
import PlayerListToolbar from "@/components/equipo/PlayerListToolbar";
import FieldView from "@/components/equipo/FieldView";
import { api, ApiError } from "@/lib/api";
import type { PlayerSummary } from "@/lib/types";

export type TabType = "list" | "field";

function toRow(p: PlayerSummary): EquipoPlayerRow {
  return {
    id: p.id,
    name: `${p.first_name} ${p.last_name}`.trim(),
    position: p.position?.abbreviation ?? "—",
    // Status / warning are not yet sourced from the API — stub defaults until
    // the alarms engine lands.
    status: "healthy",
    warning: "",
  };
}

export default function EquipoPage() {
  const [activeTab, setActiveTab] = useState<TabType>("list");
  const [players, setPlayers] = useState<PlayerSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<PlayerSummary[]>("/players")
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
  }, []);

  const rows = useMemo(() => (players ?? []).map(toRow), [players]);

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
            <PlayerTable players={rows} />
          </>
        ) : (
          <FieldView players={rows} />
        )}
      </div>
    </div>
  );
}
