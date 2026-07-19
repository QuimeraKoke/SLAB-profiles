// Diagram registry for the `bodymap` field type: named anatomical diagrams,
// each with one or more views (e.g. foot → plantar/dorsal, body → front/back).
// A view is an SVG (viewBox + optional outline) plus clickable zones. The
// `bodymap` field config only references a diagram by `key`; the geometry
// lives here so templates stay lightweight and the same figure powers both
// the interactive input and the read-only display.
//
// Zone keys are GLOBALLY UNIQUE within a diagram (view-prefixed) so a result's
// flat `zones: string[]` is unambiguous about which view each zone belongs to.

export interface DiagramZone {
  key: string;
  label: string;
  /** SVG path data (in the view's viewBox coordinate space). */
  path: string;
}

export interface DiagramLabel {
  text: string;
  x: number;
  y: number;
}

export interface DiagramView {
  key: string;
  label: string;
  /** "minX minY width height" */
  viewBox: string;
  /** Optional non-interactive silhouette drawn behind the zones. */
  outline?: string;
  /** Optional non-interactive text annotations (e.g. "Izquierdo"/"Derecho"). */
  labels?: DiagramLabel[];
  zones: DiagramZone[];
}

export interface Diagram {
  key: string;
  label: string;
  views: DiagramView[];
}

/** Helper: an ellipse as an SVG path (two arcs). */
function ellipse(cx: number, cy: number, rx: number, ry: number): string {
  return `M ${cx - rx},${cy} a ${rx},${ry} 0 1,0 ${rx * 2},0 a ${rx},${ry} 0 1,0 ${-rx * 2},0 z`;
}

// ── Foot: plantar (sole) + dorsal (top), BOTH feet shown at once ───────────
// Two stylized feet side by side (Izquierdo / Derecho) so the podiatrist pins
// directly on the relevant foot — no separate "lado" pick. The foot side is
// encoded in each zone key. Base geometry is a single foot in a 0–100 box;
// each foot is offset horizontally and zones get an `_izq` / `_der` suffix.
interface FootZoneSpec {
  key: string;
  label: string;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

const PLANTAR_BASE: FootZoneSpec[] = [
  { key: "hallux", label: "Hallux (1er dedo)", cx: 32, cy: 28, rx: 14, ry: 18 },
  { key: "dedos", label: "Dedos menores (2–5)", cx: 66, cy: 26, rx: 22, ry: 16 },
  { key: "metatarso", label: "Cabezas metatarsianas", cx: 52, cy: 72, rx: 38, ry: 26 },
  { key: "arco_medial", label: "Arco medial", cx: 38, cy: 135, rx: 16, ry: 34 },
  { key: "arco_lateral", label: "Arco lateral", cx: 66, cy: 135, rx: 14, ry: 34 },
  { key: "talon", label: "Talón", cx: 52, cy: 210, rx: 30, ry: 34 },
];

const DORSAL_BASE: FootZoneSpec[] = [
  { key: "dedos", label: "Dedos", cx: 52, cy: 26, rx: 40, ry: 18 },
  { key: "dorso", label: "Dorso del pie", cx: 52, cy: 112, rx: 40, ry: 62 },
  { key: "tobillo", label: "Tobillo / empeine", cx: 52, cy: 212, rx: 30, ry: 34 },
];

const FOOT_DY = 30; // top room for the Izquierdo / Derecho labels
const FEET = [
  { side: "izq", label: "izq", dx: 8 },
  { side: "der", label: "der", dx: 122 },
];

function bothFeet(base: FootZoneSpec[], viewKey: string): DiagramZone[] {
  const out: DiagramZone[] = [];
  for (const f of FEET) {
    for (const z of base) {
      out.push({
        key: `${viewKey}_${z.key}_${f.side}`,
        label: `${z.label} (${f.label})`,
        path: ellipse(z.cx + f.dx, z.cy + FOOT_DY, z.rx, z.ry),
      });
    }
  }
  return out;
}

const FOOT_LABELS: DiagramLabel[] = [
  { text: "Izquierdo", x: 56, y: 20 },
  { text: "Derecho", x: 170, y: 20 },
];

const FOOT: Diagram = {
  key: "foot",
  label: "Pies",
  views: [
    {
      key: "plantar",
      label: "Plantar",
      viewBox: "0 0 230 285",
      labels: FOOT_LABELS,
      zones: bothFeet(PLANTAR_BASE, "plantar"),
    },
    {
      key: "dorsal",
      label: "Dorsal",
      viewBox: "0 0 230 285",
      labels: FOOT_LABELS,
      zones: bothFeet(DORSAL_BASE, "dorsal"),
    },
  ],
};

// ── Body: front + back (reuses the silhouette geometry of BodyMapHeatmap so
// treated zones share region keys with the injury heat-map) ───────────────
const BODY: Diagram = {
  key: "body",
  label: "Cuerpo",
  views: [
    {
      key: "front",
      label: "Frontal",
      viewBox: "0 0 200 440",
      zones: [
        { key: "head", label: "Cabeza", path: "M 100 5 A 28 32 0 1 0 100 69 A 28 32 0 1 0 100 5 Z" },
        { key: "neck", label: "Cuello", path: "M 88 67 L 112 67 L 112 84 L 88 84 Z" },
        { key: "chest", label: "Pecho", path: "M 60 84 L 140 84 L 145 145 L 55 145 Z" },
        { key: "abdomen", label: "Abdomen", path: "M 58 145 L 142 145 L 138 195 L 62 195 Z" },
        { key: "pelvis", label: "Pelvis", path: "M 62 195 L 138 195 L 145 235 L 55 235 Z" },
        { key: "right_shoulder", label: "Hombro der.", path: "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 40 110 Z" },
        { key: "left_shoulder", label: "Hombro izq.", path: "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 160 110 Z" },
        { key: "right_arm", label: "Brazo der.", path: "M 35 110 L 55 110 L 53 175 L 33 175 Z" },
        { key: "left_arm", label: "Brazo izq.", path: "M 145 110 L 165 110 L 167 175 L 147 175 Z" },
        { key: "right_forearm", label: "Antebrazo der.", path: "M 33 175 L 53 175 L 50 235 L 30 235 Z" },
        { key: "left_forearm", label: "Antebrazo izq.", path: "M 147 175 L 167 175 L 170 235 L 150 235 Z" },
        { key: "right_hand", label: "Mano der.", path: "M 28 235 L 52 235 L 50 265 L 28 265 Z" },
        { key: "left_hand", label: "Mano izq.", path: "M 148 235 L 172 235 L 172 265 L 150 265 Z" },
        { key: "right_thigh", label: "Muslo der.", path: "M 60 235 L 96 235 L 92 320 L 60 320 Z" },
        { key: "left_thigh", label: "Muslo izq.", path: "M 104 235 L 140 235 L 140 320 L 108 320 Z" },
        { key: "right_knee", label: "Rodilla der.", path: "M 60 320 L 92 320 L 90 340 L 62 340 Z" },
        { key: "left_knee", label: "Rodilla izq.", path: "M 108 320 L 140 320 L 138 340 L 110 340 Z" },
        { key: "right_calf", label: "Gemelo der.", path: "M 62 340 L 90 340 L 86 410 L 64 410 Z" },
        { key: "left_calf", label: "Gemelo izq.", path: "M 110 340 L 138 340 L 136 410 L 114 410 Z" },
        { key: "right_foot", label: "Pie der.", path: "M 60 410 L 90 410 L 90 432 L 56 432 Z" },
        { key: "left_foot", label: "Pie izq.", path: "M 110 410 L 140 410 L 144 432 L 110 432 Z" },
      ],
    },
    {
      key: "back",
      label: "Posterior",
      viewBox: "0 0 200 440",
      zones: [
        { key: "head", label: "Cabeza", path: "M 100 5 A 28 32 0 1 0 100 69 A 28 32 0 1 0 100 5 Z" },
        { key: "neck", label: "Cuello", path: "M 88 67 L 112 67 L 112 84 L 88 84 Z" },
        { key: "upper_back", label: "Espalda alta", path: "M 60 84 L 140 84 L 145 145 L 55 145 Z" },
        { key: "lower_back", label: "Zona lumbar", path: "M 58 145 L 142 145 L 138 195 L 62 195 Z" },
        { key: "pelvis", label: "Pelvis", path: "M 62 195 L 138 195 L 145 235 L 55 235 Z" },
        { key: "left_shoulder", label: "Hombro izq.", path: "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 40 110 Z" },
        { key: "right_shoulder", label: "Hombro der.", path: "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 160 110 Z" },
        { key: "left_arm", label: "Brazo izq.", path: "M 35 110 L 55 110 L 53 175 L 33 175 Z" },
        { key: "right_arm", label: "Brazo der.", path: "M 145 110 L 165 110 L 167 175 L 147 175 Z" },
        { key: "left_forearm", label: "Antebrazo izq.", path: "M 33 175 L 53 175 L 50 235 L 30 235 Z" },
        { key: "right_forearm", label: "Antebrazo der.", path: "M 147 175 L 167 175 L 170 235 L 150 235 Z" },
        { key: "left_hand", label: "Mano izq.", path: "M 28 235 L 52 235 L 50 265 L 28 265 Z" },
        { key: "right_hand", label: "Mano der.", path: "M 148 235 L 172 235 L 172 265 L 150 265 Z" },
        { key: "left_thigh", label: "Muslo izq.", path: "M 60 235 L 96 235 L 92 320 L 60 320 Z" },
        { key: "right_thigh", label: "Muslo der.", path: "M 104 235 L 140 235 L 140 320 L 108 320 Z" },
        { key: "left_knee", label: "Rodilla izq. (hueco poplíteo)", path: "M 60 320 L 92 320 L 90 340 L 62 340 Z" },
        { key: "right_knee", label: "Rodilla der. (hueco poplíteo)", path: "M 108 320 L 140 320 L 138 340 L 110 340 Z" },
        { key: "left_calf", label: "Gemelo izq.", path: "M 62 340 L 90 340 L 86 410 L 64 410 Z" },
        { key: "right_calf", label: "Gemelo der.", path: "M 110 340 L 138 340 L 136 410 L 114 410 Z" },
        { key: "left_foot", label: "Talón/pie izq.", path: "M 60 410 L 90 410 L 90 432 L 56 432 Z" },
        { key: "right_foot", label: "Talón/pie der.", path: "M 110 410 L 140 410 L 144 432 L 110 432 Z" },
      ],
    },
  ],
};

export const DIAGRAMS: Record<string, Diagram> = {
  foot: FOOT,
  body: BODY,
};

export function getDiagram(key: string | undefined | null): Diagram | null {
  if (!key) return null;
  return DIAGRAMS[key] ?? null;
}

/** Flat lookup: zone key → its label, across every view of a diagram. */
export function zoneLabelMap(diagram: Diagram): Record<string, string> {
  const out: Record<string, string> = {};
  for (const v of diagram.views) {
    for (const z of v.zones) out[z.key] = z.label;
  }
  return out;
}

/** Which view a zone key belongs to (first match). */
export function viewOfZone(diagram: Diagram, zoneKey: string): DiagramView | null {
  for (const v of diagram.views) {
    if (v.zones.some((z) => z.key === zoneKey)) return v;
  }
  return null;
}

// ── Value shape stored in result_data[fieldKey] ───────────────────────────
export interface BodyMapPin {
  view: string;
  /** Normalized 0–1 coords relative to the view's viewBox. */
  x: number;
  y: number;
  /** Zone the pin fell in — auto-detected from its position. */
  zone?: string;
}

export interface BodyMapValue {
  /** Derived: the unique zones covered by the pins. Kept in the value for
   *  reporting / heat-map compatibility. */
  zones: string[];
  pins: BodyMapPin[];
}

export function emptyBodyMapValue(): BodyMapValue {
  return { zones: [], pins: [] };
}

/** Coerce an unknown result value into a well-formed BodyMapValue. */
export function normalizeBodyMapValue(raw: unknown): BodyMapValue {
  const v = (raw ?? {}) as Partial<BodyMapValue>;
  const zones = Array.isArray(v.zones) ? v.zones.filter((z) => typeof z === "string") : [];
  const pins = Array.isArray(v.pins)
    ? v.pins
        .filter(
          (p): p is BodyMapPin =>
            !!p && typeof p.view === "string" &&
            typeof p.x === "number" && typeof p.y === "number",
        )
        .map((p) => ({
          view: p.view,
          x: p.x,
          y: p.y,
          ...(typeof p.zone === "string" ? { zone: p.zone } : {}),
        }))
    : [];
  return { zones, pins };
}

/** The unique, order-preserving set of zones covered by a pin list. */
export function zonesFromPins(pins: BodyMapPin[]): string[] {
  const out: string[] = [];
  for (const p of pins) {
    if (p.zone && !out.includes(p.zone)) out.push(p.zone);
  }
  return out;
}

export function isBodyMapEmpty(v: BodyMapValue): boolean {
  return v.zones.length === 0 && v.pins.length === 0;
}
