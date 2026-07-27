"use client";

import { ArrowUpRight } from "lucide-react";

import styles from "./CallUpMark.module.css";

/** Small indigo flag shown next to a player who appears in a team report on
 *  CALL-UP (their home category differs). Mirrors the roster's call-up badge
 *  so the same player reads the same across surfaces. Renders nothing when
 *  `show` is false so call sites can drop it inline unconditionally. */
export default function CallUpMark({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span
      className={styles.mark}
      title="Convocado · categoría secundaria (no cuenta en los totales del plantel)"
    >
      <ArrowUpRight size={11} aria-hidden="true" />
      conv.
    </span>
  );
}
