/**
 * Shared primitives for the Excel exporters under `lib/export/`.
 *
 * Both `teamReport` (cross-roster) and `playerReport` (single-player)
 * lean on these helpers — keeping the sheet-name rules, scalar coercion
 * and filename format consistent across the two flows.
 */

import type * as XLSXType from "xlsx";

export type AOA = (string | number | null)[][];

/** Coerce arbitrary JSONB cell values into something Excel-friendly.
 *  Numbers stay as numbers (formulas keep working downstream); everything
 *  else becomes a string. */
export function formatScalar(v: unknown): string | number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return v;
  if (typeof v === "boolean") return v ? "Sí" : "No";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** Excel sheet names: max 31 chars, no `[]:*?/\\`. We also strip control
 *  characters and trim whitespace, then append " (N)" for duplicates. */
export function uniqueSheetName(raw: string, used: Set<string>): string {
  const cleaned = raw
    .replace(/[\[\]:*?/\\]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 28) || "Hoja";
  let candidate = cleaned;
  let i = 2;
  while (used.has(candidate)) {
    const suffix = ` (${i})`;
    candidate = cleaned.slice(0, 31 - suffix.length) + suffix;
    i += 1;
  }
  return candidate;
}

/** Human-friendly "YYYY-MM-DD HH:MM" for sheet metadata. Local time —
 *  the user is the consumer, not a system. */
export function formatDateTime(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

/** Date-only ISO portion. Used in filenames. */
export function formatDateOnly(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

/** Build a workbook filename from arbitrary segments. Each segment is
 *  slug-safe-ified independently so player names, dept slugs, etc. don't
 *  clash with the filesystem. `.xlsx` is appended automatically. */
export function buildFilename(segments: string[], generatedAt: Date): string {
  const safe = segments
    .map((s) => s.toString().trim())
    .filter(Boolean)
    .map(slugSegment);
  return `${safe.join("-")}-${formatDateOnly(generatedAt)}.xlsx`;
}

/** Lowercase, ASCII-only, hyphen-separated slug. Strips diacritics so
 *  Spanish names ("Pérez", "González") become URL/filename friendly. */
function slugSegment(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Re-export the SheetJS namespace so callers don't have to repeat the
 *  type-only import. The runtime module is loaded lazily by callers via
 *  `await import("xlsx")` — we never ship it in the initial bundle. */
export type { XLSXType };
