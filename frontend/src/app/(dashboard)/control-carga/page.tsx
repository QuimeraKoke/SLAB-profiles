"use client";

/**
 * Control de carga — the staff's plan per microcycle and, next, how the GPS
 * compares with it (PLAN_CONTROL_CARGA.md). The team comes from the global
 * picker: the selected category's competition this season (Serie 2008 → U18),
 * shown in a chip so it is clear which team is being planned (IA principle 5).
 * Tab and microcycle live in the URL (`?tab=`, `?mc=`).
 */

import React, { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import EvaluationView from "@/components/loadControl/EvaluationView";
import NewMicrocycleModal from "@/components/loadControl/NewMicrocycleModal";
import PlanEditor from "@/components/loadControl/PlanEditor";
import { FORMATIVO_TAB_IDS } from "@/components/loadControl/FormativoPanels";
import ProfileTabs, { panelIdFor } from "@/components/perfil/ProfileTabs/ProfileTabs";
import { useToast } from "@/components/ui/Toast/Toast";
import { useCategoryContext } from "@/context/CategoryContext";
import { api, ApiError } from "@/lib/api";
import { kindLabel, shortDate, STATUS_LABEL, type TeamPayload } from "@/lib/loadControl";
import { usePermission } from "@/lib/permissions";

import styles from "@/components/loadControl/loadControl.module.css";

const TABS = [
  { id: "carga", label: "Carga GPS" },
  { id: "planificacion", label: "Planificación" },
];

export default function ControlCargaPage() {
  const { categoryId, loading: catLoading } = useCategoryContext();
  const canAdd = usePermission("load_control.add_microcycle");
  const canEdit = usePermission("load_control.change_microcycle");
  const { toast } = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : TABS[0].id;
  // The squad panels moved to the Centro de mando (2026-11-04): old links follow.
  const moved = FORMATIVO_TAB_IDS.has(params.get("tab") ?? "");
  useEffect(() => {
    if (moved) router.replace(`/centro-de-mando?${params.toString()}`);
  }, [moved, params, router]);
  const mcParam = params.get("mc") ?? "";
  // Carga GPS filters, in the URL like the tab (refresh-safe, shareable).
  const dayParam = params.get("dia");
  const sparringParam = params.get("sparring");
  const matchesParam = params.get("partidos") !== "0";

  const [team, setTeam] = useState<TeamPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [reload, setReload] = useState(0);

  const setUrl = useCallback((changes: Record<string, string | null>) => {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(changes)) {
      if (v) sp.set(k, v); else sp.delete(k);
    }
    router.replace(`${pathname}?${sp.toString()}`, { scroll: false });
  }, [params, pathname, router]);

  useEffect(() => {
    if (catLoading || !categoryId) return;
    let cancelled = false;
    api<TeamPayload>(`/load-control/team?category_id=${categoryId}`)
      .then((t) => { if (!cancelled) { setTeam(t); setError(null); } })
      .catch((e) => {
        if (cancelled) return;
        setTeam(null);
        setError(e instanceof ApiError ? e.message : "No se pudo cargar el equipo.");
      });
    return () => { cancelled = true; };
  }, [categoryId, catLoading, reload]);

  const selected = team?.microcycles.find((m) => m.id === mcParam) ?? team?.microcycles[0] ?? null;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Control de carga</h1>
          <p className={styles.subtitle}>
            {tab === "carga" ? "¿Cumplieron lo planificado? Real vs objetivo por jugador, contra el plan de la semana."
              : "¿Cuánto debe hacer cada posición cada día? Se define como % de la carga de partido."}
          </p>
        </div>
        {team && (
          <div className={styles.controls}>
            {team.microcycles.length > 0 && (
              <label className={styles.label}>
                Semana
                <select className={styles.select} value={selected?.id ?? ""}
                  onChange={(e) => setUrl({ mc: e.target.value, dia: null })}>
                  {team.microcycles.map((m) => (
                    <option key={m.id} value={m.id}>
                      Semana {m.number} · {shortDate(m.start_date)} · {kindLabel(m.kind)} · {STATUS_LABEL[m.status]}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {canAdd && (
              <button type="button" className={styles.primary} onClick={() => setCreating(true)}>
                Nueva semana
              </button>
            )}
          </div>
        )}
      </header>

      {team && (
        <span className={styles.chip}>
          Mostrando {team.label} {team.season} · {team.categories.join(" + ")}
        </span>
      )}
      {error && <div className={styles.error} role="alert">{error}</div>}

      <ProfileTabs tabs={TABS} activeTab={tab} onTabChange={(t) => setUrl({ tab: t })} />
      <div role="tabpanel" id={panelIdFor(tab)} aria-labelledby={`tab-${tab}`} style={{ display: "contents" }}>
        {team && tab === "carga" && (
          selected
            ? <EvaluationView key={selected.id} microcycleId={selected.id}
                day={dayParam} sparring={sparringParam === null ? null : sparringParam === "1"}
                matches={matchesParam}
                onFilters={(f) => setUrl({
                  ...(f.day !== undefined ? { dia: f.day } : {}),
                  ...(f.sparring !== undefined ? { sparring: f.sparring === null ? null : f.sparring ? "1" : "0" } : {}),
                  ...(f.matches !== undefined ? { partidos: f.matches ? null : "0" } : {}),
                })} />
            : <div className={styles.empty}>Planifica una semana para ver la carga contra su objetivo.</div>
        )}
        {team && tab === "planificacion" && (
          selected
            ? <PlanEditor key={selected.id} microcycleId={selected.id} canEdit={canEdit}
                onChanged={() => setReload((n) => n + 1)} />
            : <div className={styles.empty}>
                {team.label} todavía no tiene semanas planificadas.
                {canAdd ? " Crea la primera con “Nueva semana”." : ""}
              </div>
        )}
      </div>

      {team && categoryId && creating && (
        <NewMicrocycleModal open={creating} categoryId={categoryId} season={team.season}
          teamLabel={team.label} microcycles={team.microcycles}
          onClose={() => setCreating(false)}
          onCreated={(mc) => {
            setCreating(false);
            toast.success(`Semana ${mc.number} creada.`);
            setReload((n) => n + 1);
            setUrl({ mc: mc.id });
          }} />
      )}
    </div>
  );
}
