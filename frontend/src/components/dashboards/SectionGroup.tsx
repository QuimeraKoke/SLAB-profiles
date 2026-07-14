"use client";

import React, { useState } from "react";
import { ArrowLeft, ArrowRight, Trash2 } from "lucide-react";

import type { DashboardSection } from "@/lib/types";
import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { ApiError } from "@/lib/api";
import {
  SPAN_PRESETS,
  deletePlayerWidget,
  reorderPlayerWidgets,
  updatePlayerWidget,
} from "@/lib/panelBuilder";
import { renderWidget } from "./widgets";
import styles from "./SectionGroup.module.css";

interface SectionGroupProps {
  section: DashboardSection;
  /** When rendering a player profile, enables per-player widget features
   *  (e.g. the position-comparison toggle on line charts). */
  playerId?: string;
  /** §5b — edit mode surfaces per-widget arrange controls. */
  editMode?: boolean;
  /** Refetch after a successful arrange mutation. */
  onChanged?: () => void;
}

export default function SectionGroup({ section, playerId, editMode = false, onChanged }: SectionGroupProps) {
  const [collapsed, setCollapsed] = useState(section.default_collapsed);
  const [busy, setBusy] = useState(false);
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const showHeader = section.title.length > 0;
  const canCollapse = section.is_collapsible && showHeader && !editMode;
  const widgets = section.widgets;

  async function run(fn: () => Promise<unknown>, okMsg: string) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      toast.success(okMsg);
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo aplicar el cambio.");
    } finally {
      setBusy(false);
    }
  }
  function move(index: number, dir: -1 | 1) {
    const next = index + dir;
    if (next < 0 || next >= widgets.length) return;
    const ids = widgets.map((w) => w.id);
    [ids[index], ids[next]] = [ids[next], ids[index]];
    run(() => reorderPlayerWidgets(ids), "Orden actualizado.");
  }
  function resize(id: string, span: number) {
    run(() => updatePlayerWidget(id, { column_span: span }), "Tamaño actualizado.");
  }
  async function remove(id: string, title: string) {
    const ok = await confirm({
      title: "Quitar widget",
      message: `¿Quitar "${title}" del panel? Podés volver a agregarlo después.`,
      confirmLabel: "Quitar",
      variant: "danger",
    });
    if (ok) run(() => deletePlayerWidget(id), "Widget quitado.");
  }

  return (
    <section className={styles.section}>
      {showHeader && (
        <header
          className={`${styles.header} ${canCollapse ? styles.clickable : ""}`}
          onClick={canCollapse ? () => setCollapsed((c) => !c) : undefined}
          role={canCollapse ? "button" : undefined}
          tabIndex={canCollapse ? 0 : undefined}
          onKeyDown={
            canCollapse
              ? (e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setCollapsed((c) => !c);
                  }
                }
              : undefined
          }
        >
          <h3 className={styles.title}>{section.title}</h3>
          {canCollapse && (
            <span className={styles.chevron} aria-hidden>
              {collapsed ? "▾" : "▴"}
            </span>
          )}
        </header>
      )}

      {!collapsed && (
        <div className={styles.grid}>
          {widgets.map((widget, index) => (
            <div
              key={widget.id}
              className={`${styles.cell} ${editMode ? styles.cellEditing : ""}`}
              style={
                {
                  "--col-span": widget.column_span,
                  // Tablet rule: max 2 widgets per row. ≤6 stays 6 (pair),
                  // >6 promotes to 12 (full row). Mobile overrides to 12 in CSS.
                  "--tablet-col-span": widget.column_span <= 6 ? 6 : 12,
                } as React.CSSProperties
              }
            >
              {editMode && (
                <div className={styles.editBar}>
                  <div className={styles.editGroup}>
                    <button type="button" className={styles.editBtn} disabled={busy || index === 0}
                      onClick={() => move(index, -1)} aria-label="Mover a la izquierda" title="Mover a la izquierda">
                      <ArrowLeft size={15} />
                    </button>
                    <button type="button" className={styles.editBtn} disabled={busy || index === widgets.length - 1}
                      onClick={() => move(index, 1)} aria-label="Mover a la derecha" title="Mover a la derecha">
                      <ArrowRight size={15} />
                    </button>
                  </div>
                  <div className={styles.editGroup} role="group" aria-label="Tamaño">
                    {SPAN_PRESETS.map((p) => (
                      <button key={p.value} type="button"
                        className={widget.column_span === p.value ? styles.spanOn : styles.spanBtn}
                        disabled={busy} onClick={() => resize(widget.id, p.value)} title={`Ancho: ${p.label}`}>
                        {p.label}
                      </button>
                    ))}
                  </div>
                  <button type="button" className={styles.removeBtn} disabled={busy}
                    onClick={() => remove(widget.id, widget.title)} aria-label="Quitar widget" title="Quitar">
                    <Trash2 size={15} />
                  </button>
                </div>
              )}
              {renderWidget(widget, playerId)}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
