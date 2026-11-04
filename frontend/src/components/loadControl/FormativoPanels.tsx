"use client";

/**
 * The formativo's panels for the club's 9 questions (PLAN_CONTROL_CARGA.md),
 * shown as tabs of the Centro de mando for categories that compete in a
 * bracket (U20, U18…). Control de carga keeps only what is about the plan
 * (Carga GPS and Planificación); everything about the squad lives here.
 *
 * Weekly panels read the calendar week holding the selected day (`?dia=`,
 * moved with "día anterior / siguiente" — planned or not); the non-weekly
 * ones (Evaluaciones, Composición) read the selected category.
 * Tab, week and every filter live in the URL (IA principle 2).
 */

import React from "react";

import EvaluationGrid from "@/components/command/EvaluationGrid";
import AvailabilityView from "@/components/loadControl/AvailabilityView";
import CompositionView from "@/components/loadControl/CompositionView";
import DayLoadChart from "@/components/loadControl/DayLoadChart";
import FatigueView from "@/components/loadControl/FatigueView";
import ParticipationView from "@/components/loadControl/ParticipationView";
import PlayerView from "@/components/loadControl/PlayerView";
import SummaryView from "@/components/loadControl/SummaryView";
import WellnessView from "@/components/loadControl/WellnessView";
import { type DayNav, shortDate } from "@/lib/loadControl";

import styles from "@/components/loadControl/loadControl.module.css";

export const FORMATIVO_TABS = [
  { id: "resumen", label: "Resumen" },
  { id: "fatiga", label: "Fatiga post-partido" },
  { id: "bienestar", label: "Check-in / out" },
  { id: "lesiones", label: "Kinesia y lesiones" },
  { id: "minutos", label: "Minutos y entrenamientos" },
  { id: "jugador", label: "Jugador" },
  { id: "evaluaciones", label: "Evaluaciones" },
  { id: "composicion", label: "Composición corporal" },
];
export const FORMATIVO_TAB_IDS = new Set(FORMATIVO_TABS.map((t) => t.id));
const NOT_WEEKLY = new Set(["evaluaciones", "composicion"]);

export const FORMATIVO_QUESTION: Record<string, string> = {
  resumen: "¿Cómo está el plantel esta semana? ¿A quién compensar? ¿Quién llega fatigado?",
  fatiga: "¿Cuánto les pegó el último partido y cómo llegan al que viene?",
  bienestar: "¿Cómo llegan, cómo se sienten, qué les molesta y cómo se van?",
  lesiones: "¿Quién está en readaptación o en clínica, desde cuándo y cuándo vuelve?",
  minutos: "¿Cuánto jugó cada uno y a cuántas sesiones fue?",
  jugador: "¿Cómo viene esta persona en todo esta semana?",
  evaluaciones: "¿Qué tan fuerte, rápido y resistente es cada uno, frente al grupo y frente a su evaluación anterior?",
  composicion: "¿Cómo evolucionan el músculo, la grasa y los pliegues de cada uno?",
};

const WEEKDAY = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];

/** ISO day ± n, in local calendar terms. */
export function shiftDay(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "‹ Día anterior · Miércoles 28 oct · MD-3 · Semana 42 · Día siguiente ›" —
 *  the only way to move: day by day, across weeks, planned or not. */
export function DayNavBar({ nav, onDay, today }: { nav: DayNav; onDay: (iso: string) => void; today: string }) {
  const d = new Date(`${nav.day}T12:00:00`);
  return (
    <div className={styles.controls} role="group" aria-label="Día">
      <button type="button" className={styles.secondary} onClick={() => onDay(shiftDay(nav.day, -1))}
        aria-label={`Día anterior: ${shiftDay(nav.day, -1)}`}>‹ Día anterior</button>
      <span>
        <strong>{WEEKDAY[d.getDay()]} {shortDate(nav.day)}</strong>
        {nav.md_label && <> · {nav.md_label}</>}
        <span className={styles.muted}>
          {" "}· Semana {nav.number} ({shortDate(nav.start_date)}–{shortDate(nav.end_date)}){nav.planned ? "" : " · sin planificar"}
        </span>
      </span>
      <button type="button" className={styles.secondary} onClick={() => onDay(shiftDay(nav.day, 1))}
        aria-label={`Día siguiente: ${shiftDay(nav.day, 1)}`}>Día siguiente ›</button>
      {nav.day !== today && (
        <button type="button" className={styles.linkButton} onClick={() => onDay(today)}>Hoy</button>
      )}
    </div>
  );
}

export const isWeekly = (tab: string) => !NOT_WEEKLY.has(tab);

interface Props {
  tab: string;
  /** The day navigator's answer: which week holds the selected day. */
  nav: DayNav;
  categoryId: string;
  params: URLSearchParams;
  setUrl: (changes: Record<string, string | null>) => void;
  /** Go to a tab — this page's, or Control de carga's (Carga GPS). */
  goTab: (tab: string, extra?: Record<string, string | null>) => void;
}

export default function FormativoPanels({ tab, nav, categoryId, params, setUrl, goTab }: Props) {
  // Planned week → its id; otherwise the "<day>_<category>" key the API
  // resolves to the calendar week, built on the fly (`load_control.week`).
  const week = nav.microcycle_id ?? nav.week_key;

  if (tab === "evaluaciones") return <EvaluationGrid categoryId={categoryId} />;
  if (tab === "composicion") {
    return (
      <CompositionView categoryId={categoryId} playerId={params.get("jugador")}
        metric={params.get("metrica")} sort={params.get("orden")}
        onFilters={(f) => setUrl({
          ...(f.player !== undefined ? { jugador: f.player } : {}),
          ...(f.metric !== undefined ? { metrica: f.metric } : {}),
          ...(f.sort !== undefined ? { orden: f.sort } : {}),
        })} />
    );
  }

  switch (tab) {
    case "resumen":
      return <SummaryView key={week} microcycleId={week} onTab={goTab} />;
    case "fatiga":
      return (
        <FatigueView key={week} microcycleId={week}
          matchDate={params.get("partido")} playerId={params.get("jugador")}
          onFilters={(f) => setUrl({
            ...(f.match !== undefined ? { partido: f.match } : {}),
            ...(f.player !== undefined ? { jugador: f.player } : {}),
          })} />
      );
    case "bienestar":
      return (
        <WellnessView key={week} microcycleId={week}
          day={nav.day} playerId={params.get("jugador")} hideDayNav
          onFilters={(f) => setUrl({
            ...(f.day !== undefined ? { dia: f.day } : {}),
            ...(f.player !== undefined ? { jugador: f.player } : {}),
          })} />
      );
    case "lesiones":
      return <AvailabilityView key={week} microcycleId={week} />;
    case "minutos":
      return (
        <>
        <DayLoadChart key={`${week}-${nav.day}`} microcycleId={week} day={nav.day}
          metric={params.get("carga_metrica")} onMetric={(k) => setUrl({ carga_metrica: k })} />
        <ParticipationView key={week} microcycleId={week}
          scope={params.get("periodo") === "temporada" ? "season" : "microcycle"}
          onScope={(sc) => setUrl({ periodo: sc === "season" ? "temporada" : null })} />
        </>
      );
    case "jugador":
      return (
        <PlayerView key={week} microcycleId={week} playerId={params.get("jugador")}
          onPlayer={(id) => setUrl({ jugador: id })} onTab={(t) => goTab(t)} />
      );
    default:
      return null;
  }
}
