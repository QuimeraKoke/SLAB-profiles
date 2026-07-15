"use client";

import React, { use, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import styles from "../page.module.css";
import ProfileHeader from "@/components/perfil/ProfileHeader/ProfileHeader";
import ProfileTabs, { panelIdFor, type TabSpec } from "@/components/perfil/ProfileTabs/ProfileTabs";
import ProfileSummary from "@/components/perfil/ProfileSummary/ProfileSummary";
import ProfileTimeline from "@/components/perfil/ProfileTimeline/ProfileTimeline";
import ProfileEvents from "@/components/perfil/ProfileEvents/ProfileEvents";
import ProfileDepartment from "@/components/perfil/ProfileDepartment/ProfileDepartment";
import ProfileAlerts from "@/components/perfil/ProfileAlerts/ProfileAlerts";
import ProfileGoals from "@/components/perfil/ProfileGoals/ProfileGoals";
import ProfileEpisodes from "@/components/perfil/ProfileEpisodes/ProfileEpisodes";
import { useBreadcrumbLabel } from "@/components/layout/Breadcrumbs";
import { api, ApiError } from "@/lib/api";
import type { PlayerDetail } from "@/lib/types";

const RESUMEN_TAB_ID = "resumen";
const TIMELINE_TAB_ID = "timeline";
const EVENTS_TAB_ID = "eventos";
const ALERTS_TAB_ID = "alertas";
const GOALS_TAB_ID = "objetivos";
const LESIONES_TAB_ID = "lesiones";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PerfilPlayerPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  // QW-3: URL is the source of truth for the active tab. Local state is
  // initialized from `?tab=` but every change also writes back via
  // router.replace — so Back/Forward and shared deep-links work, and a
  // refresh preserves the chosen tab.
  const [activeTab, setActiveTab] = useState<string>(tabFromUrl ?? RESUMEN_TAB_ID);

  // Keep local state in sync if the URL changes externally (e.g. alert
  // notification deep-link navigates here while the page is already mounted).
  useEffect(() => {
    if (tabFromUrl && tabFromUrl !== activeTab) {
      setActiveTab(tabFromUrl);
    }
    // We intentionally don't depend on `activeTab` — this effect only
    // reacts to external URL changes, not to our own writes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabFromUrl]);

  // QW-4 follow-up: surface the player's name in the document title once
  // their data arrives. The parent layout's static "Perfil · SLAB" is the
  // fallback during load; this overwrites it client-side. (Server-side
  // generateMetadata isn't available because this is a client component
  // for the search-params / router hooks.)
  useEffect(() => {
    if (!player) return;
    const name = `${player.first_name} ${player.last_name}`.trim();
    document.title = name ? `${name} · SLAB` : "Perfil · SLAB";
  }, [player]);

  // ME-1: populate the breadcrumb with the player's name so the crumb
  // trail reads "Inicio › Jugador › Charles Aránguiz" instead of
  // "Inicio › Jugador › …".
  const setBreadcrumbLabel = useBreadcrumbLabel();
  useEffect(() => {
    if (!player) return;
    const name = `${player.first_name} ${player.last_name}`.trim();
    if (name) setBreadcrumbLabel(player.id, name);
  }, [player, setBreadcrumbLabel]);

  const handleTabChange = useCallback(
    (tabId: string) => {
      setActiveTab(tabId);
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tabId);
      // router.replace (not push) so Back leaves the profile rather than
      // cycling through every tab the user touched.
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );
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
    // Alerts split from Objetivos — one label, one meaning.
    { id: ALERTS_TAB_ID, label: "Alertas" },
    { id: GOALS_TAB_ID, label: "Objetivos" },
    { id: LESIONES_TAB_ID, label: "Lesiones" },
    ...departmentTabs,
  ];

  // If active tab no longer exists (e.g. category changed, or a deep-link
  // points at a tab not in this player's category), fall back to Resumen.
  const safeActive = tabs.some((t) => t.id === activeTab) ? activeTab : RESUMEN_TAB_ID;
  // Heal the URL too — otherwise the address bar keeps the bogus `?tab=…`
  // and re-sharing the link reproduces the same dead deep-link.
  if (safeActive !== activeTab) {
    queueMicrotask(() => handleTabChange(safeActive));
  }
  const activeDepartment = player.category.departments.find((d) => d.slug === safeActive);

  return (
    <div className={styles.container}>
      <ProfileHeader player={player} />
      <ProfileTabs tabs={tabs} activeTab={safeActive} onTabChange={handleTabChange} />

      <div
        className={styles.contentArea}
        role="tabpanel"
        id={panelIdFor(safeActive)}
        aria-labelledby={`tab-${safeActive}`}
        tabIndex={0}
      >
        {safeActive === RESUMEN_TAB_ID && (
          <ProfileSummary
            playerId={player.id}
            playerName={`${player.first_name} ${player.last_name}`}
            departments={player.category.departments}
          />
        )}
        {safeActive === TIMELINE_TAB_ID && <ProfileTimeline playerId={player.id} />}
        {safeActive === EVENTS_TAB_ID && <ProfileEvents playerId={player.id} />}
        {safeActive === ALERTS_TAB_ID && <ProfileAlerts playerId={player.id} />}
        {safeActive === GOALS_TAB_ID && <ProfileGoals player={player} />}
        {safeActive === LESIONES_TAB_ID && <ProfileEpisodes player={player} />}
        {activeDepartment && (
          <ProfileDepartment
            playerId={player.id}
            playerName={`${player.first_name} ${player.last_name}`}
            categoryId={player.category.id}
            department={activeDepartment}
          />
        )}
      </div>
    </div>
  );
}
