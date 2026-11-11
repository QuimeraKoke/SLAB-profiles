"use client";

import React, { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import EvaluationGrid from "@/components/command/EvaluationGrid";
import WellnessRoleTabs, { ROLE_LABEL } from "@/components/command/WellnessRoleTabs";
import FormativoPanels, {
  FORMATIVO_QUESTION, FORMATIVO_TABS, PERIOD_TABS, STRIP_TABS,
} from "@/components/loadControl/FormativoPanels";
import PeriodBar, { isCalendarWeek } from "@/components/loadControl/PeriodBar";
import ProfileTabs, { panelIdFor } from "@/components/perfil/ProfileTabs/ProfileTabs";
import type { DayNav } from "@/lib/loadControl";
import type {
  CommandCenter,
  CCDataQualityRow,
  CCRecentItem,
  CCCheckinAdherence,
  WellnessRoleId,
} from "@/components/command/types";
import styles from "./page.module.css";
import { PlayerName, PlayerPhotosProvider } from "@/components/loadControl/PlayerPhotos";

export default function CommandCenterPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const [data, setData] = useState<CommandCenter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  // The check-in/check-out choice lives in the URL, like every other tab in
  // the app: bookmarkable, refresh-safe and deep-linkable from an alert.
  const roles = data?.wellness_roles ?? ["checkin"];
  const requested = params.get("wellness");
  const wellnessRole: WellnessRoleId =
    requested === "checkout" && roles.includes("checkout") ? "checkout" : "checkin";

  const setWellnessRole = useMemo(
    () => (role: WellnessRoleId) => {
      const next = new URLSearchParams(params.toString());
      if (role === "checkin") next.delete("wellness");
      else next.set("wellness", role);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  // Formativo (a category that competes in a bracket): the club's panels as
  // tabs, read day by day. `/load-control/day` 404s elsewhere (Primer Equipo),
  // and the page stays as it was.
  const [today] = useState(() => {
    const t = new Date();
    return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
  });
  // ONE time control: the period (the Mon–Sun week of `?dia`, or any
  // `?desde=&hasta=`) and the day chosen inside it (`?dia`, default today —
  // or the last day of a past period).
  const dayParam = params.get("dia");
  const [nav, setNav] = useState<DayNav | null>(null);
  const tabs = useMemo(() => (nav ? [{ id: "general", label: "Centro de mando" }, ...FORMATIVO_TABS] : []), [nav]);
  const tab = tabs.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "general";
  const desde = params.get("desde");
  const hasta = params.get("hasta");
  const range = desde && hasta ? { start: desde, end: hasta } : null;
  const setUrl = useMemo(
    () => (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(changes)) {
        if (v) next.set(k, v); else next.delete(k);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );
  // Bookmarks from before the single time control: the panels' own toggles
  // (`molestias`, `carga_vista`, `periodo=temporada`) are gone.
  useEffect(() => {
    const old = ["molestias", "carga_vista", "periodo"].filter((k) => params.has(k));
    if (!old.length) return;
    const changes: Record<string, string | null> = Object.fromEntries(old.map((k) => [k, null]));
    if (params.get("periodo") === "temporada" && !range) {
      changes.desde = `${today.slice(0, 4)}-01-01`;
      changes.hasta = today;
    }
    setUrl(changes);
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  const onPeriod = (a: string, b: string, d: string) => {
    const dia = d === today ? null : d;
    // A Mon–Sun week is "the week" (planned or not), not a period.
    if (isCalendarWeek(a, b)) setUrl({ desde: null, hasta: null, dia });
    else setUrl({ desde: a, hasta: b, dia });
  };

  // Carga GPS lives in Control de carga (the plan): link there, same week/day.
  const goTab = (t: string, extra?: Record<string, string | null>) => {
    if (t === "carga") {
      const sp = new URLSearchParams({ tab: "carga" });
      if (nav?.microcycle_id) { sp.set("mc", nav.microcycle_id); sp.set("dia", nav.day); }
      router.push(`/control-carga?${sp}`);
      return;
    }
    setUrl({ tab: t, ...(extra ?? {}) });
  };

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    const period = range ? `&start=${range.start}&end=${range.end}` : "";
    const day = dayParam ?? (range ? "" : today);
    api<DayNav>(`/load-control/day?category_id=${categoryId}${day ? `&day=${day}` : ""}${period}`)
      .then((n) => { if (!cancelled) setNav(n); })
      .catch(() => { if (!cancelled) setNav(null); });
    return () => { cancelled = true; };
  }, [categoryId, dayParam, range?.start, range?.end]); // eslint-disable-line react-hooks/exhaustive-deps

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
  if (!categoryId) return <div className={styles.muted}>Selecciona una categoría.</div>;
  if (error) return <div className={styles.error} role="alert">{error}</div>;
  if (!data) return <div className={styles.muted}>Cargando centro de mando…</div>;

  return (
    <PlayerPhotosProvider categoryId={categoryId}>
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

      {nav && (
        <ProfileTabs tabs={tabs} activeTab={tab} onTabChange={(t) => setUrl({ tab: t === "general" ? null : t })} />
      )}
      {nav && tab !== "general" && categoryId && (
        <div role="tabpanel" id={panelIdFor(tab)} aria-labelledby={`tab-${tab}`} className={styles.stack}>
          <p className={styles.sub}>
            {FORMATIVO_QUESTION[tab]} <span className={styles.muted}>· {nav.team.label} {nav.team.season} · {nav.team.categories.join(" + ")}</span>
          </p>
          {PERIOD_TABS.has(tab) && (
            <PeriodBar nav={nav} categoryId={categoryId} today={today} strip={STRIP_TABS.has(tab)}
              onPeriod={onPeriod} onDay={(d) => setUrl({ dia: d === today ? null : d })} />
          )}
          <FormativoPanels tab={tab} nav={nav} categoryId={categoryId} params={params} setUrl={setUrl} goTab={goTab} />
        </div>
      )}

      {(!nav || tab === "general") && <div className={styles.stack}>
        {/* Full-width hero + KPI strip across the whole canvas. */}
        <Hero context={data.context} />
        <KpiStrip
          kpis={data.kpis}
          wellnessRoles={roles}
          wellnessRole={wellnessRole}
          checkoutWellness={data.checkout?.wellness}
          onWellnessRoleChange={setWellnessRole}
        />

        {/* Formativo: every player's last physical test against the
            category's bands — in its own tab when the formativo panels are
            on. Renders nothing where there are no bands (Primer Equipo). */}
        {!nav && <EvaluationGrid categoryId={categoryId} />}

        {/* Below: main column + rail (Estado del plantel moved down here). */}
        <div className={styles.grid}>
          <main className={styles.main}>
            <DecisionTable decisions={data.decisions} />
          </main>

          <aside className={styles.rail}>
            <SquadStatus squad={data.squad} />
            <CheckinAdherence
              data={
                wellnessRole === "checkout" && data.checkout
                  ? data.checkout.adherence
                  : data.checkin_adherence
              }
              roles={roles}
              role={wellnessRole}
              onRoleChange={setWellnessRole}
            />
            <DataQuality rows={data.data_quality} />
            <QuickActions />
            <RecentActivity items={data.recent} />
          </aside>
        </div>
      </div>}
    </div>
    </PlayerPhotosProvider>
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

function CheckinAdherence({
  data, roles, role, onRoleChange,
}: {
  data: CCCheckinAdherence;
  roles: WellnessRoleId[];
  role: WellnessRoleId;
  onRoleChange: (r: WellnessRoleId) => void;
}) {
  const { responded, expected, pct, no_respondieron, respondieron } = data;
  const tone = pct == null ? "muted" : pct >= 90 ? "ok" : pct >= 60 ? "warn" : "crit";
  const [openMissing, setOpenMissing] = useState(true);
  const [openDone, setOpenDone] = useState(false);
  return (
    <div className={styles.railCard}>
      <div className={styles.railHead}>
        <HeartPulse size={15} aria-hidden="true" />
        {roles.length > 1
          ? `Adherencia al ${ROLE_LABEL[role].toLowerCase()} de hoy`
          : "Adherencia al check-in de hoy"}
      </div>
      <WellnessRoleTabs
        roles={roles}
        active={role}
        onChange={onRoleChange}
        label="Adherencia de hoy"
      />
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
                <span className={styles.adhName}><PlayerName id={p.player_id} name={p.name} size={32} /></span>
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
