"use client";

import React, { createContext, useContext, useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import styles from "./Breadcrumbs.module.css";

/**
 * App-wide breadcrumb strip. Reads `usePathname()` and renders a trail of
 * `Inicio › Sección › Entidad › Acción` derived from the route segments.
 *
 * Static segments (equipo, partidos, …) are translated via SEGMENT_LABELS.
 * Dynamic segments (UUIDs, numeric IDs) need an entity label from the
 * detail page — the page calls `useBreadcrumbLabels({ [segment]: "Charles
 * Aránguiz" })` inside an effect, and the breadcrumb picks it up.
 *
 * Hidden on the root landing (`/`) and routes shallower than 1 segment.
 */

const SEGMENT_LABELS: Record<string, string> = {
  equipo: "Equipo",
  perfil: "Jugador",
  partidos: "Partidos",
  reportes: "Reportes",
  configuraciones: "Administración",
  jugadores: "Jugadores",
  registrar: "Registrar examen",
  editar: "Editar",
  nuevo: "Nuevo",
  uso: "Uso",
};

function isDynamicSegment(s: string): boolean {
  // UUID-ish (first 8-hex prefix is enough) or numeric ID.
  if (/^[0-9a-f]{8}-[0-9a-f]{4}/i.test(s)) return true;
  if (/^\d+$/.test(s)) return true;
  return false;
}

// ----- Context: pages populate per-segment entity labels --------------

type LabelMap = Record<string, string>;
type LabelSetter = React.Dispatch<React.SetStateAction<LabelMap>>;

const BreadcrumbContext = createContext<{
  labels: LabelMap;
  setLabels: LabelSetter;
} | null>(null);

export function BreadcrumbProvider({ children }: { children: React.ReactNode }) {
  const [labels, setLabels] = React.useState<LabelMap>({});
  const value = useMemo(() => ({ labels, setLabels }), [labels]);
  return (
    <BreadcrumbContext.Provider value={value}>
      {children}
    </BreadcrumbContext.Provider>
  );
}

/** Detail pages call this from a useEffect once their entity has loaded:
 *
 *     const setBreadcrumbLabel = useBreadcrumbLabel();
 *     useEffect(() => {
 *       if (player) setBreadcrumbLabel(player.id, `${player.first_name} ${player.last_name}`);
 *     }, [player]);
 *
 * Falls back to "…" if not yet set, so the breadcrumb is never blank.
 *
 * Uses the functional `setLabels` updater so concurrent writes from
 * sibling pages don't clobber each other (closure-staleness).
 */
export function useBreadcrumbLabel() {
  const ctx = useContext(BreadcrumbContext);
  const setLabels = ctx?.setLabels;
  return React.useCallback(
    (segment: string, label: string) => {
      setLabels?.((prev) => ({ ...prev, [segment]: label }));
    },
    [setLabels],
  );
}

// ----- Render ----------------------------------------------------------

export default function Breadcrumbs() {
  const pathname = usePathname();
  const ctx = useContext(BreadcrumbContext);
  const labels = ctx?.labels ?? {};

  // Don't render on the literal root or the login page.
  if (!pathname || pathname === "/" || pathname.startsWith("/login")) {
    return null;
  }

  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return null;

  // Build cumulative hrefs so each crumb is clickable.
  const crumbs = segments.map((seg, idx) => {
    const href = "/" + segments.slice(0, idx + 1).join("/");
    let label = SEGMENT_LABELS[seg];
    if (!label) {
      if (isDynamicSegment(seg)) {
        label = labels[seg] ?? "…";
      } else {
        // Unknown static segment — capitalize as a sane fallback.
        label = seg.charAt(0).toUpperCase() + seg.slice(1);
      }
    }
    return { href, label, isLast: idx === segments.length - 1 };
  });

  // Suppress the "Inicio" crumb when the user is already at /equipo —
  // otherwise the trail reads "Inicio › Equipo" with both linking to the
  // same URL, which looks like a duplicate to power users.
  const showHome = !(segments.length === 1 && segments[0] === "equipo");

  return (
    <nav aria-label="Migas de pan" className={styles.breadcrumbs}>
      <ol>
        {showHome && (
          <li>
            <Link href="/equipo" className={styles.link}>
              Inicio
            </Link>
          </li>
        )}
        {crumbs.map((c, i) => (
          <li key={c.href} className={styles.item}>
            {(showHome || i > 0) && (
              <ChevronRight size={14} aria-hidden="true" className={styles.sep} />
            )}
            {c.isLast ? (
              <span aria-current="page" className={styles.current}>
                {c.label}
              </span>
            ) : (
              <Link href={c.href} className={styles.link}>
                {c.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
