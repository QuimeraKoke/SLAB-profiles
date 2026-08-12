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
// A zone is either a single ellipse (cx/cy/rx/ry) or an explicit list of
// ellipses — the toe groups draw as several separate ovals that still form ONE
// selectable zone, because an SVG path may hold multiple subpaths under one
// `d`. That keeps the stored zone keys (and the pins' normalized coordinates)
// untouched while the drawing actually shows individual toes.
interface FootOval {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}
interface FootZoneSpec {
  key: string;
  label: string;
  /** One or more ovals; multiple ovals render as one multi-subpath zone. */
  ovals: FootOval[];
}

/** Toe row: `n` ovals marching laterally, each a bit smaller and set a bit
 *  lower than the last — the natural cascade from 2nd toe to 5th. */
function toeRow(
  startCx: number, startCy: number, step: number, n: number,
  rx: number, ry: number,
): FootOval[] {
  return Array.from({ length: n }, (_, i) => ({
    cx: startCx + i * step,
    cy: startCy + i * 2,          // each toe sits slightly lower
    rx: rx - i * 0.5,
    ry: ry - i * 1.6,
  }));
}

const PLANTAR_BASE: FootZoneSpec[] = [
  // Hallux keeps its own footprint; the 2nd–5th toes now read as four ovals
  // spanning the same x-range the single "dedos" ellipse used to cover.
  { key: "hallux", label: "Hallux (1er dedo)", ovals: [{ cx: 32, cy: 30, rx: 12, ry: 17 }] },
  { key: "dedos", label: "Dedos menores (2–5)", ovals: toeRow(52, 28, 10, 4, 6, 15) },
  { key: "metatarso", label: "Cabezas metatarsianas", ovals: [{ cx: 52, cy: 72, rx: 38, ry: 26 }] },
  { key: "arco_medial", label: "Arco medial", ovals: [{ cx: 38, cy: 135, rx: 16, ry: 34 }] },
  { key: "arco_lateral", label: "Arco lateral", ovals: [{ cx: 66, cy: 135, rx: 14, ry: 34 }] },
  { key: "talon", label: "Talón", ovals: [{ cx: 52, cy: 210, rx: 30, ry: 34 }] },
];

const DORSAL_BASE: FootZoneSpec[] = [
  // Dorsal has no separate hallux zone, so all five toes live in "dedos".
  {
    key: "dedos",
    label: "Dedos",
    ovals: [{ cx: 24, cy: 32, rx: 11, ry: 17 }, ...toeRow(46, 30, 11, 4, 6.5, 15)],
  },
  { key: "dorso", label: "Dorso del pie", ovals: [{ cx: 52, cy: 112, rx: 40, ry: 62 }] },
  { key: "tobillo", label: "Tobillo / empeine", ovals: [{ cx: 52, cy: 212, rx: 30, ry: 34 }] },
];

const FOOT_DY = 30; // top room for the Izquierdo / Derecho labels
// The base geometry is anatomically a RIGHT foot (hallux/medial on the left).
// Drawn as a pair the two feet must be MIRROR images, not identical, so the
// big toes face inward (medial-to-medial). The right foot uses the base as-is;
// the left foot is horizontally mirrored about the foot's centerline.
const FOOT_CENTER_X = 52; // outline + base ovals are symmetric about this x
const FEET = [
  { side: "izq", label: "izq", dx: 8, mirror: true },
  { side: "der", label: "der", dx: 122, mirror: false },
];

/** Non-interactive foot body drawn behind the zones — gives the toes something
 *  to sit on so they read as a foot rather than floating ovals. Spans the
 *  metatarsal-to-heel area only; the toes themselves are zones. */
function footOutline(dx: number): string {
  const x = (n: number) => n + dx;
  const y = (n: number) => n + FOOT_DY;
  return (
    `M ${x(14)} ${y(70)} ` +
    `C ${x(10)} ${y(40)}, ${x(94)} ${y(40)}, ${x(90)} ${y(70)} ` +
    `C ${x(94)} ${y(120)}, ${x(84)} ${y(150)}, ${x(82)} ${y(185)} ` +
    `C ${x(82)} ${y(232)}, ${x(22)} ${y(232)}, ${x(22)} ${y(185)} ` +
    `C ${x(20)} ${y(150)}, ${x(10)} ${y(120)}, ${x(14)} ${y(70)} Z`
  );
}

const FOOT_OUTLINE = FEET.map((f) => footOutline(f.dx)).join(" ");

function bothFeet(base: FootZoneSpec[], viewKey: string): DiagramZone[] {
  const out: DiagramZone[] = [];
  for (const f of FEET) {
    for (const z of base) {
      out.push({
        key: `${viewKey}_${z.key}_${f.side}`,
        label: `${z.label} (${f.label})`,
        // Mirror the left foot about the centerline so the pair is symmetric
        // (big toes inward) rather than two identical feet. Zone KEYS are
        // unchanged, so stored selections are unaffected.
        path: z.ovals
          .map((o) => {
            const cx = f.mirror ? 2 * FOOT_CENTER_X - o.cx : o.cx;
            return ellipse(cx + f.dx, o.cy + FOOT_DY, o.rx, o.ry);
          })
          .join(" "),
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
      outline: FOOT_OUTLINE,
      labels: FOOT_LABELS,
      zones: bothFeet(PLANTAR_BASE, "plantar"),
    },
    {
      key: "dorsal",
      label: "Dorsal",
      viewBox: "0 0 230 285",
      outline: FOOT_OUTLINE,
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
