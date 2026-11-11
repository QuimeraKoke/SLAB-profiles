"use client";

/**
 * The formativo's panels for the club's 9 questions (PLAN_CONTROL_CARGA.md),
 * shown as tabs of the Centro de mando for categories that compete in a
 * bracket (U20, U18…). Control de carga keeps only what is about the plan
 * (Carga GPS and Planificación); everything about the squad lives here.
 *
 * ONE time control (`PeriodBar`): a period — the Mon–Sun week of `?dia=`, or
 * any `?desde=&hasta=` — and a day chosen inside it (`?dia=`, the day strip).
 * Every card says which of the two it answers (`ScopeBadge`); no card has a
 * time toggle of its own. Fatiga moves match by match; Evaluaciones and
 * Composición read the whole history. All of it lives in the URL (IA principle 2).
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
import { dayText, periodText } from "@/components/loadControl/PeriodBar";
import { type DayNav } from "@/lib/loadControl";
import { PeriodContext, periodWords } from "@/lib/periodWording";

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
/** Panels that read several days at once and may read any period (?desde=&hasta=)
 *  instead of the calendar week. Fatiga stays per microcycle (MD+1 vs MD-1),
 *  Kinesia per day. */
export const RANGE_TABS = new Set(["resumen", "bienestar", "minutos", "jugador"]);

export const FORMATIVO_QUESTION: Record<string, string> = {
  resumen: "¿Cómo está el plantel? ¿A quién compensar? ¿Quién llega fatigado?",
  fatiga: "¿Cuánto les pegó el último partido y cómo llegan al que viene?",
  bienestar: "¿Cómo llegan, cómo se sienten, qué les molesta y cómo se van?",
  lesiones: "¿Quién está en readaptación o en clínica, desde cuándo y cuándo vuelve?",
  minutos: "¿Cuánto jugó cada uno y a cuántas sesiones fue?",
  jugador: "¿Cómo viene esta persona, en todo?",
  evaluaciones: "¿Qué tan fuerte, rápido y resistente es cada uno, frente al grupo y frente a su evaluación anterior?",
  composicion: "¿Cómo evolucionan el músculo, la grasa y los pliegues de cada uno?",
};

/** Tabs that read a period: the period bar. */
export const PERIOD_TABS = new Set(["resumen", "bienestar", "lesiones", "minutos", "jugador"]);
/** …and also have cards about ONE day of it: the day strip too. Resumen and
 *  Jugador add the whole period up, so a day picker there would do nothing. */
export const STRIP_TABS = new Set(["bienestar", "lesiones", "minutos"]);
/** Tabs that do not depend on dates at all (whole history). */
export const NO_TIME_TABS = NOT_WEEKLY;
/** Fatiga moves match by match (its own "‹ Partido ›"): the microcycle is
 *  defined by the match, not by a free period. */
export const OWN_TIME_TABS = new Set(["fatiga"]);

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

export default function FormativoPanels(props: Props) {
  return (
    <PeriodContext.Provider value={periodWords(!!props.nav.range,
      { day: props.nav.day, dayText: dayText(props.nav), periodText: periodText(props.nav) })}>
      <Panels {...props} />
    </PeriodContext.Provider>
  );
}

function Panels({ tab, nav, categoryId, params, setUrl, goTab }: Props) {
  // Planned week → its id; otherwise the key the API resolves to the
  // calendar week ("<day>_<category>") or the period ("<start>~<end>_<category>").
  const week = nav.microcycle_id ?? nav.week_key;
  const onDay = (d: string | null | undefined) => d !== undefined && setUrl({ dia: d });

  if (tab === "evaluaciones" || tab === "composicion") {
    return (
      <>
        <p className={styles.noTime}>Muestra todo el historial: no depende de las fechas.</p>
        {tab === "evaluaciones" ? <EvaluationGrid categoryId={categoryId} /> : (
          <CompositionView categoryId={categoryId} playerId={params.get("jugador")}
            metric={params.get("metrica")} sort={params.get("orden")}
            onFilters={(f) => setUrl({
              ...(f.player !== undefined ? { jugador: f.player } : {}),
              ...(f.metric !== undefined ? { metrica: f.metric } : {}),
              ...(f.sort !== undefined ? { orden: f.sort } : {}),
            })} />
        )}
      </>
    );
  }

  switch (tab) {
    case "resumen":
      return <SummaryView key={week} microcycleId={week} onTab={goTab} />;
    case "fatiga":
      return (
        <FatigueView key={week} microcycleId={week}
          matchDate={params.get("partido")} playerId={params.get("jugador")}
          mode={params.get("fatiga_vista") === "microciclo" ? "micro" : "match"}
          onMode={(md) => setUrl({ fatiga_vista: md === "micro" ? "microciclo" : null })}
          onFilters={(f) => setUrl({
            ...(f.match !== undefined ? { partido: f.match } : {}),
            ...(f.player !== undefined ? { jugador: f.player } : {}),
          })} />
      );
    case "bienestar":
      return (
        <WellnessView key={week} microcycleId={week}
          day={nav.day} playerId={params.get("jugador")} hideDayNav
          onFilters={(f) => {
            if (f.day !== undefined) onDay(f.day);
            if (f.player !== undefined) setUrl({ jugador: f.player });
          }} />
      );
    case "lesiones":
      return <AvailabilityView key={`${week}-${nav.day}`} microcycleId={week} day={nav.day} />;
    case "minutos":
      return (
        <>
          <DayLoadChart key={`${week}-periodo`} microcycleId={week} day={nav.day} view="week"
            metric={params.get("carga_metrica")} onMetric={(k) => setUrl({ carga_metrica: k })} />
          <DayLoadChart key={`${week}-${nav.day}`} microcycleId={week} day={nav.day} view="day"
            metric={params.get("carga_metrica")} onMetric={(k) => setUrl({ carga_metrica: k })} />
          <ParticipationView key={week} microcycleId={week} />
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
