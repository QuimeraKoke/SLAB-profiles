"use client";

import React, { useMemo, useState } from "react";

import type {
  BodyMapHeatmapPayload,
  BodyMapStageInfo,
  DashboardWidget,
} from "@/lib/types";
import styles from "./BodyMapHeatmap.module.css";

interface Props {
  widget: DashboardWidget;
}

const REGION_LABEL: Record<string, string> = {
  head: "Cabeza",
  neck: "Cuello",
  chest: "Pecho",
  abdomen: "Abdomen",
  upper_back: "Espalda alta",
  lower_back: "Espalda baja",
  pelvis: "Pelvis",
  left_shoulder: "Hombro izq.",
  right_shoulder: "Hombro der.",
  left_arm: "Brazo izq.",
  right_arm: "Brazo der.",
  left_forearm: "Antebrazo izq.",
  right_forearm: "Antebrazo der.",
  left_hand: "Mano izq.",
  right_hand: "Mano der.",
  left_thigh: "Muslo izq.",
  right_thigh: "Muslo der.",
  left_knee: "Rodilla izq.",
  right_knee: "Rodilla der.",
  left_calf: "Pantorrilla izq.",
  right_calf: "Pantorrilla der.",
  left_foot: "Pie izq.",
  right_foot: "Pie der.",
};

/** Order matters for the legend display. */
const REGION_ORDER: string[] = [
  "head", "neck",
  "chest", "abdomen", "upper_back", "lower_back", "pelvis",
  "left_shoulder", "right_shoulder",
  "left_arm", "right_arm",
  "left_forearm", "right_forearm",
  "left_hand", "right_hand",
  "left_thigh", "right_thigh",
  "left_knee", "right_knee",
  "left_calf", "right_calf",
  "left_foot", "right_foot",
];

type View = "front" | "back";

/**
 * Linear interpolation between gray (count = 0) and red (count = max).
 * Returns a CSS hsl string. Empty regions stay near-white so they read as
 * "no data here" rather than "low data here".
 */
function colorForCount(count: number, maxCount: number): string {
  if (count === 0 || maxCount === 0) return "hsl(220, 13%, 95%)";
  const ratio = Math.min(count / maxCount, 1);
  const lightness = 90 - ratio * 45;
  const saturation = 60 + ratio * 15;
  return `hsl(0, ${saturation}%, ${lightness}%)`;
}

export default function BodyMapHeatmap({ widget }: Props) {
  const data = widget.data as BodyMapHeatmapPayload;
  const stages: BodyMapStageInfo[] = data.stages ?? [];
  const fieldLabel = data.field?.label ?? "";

  const [view, setView] = useState<View>("front");
  // Empty string = "all stages combined" (default).
  const [activeStage, setActiveStage] = useState<string>("");

  // Compute the displayed counts based on the active filter.
  const { counts, max, totalCount } = useMemo(() => {
    const allCounts = data.counts ?? {};
    const byStage = data.counts_by_stage ?? {};
    const filteredCounts = activeStage
      ? byStage[activeStage] ?? {}
      : allCounts;
    const filteredMax = Math.max(0, ...Object.values(filteredCounts));
    const total = Object.values(filteredCounts).reduce((a, b) => a + b, 0);
    return { counts: filteredCounts, max: filteredMax, totalCount: total };
  }, [data, activeStage]);

  const [hover, setHover] = useState<{ region: string; x: number; y: number } | null>(
    null,
  );

  const handleEnter = (region: string) => (e: React.MouseEvent) => {
    setHover({ region, x: e.clientX, y: e.clientY });
  };
  const handleLeave = () => setHover(null);
  const handleMove = (e: React.MouseEvent) => {
    setHover((prev) => (prev ? { ...prev, x: e.clientX, y: e.clientY } : null));
  };

  const legendItems = REGION_ORDER
    .filter((r) => (counts[r] ?? 0) > 0)
    .sort((a, b) => (counts[b] ?? 0) - (counts[a] ?? 0));

  const isEmpty = (data.total_results ?? 0) === 0;
  const isFilterEmpty = !isEmpty && max === 0;

  // Tooltip detail comes from the per-region items list. When a stage filter
  // is active and we'd otherwise show stage-agnostic option breakdown, the
  // breakdown could be misleading — so when filtering we show only the count.
  const itemsByRegion = new Map(data.items?.map((it) => [it.region, it]) ?? []);
  const hoverDetail = hover ? itemsByRegion.get(hover.region) : null;

  return (
    <div className={styles.widget}>
      <header className={styles.header}>
        <h4 className={styles.title}>{widget.title}</h4>
        <span className={styles.totalCount}>
          {totalCount} resultado{totalCount === 1 ? "" : "s"}
          {fieldLabel && ` · ${fieldLabel}`}
        </span>
      </header>

      {!isEmpty && (
        <div className={styles.toolbar}>
          <div className={styles.toolbarGroup}>
            <div className={styles.viewToggle} role="tablist" aria-label="Vista">
              <button
                type="button"
                role="tab"
                aria-selected={view === "front"}
                className={`${styles.viewBtn} ${view === "front" ? styles.viewBtnActive : ""}`}
                onClick={() => setView("front")}
              >
                Frente
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "back"}
                className={`${styles.viewBtn} ${view === "back" ? styles.viewBtnActive : ""}`}
                onClick={() => setView("back")}
              >
                Espalda
              </button>
            </div>
          </div>

          {stages.length > 0 && (
            <div className={styles.toolbarGroup}>
              <button
                type="button"
                className={`${styles.stageChip} ${activeStage === "" ? styles.stageChipActive : ""}`}
                onClick={() => setActiveStage("")}
              >
                Todas
              </button>
              {stages.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  className={`${styles.stageChip} ${
                    activeStage === s.value ? styles.stageChipActive : ""
                  } ${s.kind === "closed" ? styles.kind_closed : ""}`}
                  onClick={() => setActiveStage(s.value)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {isEmpty ? (
        <div className={styles.empty}>
          Sin datos de regiones para este jugador.
          <br />
          <small style={{ color: "#9ca3af" }}>
            Configurá <code>option_regions</code> en el campo categórico de la
            plantilla para mapear cada opción a una región del cuerpo.
          </small>
        </div>
      ) : (
        <div className={styles.body} onMouseMove={handleMove}>
          <div className={styles.svgWrap}>
            {view === "front" ? (
              <BodyFrontSilhouette
                counts={counts}
                max={max}
                onEnter={handleEnter}
                onLeave={handleLeave}
              />
            ) : (
              <BodyBackSilhouette
                counts={counts}
                max={max}
                onEnter={handleEnter}
                onLeave={handleLeave}
              />
            )}
            <div className={styles.viewCaption} aria-live="polite">
              {view === "front" ? (
                <>
                  <span className={styles.arrow} aria-hidden="true">👁</span>
                  <span>Vista frontal</span>
                </>
              ) : (
                <>
                  <span className={styles.arrow} aria-hidden="true">↩</span>
                  <span>Vista posterior</span>
                </>
              )}
            </div>
            <div className={styles.scaleHint}>
              <span>0</span>
              <span className={styles.scaleBar} />
              <span>{max}</span>
            </div>
          </div>

          <div className={styles.legend}>
            <h5 className={styles.legendTitle}>
              Conteo por región
              {activeStage && stages.find((s) => s.value === activeStage) && (
                <span style={{ fontWeight: 500, color: "#9ca3af", marginLeft: 6 }}>
                  · {stages.find((s) => s.value === activeStage)?.label}
                </span>
              )}
            </h5>
            {isFilterEmpty ? (
              <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>
                Sin coincidencias para esta etapa.
              </span>
            ) : legendItems.length === 0 ? (
              <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>—</span>
            ) : (
              legendItems.map((r) => {
                const cnt = counts[r] ?? 0;
                return (
                  <div key={r} className={styles.legendRow}>
                    <span
                      className={styles.legendSwatch}
                      style={{ background: colorForCount(cnt, max) }}
                    />
                    <span className={styles.legendName}>
                      {REGION_LABEL[r] ?? r}
                    </span>
                    <span className={styles.legendCount}>{cnt}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {hover && hoverDetail && (
        <div
          className={styles.tooltip}
          style={{ left: hover.x, top: hover.y }}
        >
          <strong>{REGION_LABEL[hover.region] ?? hover.region}</strong> ·{" "}
          {counts[hover.region] ?? 0} resultado
          {(counts[hover.region] ?? 0) === 1 ? "" : "s"}
          {!activeStage && hoverDetail.options.length > 1 && (
            <div style={{ marginTop: 2, opacity: 0.8 }}>
              {hoverDetail.options
                .map((o) => `${o.label} (${o.count})`)
                .join(" · ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface SilhouetteProps {
  counts: Record<string, number>;
  max: number;
  onEnter: (region: string) => (e: React.MouseEvent) => void;
  onLeave: () => void;
}

function regionPath(
  id: string,
  d: string,
  fill: (region: string) => string,
  onEnter: SilhouetteProps["onEnter"],
  onLeave: SilhouetteProps["onLeave"],
) {
  return (
    <path
      key={id}
      id={id}
      d={d}
      className={styles.region}
      fill={fill(id)}
      onMouseEnter={onEnter(id)}
      onMouseLeave={onLeave}
    >
      <title>{REGION_LABEL[id] ?? id}</title>
    </path>
  );
}

/**
 * Front-view silhouette. Mirrors medical-imaging convention: the player's
 * right side is on the SVG's LEFT (as if facing the viewer).
 */
function BodyFrontSilhouette({ counts, max, onEnter, onLeave }: SilhouetteProps) {
  const fill = (region: string) => colorForCount(counts[region] ?? 0, max);
  const r = (id: string, d: string) => regionPath(id, d, fill, onEnter, onLeave);

  return (
    <svg
      className={styles.svg}
      viewBox="0 0 200 440"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Mapa corporal frontal"
    >
      {r("head", "M 100 5 A 28 32 0 1 0 100 69 A 28 32 0 1 0 100 5 Z")}
      {/* Face features — make it obvious the figure is facing the viewer.
          These sit ABOVE the head path so they always render on top.
          Pointer-events: none so they don't block the head's hover. */}
      <circle cx="91" cy="32" r="2.2" className={styles.faceFeature} />
      <circle cx="109" cy="32" r="2.2" className={styles.faceFeature} />
      <path
        d="M 100 38 L 96 46 L 104 46 Z"
        className={styles.faceFeature}
        opacity="0.5"
      />
      <path
        d="M 94 54 Q 100 58 106 54"
        fill="none"
        stroke="#6b7280"
        strokeWidth="1.2"
        strokeLinecap="round"
        opacity="0.6"
        style={{ pointerEvents: "none" }}
      />
      {r("neck", "M 88 67 L 112 67 L 112 84 L 88 84 Z")}
      {r("chest", "M 60 84 L 140 84 L 145 145 L 55 145 Z")}
      {r("abdomen", "M 58 145 L 142 145 L 138 195 L 62 195 Z")}
      {r("pelvis", "M 62 195 L 138 195 L 145 235 L 55 235 Z")}
      {/* SVG-left = player's right, by mirror convention. */}
      {r("right_shoulder", "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 40 110 Z")}
      {r("left_shoulder", "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 160 110 Z")}
      {r("right_arm", "M 35 110 L 55 110 L 53 175 L 33 175 Z")}
      {r("left_arm", "M 145 110 L 165 110 L 167 175 L 147 175 Z")}
      {r("right_forearm", "M 33 175 L 53 175 L 50 235 L 30 235 Z")}
      {r("left_forearm", "M 147 175 L 167 175 L 170 235 L 150 235 Z")}
      {r("right_hand", "M 28 235 L 52 235 L 50 265 L 28 265 Z")}
      {r("left_hand", "M 148 235 L 172 235 L 172 265 L 150 265 Z")}
      {r("right_thigh", "M 60 235 L 96 235 L 92 320 L 60 320 Z")}
      {r("left_thigh", "M 104 235 L 140 235 L 140 320 L 108 320 Z")}
      {r("right_knee", "M 60 320 L 92 320 L 90 340 L 62 340 Z")}
      {r("left_knee", "M 108 320 L 140 320 L 138 340 L 110 340 Z")}
      {r("right_calf", "M 62 340 L 90 340 L 86 410 L 64 410 Z")}
      {r("left_calf", "M 110 340 L 138 340 L 136 410 L 114 410 Z")}
      {r("right_foot", "M 60 410 L 90 410 L 90 432 L 56 432 Z")}
      {r("left_foot", "M 110 410 L 140 410 L 144 432 L 110 432 Z")}
    </svg>
  );
}

/**
 * Back-view silhouette. Natural viewing angle (NOT mirrored): the player's
 * left side is on the SVG's LEFT, as you'd see them from behind. Front-only
 * regions (chest/abdomen) are absent; back-only regions (upper_back,
 * lower_back) are present in their place.
 */
function BodyBackSilhouette({ counts, max, onEnter, onLeave }: SilhouetteProps) {
  const fill = (region: string) => colorForCount(counts[region] ?? 0, max);
  const r = (id: string, d: string) => regionPath(id, d, fill, onEnter, onLeave);

  return (
    <svg
      className={styles.svg}
      viewBox="0 0 200 440"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Mapa corporal posterior"
    >
      {r("head", "M 100 5 A 28 32 0 1 0 100 69 A 28 32 0 1 0 100 5 Z")}
      {r("neck", "M 88 67 L 112 67 L 112 84 L 88 84 Z")}
      {/* Back-only regions take the place of chest/abdomen. */}
      {r("upper_back", "M 60 84 L 140 84 L 145 145 L 55 145 Z")}
      {r("lower_back", "M 58 145 L 142 145 L 138 195 L 62 195 Z")}
      {r("pelvis", "M 62 195 L 138 195 L 145 235 L 55 235 Z")}
      {/* Back view is NOT mirrored: SVG-left = player's left. */}
      {r("left_shoulder", "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 40 110 Z")}
      {r("right_shoulder", "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 160 110 Z")}
      {r("left_arm", "M 35 110 L 55 110 L 53 175 L 33 175 Z")}
      {r("right_arm", "M 145 110 L 165 110 L 167 175 L 147 175 Z")}
      {r("left_forearm", "M 33 175 L 53 175 L 50 235 L 30 235 Z")}
      {r("right_forearm", "M 147 175 L 167 175 L 170 235 L 150 235 Z")}
      {r("left_hand", "M 28 235 L 52 235 L 50 265 L 28 265 Z")}
      {r("right_hand", "M 148 235 L 172 235 L 172 265 L 150 265 Z")}
      {r("left_thigh", "M 60 235 L 96 235 L 92 320 L 60 320 Z")}
      {r("right_thigh", "M 104 235 L 140 235 L 140 320 L 108 320 Z")}
      {r("left_knee", "M 60 320 L 92 320 L 90 340 L 62 340 Z")}
      {r("right_knee", "M 108 320 L 140 320 L 138 340 L 110 340 Z")}
      {r("left_calf", "M 62 340 L 90 340 L 86 410 L 64 410 Z")}
      {r("right_calf", "M 110 340 L 138 340 L 136 410 L 114 410 Z")}
      {r("left_foot", "M 60 410 L 90 410 L 90 432 L 56 432 Z")}
      {r("right_foot", "M 110 410 L 140 410 L 144 432 L 110 432 Z")}
    </svg>
  );
}
