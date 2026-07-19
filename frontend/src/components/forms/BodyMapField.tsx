"use client";

import React, { useRef, useState } from "react";

import {
  getDiagram,
  normalizeBodyMapValue,
  zonesFromPins,
  type BodyMapValue,
} from "@/lib/bodyDiagrams";
import styles from "./BodyMapField.module.css";

interface Props {
  /** Diagram registry key from the field config (e.g. "foot", "body"). */
  diagramKey: string;
  value: BodyMapValue | unknown;
  onChange?: (v: BodyMapValue) => void;
  /** Display-only: highlights pins + their zones, no editing. */
  readOnly?: boolean;
}

/**
 * Interactive anatomical selector for the `bodymap` field type. The user just
 * drops pins on the figure by clicking; the zone each pin falls in is
 * auto-detected (SVG hit-test, nearest-zone fallback). No manual zone picking
 * and no mode toggle. `zones` in the value is derived from the pins. In
 * `readOnly` mode it's a static figure for viewing a saved record.
 */
export default function BodyMapField({ diagramKey, value, onChange, readOnly }: Props) {
  const diagram = getDiagram(diagramKey);
  const [viewIdx, setViewIdx] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const zoneRefs = useRef<Record<string, SVGPathElement | null>>({});

  if (!diagram) {
    return <div className={styles.error}>Diagrama “{diagramKey}” no encontrado.</div>;
  }

  const view = diagram.views[Math.min(viewIdx, diagram.views.length - 1)];
  const [minX, minY, w, h] = view.viewBox.split(/\s+/).map(Number);
  const val = normalizeBodyMapValue(value);
  const selected = new Set(val.zones);
  const allZones = diagram.views.flatMap((v) => v.zones);
  const labelOf = (key: string) => allZones.find((z) => z.key === key)?.label ?? key;

  function commit(pins: BodyMapValue["pins"]) {
    if (readOnly || !onChange) return;
    onChange({ pins, zones: zonesFromPins(pins) });
  }

  /** Which zone does a point (in viewBox coords) fall in? Containment first,
   *  then nearest zone by bounding-box centre so every pin gets a zone. */
  function detectZone(loc: DOMPoint): string | undefined {
    for (const z of view.zones) {
      const el = zoneRefs.current[z.key];
      if (el && typeof el.isPointInFill === "function") {
        try {
          if (el.isPointInFill(loc)) return z.key;
        } catch {
          /* isPointInFill unsupported on this element — fall through */
        }
      }
    }
    let best: string | undefined;
    let bestD = Infinity;
    for (const z of view.zones) {
      const el = zoneRefs.current[z.key];
      if (!el) continue;
      let bb: DOMRect;
      try {
        bb = el.getBBox();
      } catch {
        continue;
      }
      const cx = bb.x + bb.width / 2;
      const cy = bb.y + bb.height / 2;
      const d = (cx - loc.x) ** 2 + (cy - loc.y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = z.key;
      }
    }
    return best;
  }

  function placePin(e: React.MouseEvent<SVGSVGElement>) {
    if (readOnly || !onChange || !svgRef.current) return;
    const svg = svgRef.current;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const loc = pt.matrixTransform(ctm.inverse());
    const nx = (loc.x - minX) / w;
    const ny = (loc.y - minY) / h;
    if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return;
    const zone = detectZone(loc);
    commit([...val.pins, { view: view.key, x: nx, y: ny, ...(zone ? { zone } : {}) }]);
  }

  function removePin(idx: number) {
    if (readOnly || !onChange) return;
    commit(val.pins.filter((_, i) => i !== idx));
  }

  const viewPins = val.pins
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => p.view === view.key);

  return (
    <div className={`${styles.wrap} ${readOnly ? styles.readOnly : ""}`}>
      {diagram.views.length > 1 && (
        <div className={styles.tabs} role="tablist" aria-label="Vista">
          {diagram.views.map((v, i) => (
            <button
              type="button"
              key={v.key}
              role="tab"
              aria-selected={i === viewIdx}
              className={i === viewIdx ? styles.tabOn : styles.tab}
              onClick={() => setViewIdx(i)}
            >
              {v.label}
            </button>
          ))}
        </div>
      )}

      <div className={styles.figureWrap}>
        <svg
          ref={svgRef}
          className={styles.svg}
          viewBox={view.viewBox}
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label={`${diagram.label} — ${view.label}`}
          onClick={readOnly ? undefined : placePin}
          style={{ cursor: readOnly ? "default" : "crosshair" }}
        >
          {view.outline && <path d={view.outline} className={styles.outline} />}
          {view.labels?.map((lbl, i) => (
            <text
              key={`lbl-${i}`}
              x={lbl.x}
              y={lbl.y}
              className={styles.viewLabel}
              textAnchor="middle"
            >
              {lbl.text}
            </text>
          ))}
          {view.zones.map((z) => (
            <path
              key={z.key}
              ref={(el) => {
                zoneRefs.current[z.key] = el;
              }}
              d={z.path}
              className={`${styles.zone} ${selected.has(z.key) ? styles.zoneOn : ""}`}
              aria-label={z.label}
            >
              <title>{z.label}</title>
            </path>
          ))}
          {viewPins.map(({ p, i }) => (
            <g
              key={i}
              className={styles.pin}
              onClick={
                readOnly
                  ? undefined
                  : (e) => {
                      e.stopPropagation();
                      removePin(i);
                    }
              }
            >
              <title>{p.zone ? labelOf(p.zone) : "Punto"}</title>
              <circle cx={minX + p.x * w} cy={minY + p.y * h} r={8} className={styles.pinHalo} />
              <circle cx={minX + p.x * w} cy={minY + p.y * h} r={3.2} className={styles.pinCore} />
            </g>
          ))}
        </svg>
      </div>

      {!readOnly && (
        <div className={styles.controls}>
          <span className={styles.hint}>
            Hacé clic en la figura para marcar un punto — la zona se detecta
            automáticamente. Clic en un punto para quitarlo.
          </span>
        </div>
      )}

      <div className={styles.selectedList}>
        {val.pins.length === 0 ? (
          <span className={styles.muted}>Sin puntos marcados.</span>
        ) : (
          <>
            {val.zones.map((z) => (
              <span key={z} className={styles.chip}>
                {labelOf(z)}
              </span>
            ))}
            <span className={styles.pinCount}>
              {val.pins.length} punto{val.pins.length > 1 ? "s" : ""}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
