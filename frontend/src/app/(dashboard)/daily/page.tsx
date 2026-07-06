"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Sunrise,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { usePermission } from "@/lib/permissions";
import DownloadPdfButton from "@/components/reports/DownloadPdfButton";
import RosterTable, { RosterRow } from "@/components/equipo/RosterTable";
import LesionadoCard from "@/components/daily/LesionadoCard";
import NoteModal from "@/components/daily/NoteModal";
import NotesPanel from "@/components/daily/NotesPanel";
import type { DailyAlertRow, DailyReport } from "@/components/daily/types";
import styles from "./page.module.css";

interface RosterPayload {
  category: string;
  counts: Record<string, number>;
  players: RosterRow[];
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftIso(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function longDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-CL", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

export default function DailyPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const canNote = usePermission("core.add_dailynote");

  // URL is the source of truth for the meeting date (deep-linkable).
  const date = searchParams.get("date") ?? todayIso();

  const [data, setData] = useState<DailyReport | null>(null);
  const [roster, setRoster] = useState<RosterPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [noteFor, setNoteFor] = useState<string | null>(null); // player_id | null
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteKind, setNoteKind] = useState<"pauta" | "plan">("pauta");

  useEffect(() => {
    if (catLoading || !categoryId) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) setError(null);
    });
    api<DailyReport>(`/daily-report?category_id=${categoryId}&date=${date}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "No se pudo cargar la Daily.");
      });
    api<RosterPayload>(`/roster?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setRoster(d); })
      .catch(() => { /* the annex is best-effort — the report still renders */ });
    return () => { cancelled = true; };
  }, [categoryId, catLoading, date, reload]);

  const setDate = useCallback(
    (iso: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (iso === todayIso()) params.delete("date");
      else params.set("date", iso);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  const disponibles = useMemo(
    () => (roster?.players ?? []).filter((p) => p.status === "available"),
    [roster],
  );

  const categoryName =
    categories.find((c) => c.id === categoryId)?.name ?? data?.category ?? "";

  function openNote(playerId: string | null) {
    setNoteKind("pauta");
    setNoteFor(playerId);
    setNoteOpen(true);
  }

  function openPlan(playerId: string) {
    setNoteKind("plan");
    setNoteFor(playerId);
    setNoteOpen(true);
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;
  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <div className={styles.muted}>Cargando la Daily…</div>;

  const { kpis } = data;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>
            <Sunrise size={22} aria-hidden="true" />
            Daily
          </h1>
          <p className={styles.sub}>
            {categoryName} · reunión de la mañana — lesionados, alertas y pauta del día
          </p>
        </div>
        <div className={styles.dateNav}>
          <button
            className={styles.dateBtn}
            onClick={() => setDate(shiftIso(date, -1))}
            aria-label="Día anterior"
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span className={styles.dateLabel}>
            <CalendarDays size={14} aria-hidden="true" />
            {longDate(date)}
          </span>
          <button
            className={styles.dateBtn}
            onClick={() => setDate(shiftIso(date, 1))}
            disabled={date >= todayIso()}
            aria-label="Día siguiente"
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
          {date !== todayIso() && (
            <button className={styles.todayBtn} onClick={() => setDate(todayIso())}>
              Hoy
            </button>
          )}
          <DownloadPdfButton
            endpoint={`/daily-report.pdf?category_id=${categoryId}&date=${date}`}
            filename={`daily-${date}.pdf`}
            label="Descargar presentación"
          />
        </div>
      </header>

      {/* ── KPI strip ── */}
      <div className={styles.kpis}>
        <Kpi label="Disponibles" value={`${kpis.disponibles.n}/${kpis.disponibles.total}`} />
        <Kpi
          label="No disponibles"
          value={String(kpis.no_disponibles.n)}
          detail={kpis.no_disponibles.breakdown
            .filter((b) => b.n > 0)
            .map((b) => `${b.n} ${b.label}`)
            .join(" · ")}
        />
        <Kpi
          label="Alertas activas"
          value={String(kpis.alertas.critical + kpis.alertas.warning)}
          detail={`${kpis.alertas.critical} críticas · ${kpis.alertas.warning} avisos`}
          tone={kpis.alertas.critical > 0 ? "crit" : kpis.alertas.warning > 0 ? "warn" : "ok"}
        />
        <Kpi
          label="Wellness de hoy"
          value={`${kpis.wellness_hoy.n}/${kpis.wellness_hoy.expected}`}
          detail="check-ins respondidos"
        />
      </div>

      <div className={styles.grid}>
        <main className={styles.main}>
          {/* ── 1 · Lesionados ── */}
          <section aria-labelledby="daily-lesionados">
            <h2 id="daily-lesionados" className={styles.sectionTitle}>
              <span className={styles.sectionNum}>1</span>
              Lesionados y en proceso
              <span className={styles.count}>{data.lesionados.length}</span>
            </h2>
            {data.lesionados.length === 0 ? (
              <p className={styles.emptySection}>Sin jugadores fuera del grupo. 💪</p>
            ) : (
              <div className={styles.cards}>
                {data.lesionados.map((l) => (
                  <LesionadoCard
                    key={l.player_id}
                    row={l}
                    canNote={canNote}
                    onAddNote={(pid) => openNote(pid)}
                    onAddPlan={(pid) => openPlan(pid)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* ── 2 · Alertas ── */}
          <section aria-labelledby="daily-alertas">
            <h2 id="daily-alertas" className={styles.sectionTitle}>
              <span className={styles.sectionNum}>2</span>
              Alertas en disponibles
              <span className={styles.count}>{data.alertas.length}</span>
            </h2>
            {data.alertas.length === 0 ? (
              <p className={styles.emptySection}>Sin alertas activas entre los disponibles.</p>
            ) : (
              <div className={styles.alertList}>
                {data.alertas.map((row) => (
                  <AlertCard key={row.player_id} row={row} canNote={canNote} onAddNote={openNote} onAddPlan={openPlan} />
                ))}
              </div>
            )}
          </section>

          {/* ── 3 · Disponibles (anexo) ── */}
          <section aria-labelledby="daily-disponibles">
            <h2 id="daily-disponibles" className={styles.sectionTitle}>
              <span className={styles.sectionNum}>3</span>
              Disponibles
              <span className={styles.count}>{disponibles.length}</span>
            </h2>
            {roster === null ? (
              <p className={styles.emptySection}>Cargando plantel…</p>
            ) : (
              <RosterTable
                rows={disponibles}
                canEdit={false}
                canDeactivate={false}
                onEdit={() => {}}
                onDeactivate={() => {}}
              />
            )}
          </section>
        </main>

        <aside className={styles.rail}>
          <NotesPanel
            notes={data.notes}
            canNote={canNote}
            onAdd={() => openNote(null)}
            onDeleted={() => setReload((n) => n + 1)}
          />
        </aside>
      </div>

      <NoteModal
        open={noteOpen}
        date={date}
        playerId={noteFor}
        players={data.players}
        departments={data.departments}
        onClose={() => setNoteOpen(false)}
        onSaved={() => setReload((n) => n + 1)}
        kind={noteKind}
        title={noteKind === "plan" ? "Entrada del plan de trabajo" : "Nota de la reunión"}
        placeholder={
          noteKind === "plan"
            ? "Directriz vigente para este jugador — p. ej. bloque de fuerza 3×/semana, progresión de carrera, plan nutricional…"
            : "Qué se decidió para este jugador hoy…"
        }
      />
    </div>
  );
}

// ─── Pieces ─────────────────────────────────────────────────────────────

function Kpi({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "ok" | "warn" | "crit";
}) {
  return (
    <div className={styles.kpi}>
      <span className={styles.kpiLabel}>{label}</span>
      <span className={`${styles.kpiValue} ${tone ? styles[`kpi_${tone}`] : ""}`}>{value}</span>
      {detail && <span className={styles.kpiDetail}>{detail}</span>}
    </div>
  );
}

function AlertCard({
  row,
  canNote,
  onAddNote,
  onAddPlan,
}: {
  row: DailyAlertRow;
  canNote: boolean;
  onAddNote: (playerId: string) => void;
  onAddPlan: (playerId: string) => void;
}) {
  return (
    <div className={`${styles.alertCard} ${row.worst === "critical" ? styles.railCrit : styles.railWarn}`}>
      <div className={styles.alertHead}>
        <Link href={`/perfil/${row.player_id}`} className={styles.alertName}>
          {row.name}
          <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
        {canNote && (
          <span className={styles.alertBtns}>
            <button className={styles.alertNoteBtn} onClick={() => onAddNote(row.player_id)}>
              Nota
            </button>
            <button className={styles.alertNoteBtn} onClick={() => onAddPlan(row.player_id)}>
              Plan
            </button>
          </span>
        )}
      </div>
      <ul className={styles.alertMsgs}>
        {row.alerts.map((a, i) => (
          <li key={i} className={a.severity === "critical" ? styles.msgCrit : styles.msgWarn}>
            <AlertTriangle size={12} aria-hidden="true" />
            {a.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
