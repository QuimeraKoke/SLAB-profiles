"use client";

import React from "react";
import Link from "next/link";
import { MessageSquarePlus, NotebookPen, Trash2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import type { DailyNote } from "./types";
import styles from "./NotesPanel.module.css";

export default function NotesPanel({
  notes,
  canNote,
  onAdd,
  onDeleted,
}: {
  notes: DailyNote[];
  canNote: boolean;
  onAdd: () => void;
  onDeleted: () => void;
}) {
  const { confirm } = useConfirm();
  const { toast } = useToast();

  async function remove(note: DailyNote) {
    const ok = await confirm({
      title: "Eliminar nota",
      message: `Se eliminará la nota sobre ${note.player_name}. Esta acción no se puede deshacer.`,
      confirmLabel: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api(`/daily-notes/${note.id}`, { method: "DELETE" });
      toast.success("Nota eliminada.");
      onDeleted();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar la nota.");
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="daily-notes-title">
      <header className={styles.head}>
        <h2 id="daily-notes-title" className={styles.title}>
          <NotebookPen size={16} aria-hidden="true" />
          Pauta del día
        </h2>
        {canNote && (
          <button className={styles.addBtn} onClick={onAdd}>
            <MessageSquarePlus size={14} aria-hidden="true" />
            Agregar nota
          </button>
        )}
      </header>
      {notes.length === 0 ? (
        <p className={styles.empty}>
          Aún no hay notas para esta fecha. Lo que se decida en la reunión queda
          registrado aquí, por jugador y por área.
        </p>
      ) : (
        <ul className={styles.list}>
          {notes.map((n) => (
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
                  {new Date(n.created_at).toLocaleTimeString("es-CL", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
              {n.mine && (
                <button
                  className={styles.trash}
                  onClick={() => remove(n)}
                  aria-label={`Eliminar nota sobre ${n.player_name}`}
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
