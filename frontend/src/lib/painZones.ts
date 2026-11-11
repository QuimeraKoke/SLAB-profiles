// Muscle-group body map for the check-in / check-out pain answers — the zones
// of the formativo's forms ("Isquiotibiales Izq.", "Gemelos / Sóleo Der."…),
// finer than `bodyDiagrams.ts`'s "Muslo" so cuádriceps, aductores and
// isquiotibiales read apart. Same silhouette and coordinate space (200 × 440)
// as the `body` diagram.
//
// Keys are `${zone}_${side}` (or `${zone}` for unsided zones) and zone names
// match `backend/load_control/pain_zones.py`.
//
// Orientation, as a physio reads it: FRONT view = facing the player, so his
// right is on the viewer's left; BACK view = behind him, his left on the left.

export interface PainZoneShape {
  /** `${zone}_${side}` or `${zone}` */
  id: string;
  zone: string;
  side: "izq" | "der" | null;
  path: string;
}

export interface PainView {
  key: "front" | "back";
  label: string;
  zones: PainZoneShape[];
}

export const PAIN_VIEWBOX = "0 0 200 440";

/** Grey silhouette behind the zones (both views share it). */
export const PAIN_OUTLINE = [
  "M 100 5 A 28 32 0 1 0 100 69 A 28 32 0 1 0 100 5 Z",            // cabeza
  "M 88 67 L 112 67 L 112 84 L 88 84 Z",                            // cuello
  "M 60 84 L 140 84 L 145 145 L 138 195 L 145 235 L 55 235 L 62 195 L 55 145 Z", // tronco
  "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 55 110 L 50 235 L 52 265 L 28 265 L 30 235 L 33 175 L 35 110 L 40 110 Z",
  "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 145 110 L 150 235 L 148 265 L 172 265 L 170 235 L 167 175 L 165 110 L 160 110 Z",
  "M 60 235 L 97 235 L 92 320 L 90 410 L 90 432 L 56 432 L 60 410 L 62 340 L 60 320 Z",
  "M 103 235 L 140 235 L 140 320 L 138 340 L 136 410 L 144 432 L 110 432 L 110 410 L 108 320 Z",
];

type Side = "izq" | "der";
const z = (zone: string, side: Side | null, path: string): PainZoneShape => ({
  id: side ? `${zone}_${side}` : zone, zone, side, path,
});

// Front: the player's RIGHT is on the viewer's LEFT (x < 100).
const FRONT: PainZoneShape[] = [
  z("cuello", "der", "M 88 67 L 100 67 L 100 84 L 88 84 Z"),
  z("cuello", "izq", "M 100 67 L 112 67 L 112 84 L 100 84 Z"),
  z("deltoides_anterior", "der", "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 40 110 Z"),
  z("deltoides_anterior", "izq", "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 160 110 Z"),
  z("pectoral", "der", "M 62 88 L 99 88 L 99 125 L 64 125 Z"),
  z("pectoral", "izq", "M 101 88 L 138 88 L 136 125 L 101 125 Z"),
  z("abdomen", null, "M 68 128 L 132 128 L 132 192 L 68 192 Z"),
  z("oblicuo", "der", "M 57 130 L 66 130 L 66 192 L 61 192 Z"),
  z("oblicuo", "izq", "M 143 130 L 134 130 L 134 192 L 139 192 Z"),
  z("psoas", "der", "M 64 196 L 98 196 L 98 232 L 68 232 Z"),
  z("psoas", "izq", "M 102 196 L 136 196 L 132 232 L 102 232 Z"),
  z("antebrazo", "der", "M 33 175 L 53 175 L 51 226 L 31 226 Z"),
  z("antebrazo", "izq", "M 147 175 L 167 175 L 169 226 L 149 226 Z"),
  z("muneca", "der", "M 30 229 L 51 229 L 50 242 L 29 242 Z"),
  z("muneca", "izq", "M 149 229 L 170 229 L 171 242 L 150 242 Z"),
  z("cuadriceps", "der", "M 60 238 L 85 238 L 83 317 L 60 317 Z"),
  z("aductores", "der", "M 87 238 L 97 238 L 92 317 L 85 317 Z"),
  z("aductores", "izq", "M 103 238 L 113 238 L 115 317 L 108 317 Z"),
  z("cuadriceps", "izq", "M 115 238 L 140 238 L 140 317 L 117 317 Z"),
  z("rodilla", "der", "M 60 320 L 92 320 L 90 340 L 62 340 Z"),
  z("rodilla", "izq", "M 108 320 L 140 320 L 138 340 L 110 340 Z"),
  z("tibial", "der", "M 64 343 L 82 343 L 80 404 L 66 404 Z"),
  z("tibial", "izq", "M 118 343 L 136 343 L 134 404 L 120 404 Z"),
  z("tobillo", "der", "M 62 407 L 90 407 L 90 417 L 61 417 Z"),
  z("tobillo", "izq", "M 110 407 L 138 407 L 139 417 L 110 417 Z"),
  z("pie", "der", "M 60 420 L 90 420 L 90 432 L 56 432 Z"),
  z("pie", "izq", "M 110 420 L 140 420 L 144 432 L 110 432 Z"),
];

// Back: the player's LEFT is on the viewer's LEFT (x < 100).
const BACK: PainZoneShape[] = [
  z("trapecio", "izq", "M 62 86 L 99 78 L 99 108 L 70 104 Z"),
  z("trapecio", "der", "M 138 86 L 101 78 L 101 108 L 130 104 Z"),
  z("deltoides_posterior", "izq", "M 38 90 A 16 12 0 0 0 60 90 L 60 110 L 40 110 Z"),
  z("deltoides_posterior", "der", "M 162 90 A 16 12 0 0 1 140 90 L 140 110 L 160 110 Z"),
  z("triceps", "izq", "M 35 113 L 55 113 L 53 175 L 33 175 Z"),
  z("triceps", "der", "M 145 113 L 165 113 L 167 175 L 147 175 Z"),
  z("dorsal", "izq", "M 60 111 L 94 111 L 94 158 L 64 150 Z"),
  z("dorsal", "der", "M 140 111 L 106 111 L 106 158 L 136 150 Z"),
  z("columna_dorsal", null, "M 95 111 L 105 111 L 105 160 L 95 160 Z"),
  z("columna_lumbar", null, "M 66 162 L 134 162 L 136 194 L 64 194 Z"),
  z("gluteo", "izq", "M 62 197 L 99 197 L 99 236 L 58 236 Z"),
  z("gluteo", "der", "M 101 197 L 138 197 L 142 236 L 101 236 Z"),
  z("isquiotibiales", "izq", "M 60 239 L 96 239 L 92 317 L 60 317 Z"),
  z("isquiotibiales", "der", "M 104 239 L 140 239 L 140 317 L 108 317 Z"),
  z("popliteo", "izq", "M 62 320 L 90 320 L 90 338 L 62 338 Z"),
  z("popliteo", "der", "M 110 320 L 138 320 L 138 338 L 110 338 Z"),
  z("gemelos", "izq", "M 62 341 L 90 341 L 86 408 L 64 408 Z"),
  z("gemelos", "der", "M 110 341 L 138 341 L 136 408 L 114 408 Z"),
];

export const PAIN_VIEWS: PainView[] = [
  { key: "front", label: "Frontal", zones: FRONT },
  { key: "back", label: "Posterior", zones: BACK },
];

/** The id a backend `{zone, side}` cell is drawn under (null: not drawable). */
export function painZoneId(zone: string, side: string | null): string | null {
  const id = side ? `${zone}_${side}` : zone;
  return PAIN_VIEWS.some((v) => v.zones.some((s) => s.id === id)) ? id : null;
}
