"use client";

/**
 * Chips "tipo de día" (MD-4, MD-3 … MD, MD+1): filtran por día de microciclo
 * los widgets GPS que los siguen (`display_config.md_filter`).
 *
 * La URL es la fuente de verdad (`?md=MD-4,MD-3`): el filtro sobrevive a un
 * refresh y se puede compartir. Sin selección = todos los días.
 */

import React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { MdFilterConfig } from "@/lib/types";
import styles from "./MdFilter.module.css";

/** Los días elegidos en la URL, en el formato que espera el backend. */
export function useMdParam(): string {
  return useSearchParams().get("md") ?? "";
}

export default function MdFilter({ config }: { config: MdFilterConfig | null | undefined }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  if (!config?.enabled || config.options.length === 0) return null;

  const selected = new Set(config.selected);
  const write = (next: string[]) => {
    const sp = new URLSearchParams(searchParams.toString());
    if (next.length) sp.set("md", next.join(","));
    else sp.delete("md");
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  const toggle = (label: string) => {
    const next = new Set(selected);
    if (next.has(label)) next.delete(label);
    else next.add(label);
    // In microcycle order, as the options come.
    write(config.options.filter((o) => next.has(o)));
  };

  return (
    <div className={styles.bar} role="group" aria-label="Filtrar por tipo de día">
      <span className={styles.label}>Tipo de día</span>
      <button
        type="button"
        className={selected.size === 0 ? styles.chipOn : styles.chip}
        aria-pressed={selected.size === 0}
        onClick={() => write([])}
      >
        Todos
      </button>
      {config.options.map((o) => (
        <button
          key={o}
          type="button"
          className={selected.has(o) ? styles.chipOn : styles.chip}
          aria-pressed={selected.has(o)}
          onClick={() => toggle(o)}
        >
          {o}
        </button>
      ))}
    </div>
  );
}
