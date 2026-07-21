"use client";

import React from "react";
import { ClipboardList, Trash2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DailyNote } from "./types";
import styles from "./PlanList.module.css";

function fmtDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "short",
  });
}

/** The player's standing "plan de trabajo" (KIND_PLAN entries, newest first).
 *  Read display + delete on one's own entries. Compact — meant to sit inside
 *  the lesionado / alerta cards. */
export default function PlanList({
  plans,
  canNote,
  onChanged,
}: {
  plans: DailyNote[];
  canNote: boolean;
  onChanged: () => void;
}) {
  const { confirm } = useConfirm();
  const { toast } = useToast();

  async function remove(n: DailyNote) {
    const ok = await confirm({
      title: "Eliminar entrada del plan",
      message: "Se eliminará esta entrada del plan de trabajo. No se puede deshacer.",
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
    <div className={styles.wrap}>
      <span className={styles.label}>
        <ClipboardList size={12} aria-hidden="true" />
        Plan de trabajo
      </span>
      {plans.length === 0 ? (
        <span className={styles.empty}>Sin plan de trabajo vigente.</span>
      ) : (
        <ul className={styles.list}>
          {plans.map((n) => (
            <li key={n.id} className={styles.row}>
              {n.department && <span className={styles.dept}>{n.department.name}</span>}
              <span className={styles.text}>{n.text}</span>
              <span className={styles.meta}>
                {n.author}
                {" · "}
                {fmtDay(n.date)}
              </span>
              {canNote && n.mine && (
                <button
                  type="button"
                  className={styles.trash}
                  onClick={() => remove(n)}
                  aria-label="Eliminar entrada del plan"
                >
                  <Trash2 size={13} aria-hidden="true" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
