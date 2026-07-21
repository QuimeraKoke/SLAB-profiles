"use client";

import React from "react";
import Link from "next/link";
import { ClipboardList, ClipboardPlus, Trash2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DailyNote } from "./types";
// Reuse the Pauta del día panel's styling for visual parity.
import styles from "./NotesPanel.module.css";

function fmtDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "short",
  });
}

/** Rail panel that lists the squad's standing "plan de trabajo" (KIND_PLAN),
 *  mirroring `NotesPanel` (Pauta del día). Full coverage — every player with a
 *  vigente plan, regardless of injured/alert status. */
export default function PlansPanel({
  plans,
  canNote,
  onAdd,
  onChanged,
}: {
  plans: DailyNote[];
  canNote: boolean;
  onAdd: () => void;
  onChanged: () => void;
}) {
  const { confirm } = useConfirm();
  const { toast } = useToast();

  async function remove(n: DailyNote) {
    const ok = await confirm({
      title: "Eliminar entrada del plan",
      message: `Se eliminará esta entrada del plan de trabajo de ${n.player_name}. No se puede deshacer.`,
      confirmLabel: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api(`/daily-notes/${n.id}`, { method: "DELETE" });
      toast.success("Entrada eliminada.");
      onChanged();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar.");
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="daily-plans-title">
      <header className={styles.head}>
        <h2 id="daily-plans-title" className={styles.title}>
          <ClipboardList size={16} aria-hidden="true" />
          Plan de trabajo
        </h2>
        {canNote && (
          <button className={styles.addBtn} onClick={onAdd}>
            <ClipboardPlus size={14} aria-hidden="true" />
            Agregar plan
          </button>
        )}
      </header>
      {plans.length === 0 ? (
        <p className={styles.empty}>
          Sin planes de trabajo vigentes. Cargá la directriz de cada jugador —
          bloque de fuerza, progresión de carrera, plan nutricional… — y queda
          visible acá hasta que se actualice.
        </p>
      ) : (
        <ul className={styles.list}>
          {plans.map((n) => (
            <li key={n.id} className={styles.row}>
              <span className={styles.dept}>{n.department?.name ?? "General"}</span>
              <div className={styles.body}>
                <Link href={`/perfil/${n.player_id}`} className={styles.player}>
                  {n.player_name}
                </Link>
                <span className={styles.text}>{n.text}</span>
                <span className={styles.byline}>
                  {n.author}
                  {" · "}
                  {fmtDay(n.date)}
                </span>
              </div>
              {n.mine && (
                <button
                  className={styles.trash}
                  onClick={() => remove(n)}
                  aria-label={`Eliminar entrada del plan de ${n.player_name}`}
                >
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
