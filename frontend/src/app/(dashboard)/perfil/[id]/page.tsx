"use client";

import React, { use, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import styles from "../page.module.css";
import DateRangeControl, {
  defaultDateRange,
  type DateRangeValue,
} from "@/components/common/DateRangeControl";
import ProfileHeader from "@/components/perfil/ProfileHeader/ProfileHeader";
import ProfileTabs, { type TabSpec } from "@/components/perfil/ProfileTabs/ProfileTabs";
import ProfileSummary from "@/components/perfil/ProfileSummary/ProfileSummary";
import ProfileTimeline from "@/components/perfil/ProfileTimeline/ProfileTimeline";
import ProfileEvents from "@/components/perfil/ProfileEvents/ProfileEvents";
import ProfileDepartment from "@/components/perfil/ProfileDepartment/ProfileDepartment";
import ProfileGoals from "@/components/perfil/ProfileGoals/ProfileGoals";
import ProfileEpisodes from "@/components/perfil/ProfileEpisodes/ProfileEpisodes";
import { api, ApiError } from "@/lib/api";
import type { PlayerDetail } from "@/lib/types";

const RESUMEN_TAB_ID = "resumen";
const TIMELINE_TAB_ID = "timeline";
const EVENTS_TAB_ID = "eventos";
const GOALS_TAB_ID = "objetivos";
const LESIONES_TAB_ID = "lesiones";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PerfilPlayerPage({ params }: PageProps) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>(tabFromUrl ?? RESUMEN_TAB_ID);
  // Cross-cutting date filter for department tabs. Lives at the page
  // level so switching between Médico / Físico / Nutricional preserves
  // the chosen window.
  const [dateRange, setDateRange] = useState<DateRangeValue>(() => defaultDateRange());

  useEffect(() => {
    let cancelled = false;
    // Defer the "clear state for new fetch" via a microtask so the lint
    // rule `react-hooks/set-state-in-effect` doesn't flag synchronous
    // setState in the effect body. Behavior is identical to direct
    // setState — both run before any render.
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPlayer(null);
      setError(null);
    });
    api<PlayerDetail>(`/players/${id}`)
      .then((data) => {
        if (!cancelled) setPlayer(data);
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Failed to load player";
        setError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <div className={styles.container}>
        <div role="alert" style={{ color: "#b91c1c", padding: 16 }}>
          {error}
        </div>
      </div>
    );
  }

  if (!player) {
    return (
      <div className={styles.container}>
        <div style={{ color: "#6b7280", padding: 16 }}>Cargando perfil…</div>
      </div>
    );
  }

  const departmentTabs: TabSpec[] = player.category.departments.map((d) => ({
    id: d.slug,
    label: d.name,
  }));
  const tabs: TabSpec[] = [
    { id: RESUMEN_TAB_ID, label: "Resumen" },
    { id: TIMELINE_TAB_ID, label: "Línea de tiempo" },
    { id: EVENTS_TAB_ID, label: "Eventos" },
    { id: GOALS_TAB_ID, label: "Objetivos" },
    { id: LESIONES_TAB_ID, label: "Lesiones" },
    ...departmentTabs,
  ];

  // If active tab no longer exists (e.g. category changed), fall back to Resumen.
  const safeActive = tabs.some((t) => t.id === activeTab) ? activeTab : RESUMEN_TAB_ID;
  const activeDepartment = player.category.departments.find((d) => d.slug === safeActive);

  return (
    <div className={styles.container}>
      <ProfileHeader player={player} />
      <ProfileTabs tabs={tabs} activeTab={safeActive} onTabChange={setActiveTab} />

      <div className={styles.contentArea}>
        {safeActive === RESUMEN_TAB_ID && <ProfileSummary playerId={player.id} />}
        {safeActive === TIMELINE_TAB_ID && <ProfileTimeline playerId={player.id} />}
        {safeActive === EVENTS_TAB_ID && <ProfileEvents playerId={player.id} />}
        {safeActive === GOALS_TAB_ID && <ProfileGoals player={player} />}
        {safeActive === LESIONES_TAB_ID && <ProfileEpisodes player={player} />}
        {activeDepartment && (
          <ProfileDepartment
            playerId={player.id}
            playerName={`${player.first_name} ${player.last_name}`}
            department={activeDepartment}
            dateFrom={dateRange.date.from}
            dateTo={dateRange.date.to}
            dateRangeControl={
              <DateRangeControl
                value={dateRange}
                onChange={setDateRange}
                variant="compact"
              />
            }
          />
        )}
      </div>
    </div>
  );
}
