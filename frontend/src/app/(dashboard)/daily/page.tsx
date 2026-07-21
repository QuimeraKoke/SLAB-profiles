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
  History,
  Sparkles,
  Sunrise,
} from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { usePermission } from "@/lib/permissions";
import DownloadPdfButton from "@/components/reports/DownloadPdfButton";
import RosterTable, { RosterRow } from "@/components/equipo/RosterTable";
import LesionadoCard from "@/components/daily/LesionadoCard";
import KineTable from "@/components/daily/KineTable";
import NoteModal from "@/components/daily/NoteModal";
import NotesPanel from "@/components/daily/NotesPanel";
import PlansPanel from "@/components/daily/PlansPanel";
import PlanList from "@/components/daily/PlanList";
import type {
  DailyAlertRow,
  DailyNote,
  DailyReport,
  DailySummaryPayload,
} from "@/components/daily/types";
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

function relDays(iso: string): string {
  const then = new Date(`${iso}T12:00:00`).getTime();
  const now = new Date(`${todayIso()}T12:00:00`).getTime();
  const n = Math.round((now - then) / 86_400_000);
  if (n <= 0) return "hoy";
  if (n === 1) return "ayer";
  return `hace ${n} días`;
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
  const [summary, setSummary] = useState<DailySummaryPayload | null>(null);
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
      if (!cancelled) {
        setError(null);
        setSummary(null);
      }
    });
    api<DailyReport>(`/daily-report?category_id=${categoryId}&date=${date}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "No se pudo cargar la Daily.");
      });
    // AI recap — separate call so the page renders without waiting on the model.
    api<DailySummaryPayload>(`/daily-report/summary?category_id=${categoryId}&date=${date}`)
      .then((d) => { if (!cancelled) setSummary(d); })
      .catch(() => { /* best-effort — the Daily renders without it */ });
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

  // Flat list of the squad's standing plans (from the per-player map) for the
  // rail panel — by player name, newest entry first.
  const planRows = useMemo(
    () =>
      Object.values(data?.plans ?? {})
        .flat()
        .sort(
          (a, b) =>
            a.player_name.localeCompare(b.player_name) || b.date.localeCompare(a.date),
        ),
    [data?.plans],
  );

  const categoryName =
    categories.find((c) => c.id === categoryId)?.name ?? data?.category ?? "";

  function openNote(playerId: string | null) {
    setNoteKind("pauta");
    setNoteFor(playerId);
    setNoteOpen(true);
  }

  function openPlan(playerId: string | null) {
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

      {/* ── Resumen IA del día (solo días completos, guardado) ── */}
      {summary?.text && (
        <section className={styles.aiSummary} aria-label="Resumen del día generado por IA">
          <div className={styles.aiHead}>
            <Sparkles size={15} aria-hidden="true" />
            Resumen del día · IA
          </div>
          <div className={styles.aiBody}>{summary.text}</div>
        </section>
      )}

      {/* ── Recap del último daily (fila full-width, clickeable) ── */}
      {data.last_daily && (
        <button
          type="button"
          className={styles.recap}
          onClick={() => setDate(data.last_daily!.date)}
          title="Ir al último daily"
        >
          <span className={styles.recapMain}>
            <History size={15} aria-hidden="true" />
            Último daily · <strong>{longDate(data.last_daily.date)}</strong>
            <span className={styles.recapAgo}>{relDays(data.last_daily.date)}</span>
          </span>
          <span className={styles.recapStats}>
            {data.last_daily.notes} nota{data.last_daily.notes === 1 ? "" : "s"} de pauta
            {" · "}
            {data.last_daily.kine} en plan kinésico
            {" · "}
            wellness {data.last_daily.wellness_responded}/{data.last_daily.wellness_expected}
          </span>
          <ChevronRight size={16} aria-hidden="true" className={styles.recapChevron} />
        </button>
      )}

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
          label="Wellness del día"
          value={`${kpis.wellness_hoy.n}/${kpis.wellness_hoy.expected}`}
          detail="check-ins respondidos"
        />
      </div>

      {/* ── No respondieron el check-in (informativo — para ir a llamarlos) ── */}
      {kpis.wellness_hoy.no_respondieron.length > 0 && (
        <div className={styles.noResp}>
          <span className={styles.noRespTitle}>
            No respondieron el check-in
            <span className={styles.noRespCount}>
              {kpis.wellness_hoy.no_respondieron.length}
            </span>
          </span>
          <div className={styles.noRespList}>
            {kpis.wellness_hoy.no_respondieron.map((p) => (
              <Link
                key={p.player_id}
                href={`/perfil/${p.player_id}`}
                className={styles.noRespChip}
              >
                {p.name}
                {p.injured && <span className={styles.noRespInjured}>lesionado</span>}
              </Link>
            ))}
          </div>
        </div>
      )}

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
                    plans={data.plans?.[l.player_id] ?? []}
                    onChanged={() => setReload((n) => n + 1)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* ── 2 · Plan kinésico ── */}
          <section aria-labelledby="daily-kine">
            <h2 id="daily-kine" className={styles.sectionTitle}>
              <span className={styles.sectionNum}>2</span>
              Plan kinésico
            </h2>
            <KineTable
              date={date}
              injured={data.lesionados}
              entries={data.kine}
              players={data.players}
            />
          </section>

          {/* ── 3 · Alertas ── */}
          <section aria-labelledby="daily-alertas">
            <h2 id="daily-alertas" className={styles.sectionTitle}>
              <span className={styles.sectionNum}>3</span>
              Alertas en disponibles
              <span className={styles.count}>{data.alertas.length}</span>
            </h2>
            {data.alertas.length === 0 ? (
              <p className={styles.emptySection}>Sin alertas activas entre los disponibles.</p>
            ) : (
              <div className={styles.alertList}>
                {data.alertas.map((row) => (
                  <AlertCard
                    key={row.player_id}
                    row={row}
                    canNote={canNote}
                    onAddNote={openNote}
                    onAddPlan={openPlan}
                    plans={data.plans?.[row.player_id] ?? []}
                    onChanged={() => setReload((n) => n + 1)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* ── 4 · Disponibles (anexo) ── */}
          <section aria-labelledby="daily-disponibles">
            <h2 id="daily-disponibles" className={styles.sectionTitle}>
              <span className={styles.sectionNum}>4</span>
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
          <PlansPanel
            plans={planRows}
            canNote={canNote}
            onAdd={() => openPlan(null)}
            onChanged={() => setReload((n) => n + 1)}
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
  plans,
  onChanged,
}: {
  row: DailyAlertRow;
  canNote: boolean;
  onAddNote: (playerId: string) => void;
  onAddPlan: (playerId: string) => void;
  plans: DailyNote[];
  onChanged: () => void;
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
      {plans.length > 0 && (
        <div className={styles.alertPlan}>
          <PlanList plans={plans} canNote={canNote} onChanged={onChanged} />
        </div>
      )}
    </div>
  );
}
