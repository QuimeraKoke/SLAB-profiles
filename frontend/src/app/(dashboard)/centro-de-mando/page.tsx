"use client";

import React, { useEffect, useState } from "react";
import {
  Database,
  History,
  FileText,
  Plus,
  HeartPulse,
  RefreshCw,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import Hero from "@/components/command/Hero";
import KpiStrip from "@/components/command/KpiStrip";
import SquadStatus from "@/components/command/SquadStatus";
import DecisionTable from "@/components/command/DecisionTable";
import BriefingPanel from "@/components/command/BriefingPanel";
import type {
  CommandCenter,
  CCDataQualityRow,
  CCRecentItem,
  CCCheckinAdherence,
} from "@/components/command/types";
import styles from "./page.module.css";

export default function CommandCenterPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const [data, setData] = useState<CommandCenter | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) {
        setData(null);
        setError(null);
      }
    });
    api<CommandCenter>(`/command-center?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudo cargar el centro de mando.");
      });
    return () => { cancelled = true; };
  }, [categoryId]);

  const categoryName =
    categories.find((c) => c.id === categoryId)?.name ?? data?.category ?? "";

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;
  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <div className={styles.muted}>Cargando centro de mando…</div>;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>Centro de mando</h1>
          <p className={styles.sub}>{categoryName}</p>
        </div>
        <span className={styles.fresh}>
          <RefreshCw size={13} aria-hidden="true" />
          Datos actualizados {relativeTime(data.generated_at)}
        </span>
      </header>

      <div className={styles.stack}>
        {/* Full-width hero + KPI strip across the whole canvas. */}
        <Hero context={data.context} />
        <KpiStrip kpis={data.kpis} />

        {/* Below: main column + rail (Estado del plantel moved down here). */}
        <div className={styles.grid}>
          <main className={styles.main}>
            <BriefingPanel categoryId={categoryId} />
            <DecisionTable decisions={data.decisions} />
          </main>

          <aside className={styles.rail}>
            <SquadStatus squad={data.squad} />
            <CheckinAdherence data={data.checkin_adherence} />
            <DataQuality rows={data.data_quality} />
            <QuickActions />
            <RecentActivity items={data.recent} />
          </aside>
        </div>
      </div>
    </div>
  );
}

// ─── Small rail cards (inline; data already in the payload) ─────────────

function DataQuality({ rows }: { rows: CCDataQualityRow[] }) {
  return (
    <div className={styles.railCard}>
      <div className={styles.railHead}>
        <Database size={15} aria-hidden="true" />
        Calidad de datos
      </div>
      {rows.map((r) => (
        <div key={r.source} className={styles.dqRow}>
          <span className={`${styles.dot} ${styles[`dot_${r.status}`]}`} />
          <span className={styles.dqSource}>{r.source}</span>
          <span className={styles.dqDetail}>
            {r.last_at
              ? `${relativeTime(r.last_at)} · ${r.players} jug.`
              : r.detail}
          </span>
        </div>
      ))}
    </div>
  );
}

function CheckinAdherence({ data }: { data: CCCheckinAdherence }) {
  const { responded, expected, pct, no_respondieron, respondieron } = data;
  const tone = pct == null ? "muted" : pct >= 90 ? "ok" : pct >= 60 ? "warn" : "crit";
  const [openMissing, setOpenMissing] = useState(true);
  const [openDone, setOpenDone] = useState(false);
  return (
    <div className={styles.railCard}>
      <div className={styles.railHead}>
        <HeartPulse size={15} aria-hidden="true" />
        Adherencia al check-in de hoy
      </div>
      <div className={styles.adhStat}>
        <span className={`${styles.adhPct} ${styles[`adh_${tone}`]}`}>
          {pct == null ? "—" : `${pct}%`}
        </span>
        <span className={styles.adhCount}>
          {responded} de {expected} respondieron
        </span>
      </div>

      <AdhSection
        label="Faltan por responder"
        count={no_respondieron.length}
        open={openMissing}
        onToggle={() => setOpenMissing((v) => !v)}
        players={no_respondieron}
        emptyText="Todos respondieron ✓"
      />
      <AdhSection
        label="Ya respondieron"
        count={respondieron.length}
        open={openDone}
        onToggle={() => setOpenDone((v) => !v)}
        players={respondieron}
        emptyText="Nadie respondió todavía"
      />
    </div>
  );
}

function AdhSection({
  label, count, open, onToggle, players, emptyText,
}: {
  label: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  players: CCCheckinAdherence["no_respondieron"];
  emptyText: string;
}) {
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div className={styles.adhSection}>
      <button
        type="button"
        className={styles.adhSectionHead}
        onClick={onToggle}
        aria-expanded={open}
      >
        <Chevron size={14} aria-hidden="true" />
        <span className={styles.adhSectionLabel}>{label}</span>
        <span className={styles.adhSectionCount}>{count}</span>
      </button>
      {open &&
        (count === 0 ? (
          <p className={styles.muted}>{emptyText}</p>
        ) : (
          <div className={styles.adhList}>
            {players.map((p) => (
              <a key={p.player_id} href={`/perfil/${p.player_id}`} className={styles.adhRow}>
                <span className={styles.adhName}>{p.name}</span>
                {p.position && <span className={styles.adhPos}>{p.position}</span>}
                {p.injured && <span className={styles.adhChip}>lesionado</span>}
              </a>
            ))}
          </div>
        ))}
    </div>
  );
}

function QuickActions() {
  const actions = [
    { icon: <FileText size={15} aria-hidden="true" />, label: "Ver Dashboard", href: "/reportes/fisico" },
    { icon: <Plus size={15} aria-hidden="true" />, label: "Registrar lesión", href: "/equipo" },
    { icon: <HeartPulse size={15} aria-hidden="true" />, label: "Cargar wellness", href: "/equipo" },
  ];
  return (
    <div className={styles.railCard}>
      <div className={styles.railHead}>Acciones rápidas</div>
      {actions.map((a) => (
        <a key={a.label} href={a.href} className={styles.action}>
          {a.icon}
          {a.label}
        </a>
      ))}
    </div>
  );
}

function RecentActivity({ items }: { items: CCRecentItem[] }) {
  return (
    <div className={styles.railCard}>
      <div className={styles.railHead}>
        <History size={15} aria-hidden="true" />
        Cambios recientes
      </div>
      {items.length === 0 ? (
        <p className={styles.muted}>Sin actividad reciente.</p>
      ) : (
        items.map((it, i) => (
          <div key={i} className={styles.recentRow}>
            <span className={`${styles.dot} ${styles[`dot_${toneFor(it.kind)}`]}`} />
            <div>
              <div className={styles.recentText}>{it.text}</div>
              {it.at && <div className={styles.recentAt}>{relativeTime(it.at)}</div>}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────

function toneFor(kind: string): string {
  if (kind === "critical") return "crit";
  if (kind === "warning") return "warn";
  return "info";
}

function relativeTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "hace instantes";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return `hace ${Math.floor(diff / 86400)} días`;
}
