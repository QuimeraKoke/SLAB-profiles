"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Search, Plus } from "lucide-react";

import RosterTable, { type RosterRow } from "@/components/equipo/RosterTable";
import PlayerEditModal from "@/components/equipo/PlayerEditModal";
import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { usePermission } from "@/lib/permissions";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import styles from "./page.module.css";

interface RosterPayload {
  category: string;
  counts: Record<string, number>;
  players: RosterRow[];
}

const TABS: { key: string; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "available", label: "Disponibles" },
  { key: "reintegration", label: "Return to Train" },
  { key: "recovery", label: "Recuperación" },
  { key: "injured", label: "Lesionados" },
];

function normalize(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

export default function EquipoPage() {
  const { categoryId, loading: categoryLoading } = useCategoryContext();
  const { confirm } = useConfirm();
  const { toast } = useToast();
  // Both edit and deactivate are PATCH /players/{id} — gated on change_player.
  const canManage = usePermission("core.change_player");
  const [data, setData] = useState<RosterPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [reload, setReload] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    if (categoryLoading || !categoryId) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) { setData(null); setError(null); }
    });
    api<RosterPayload>(`/roster?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "No se pudo cargar el plantel.");
      });
    return () => { cancelled = true; };
  }, [categoryId, categoryLoading, reload]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = normalize(query.trim());
    return data.players.filter((p) => {
      if (statusFilter !== "all" && p.status !== statusFilter) return false;
      if (q && !normalize(`${p.name} ${p.position}`).includes(q)) return false;
      return true;
    });
  }, [data, statusFilter, query]);

  async function handleDeactivate(row: RosterRow) {
    const ok = await confirm({
      title: `Dar de baja a ${row.name}`,
      message:
        "Dejará de aparecer en el plantel y en los tableros, pero su historial " +
        "(resultados, episodios, contratos) se conserva. Podés reactivarlo desde " +
        "Gestionar plantel.",
      confirmLabel: "Dar de baja",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api(`/players/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: false }),
      });
      toast.success(`${row.name} fue dado de baja.`);
      setReload((k) => k + 1);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo dar de baja al jugador.");
    }
  }

  if (categoryLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;
  if (error) return <div className={styles.error} role="alert">{error}</div>;

  const counts = data?.counts ?? {};

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>Plantel</h1>
          <p className={styles.sub}>
            {counts.all ?? 0} jugadores · administra el plantel, edita datos o da de
            baja — el resumen vive en Centro de mando.
          </p>
        </div>
        <Link href="/configuraciones/jugadores" className={styles.addBtn}>
          <Plus size={16} aria-hidden="true" /> Agregar jugador
        </Link>
      </header>

      <div className={styles.searchRow}>
        <span className={styles.searchWrap}>
          <Search size={16} aria-hidden="true" className={styles.searchIcon} />
          <input
            className={styles.search}
            placeholder="Buscar por nombre o posición…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </span>
      </div>

      <div className={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`${styles.tab} ${statusFilter === t.key ? styles.tabActive : ""}`}
            onClick={() => setStatusFilter(t.key)}
          >
            {t.label}
            <span className={styles.tabCount}>{counts[t.key] ?? 0}</span>
          </button>
        ))}
      </div>

      {!data ? (
        <div className={styles.muted}>Cargando plantel…</div>
      ) : (
        <RosterTable
          rows={rows}
          canEdit={canManage}
          canDeactivate={canManage}
          onEdit={(r) => setEditingId(r.id)}
          onDeactivate={handleDeactivate}
        />
      )}

      {editingId && (
        <PlayerEditModal
          playerId={editingId}
          onClose={() => setEditingId(null)}
          onSaved={() => {
            setEditingId(null);
            setReload((k) => k + 1);
          }}
        />
      )}
    </div>
  );
}
