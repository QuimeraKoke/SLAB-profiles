import type { Category } from "./types";

/** One-line label for contexts that cannot style part of the text.
 *
 * A native `<option>` is the case that forces this to exist: the club wants the
 * season's rung as a small aside next to the serie, and inside an option there
 * is no small. Joined with an en dash so it still reads as an aside rather than
 * a second name.
 */
export function categoryLabel(c: Pick<Category, "label" | "label_hint" | "name">): string {
  const base = c.label || c.name;
  return c.label_hint ? `${base} — ${c.label_hint}` : base;
}
