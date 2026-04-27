"use client";

import React, { use, useEffect, useState } from "react";
import styles from "../page.module.css";
import ProfileHeader from "@/components/perfil/ProfileHeader/ProfileHeader";
import ProfileTabs, { type TabSpec } from "@/components/perfil/ProfileTabs/ProfileTabs";
import ProfileSummary from "@/components/perfil/ProfileSummary/ProfileSummary";
import ProfileTimeline from "@/components/perfil/ProfileTimeline/ProfileTimeline";
import ProfileDepartment from "@/components/perfil/ProfileDepartment/ProfileDepartment";
import { api, ApiError } from "@/lib/api";
import type { PlayerDetail } from "@/lib/types";

const RESUMEN_TAB_ID = "resumen";
const TIMELINE_TAB_ID = "timeline";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PerfilPlayerPage({ params }: PageProps) {
  const { id } = use(params);
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>(RESUMEN_TAB_ID);

  useEffect(() => {
    let cancelled = false;
    setPlayer(null);
    setError(null);
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
        {safeActive === RESUMEN_TAB_ID && <ProfileSummary />}
        {safeActive === TIMELINE_TAB_ID && <ProfileTimeline playerId={player.id} />}
        {activeDepartment && (
          <ProfileDepartment playerId={player.id} department={activeDepartment} />
        )}
      </div>
    </div>
  );
}
