"use client";

/**
 * The department's team layouts ("vistas"), managed from the report's edit
 * mode: create, rename, reorder, delete. With one layout the menu shows the
 * department as a plain item; with two or more it becomes a submenu
 * (Dashboard → Médico → General / Lesiones), in this order — the first is
 * what `/reportes/<dept>` opens.
 *
 * Every change dispatches `TEAM_LAYOUTS_CHANGED` (through the page's
 * `onChanged`) so the sidebar refetches its submenu.
 */

import React, { useState } from "react";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";

import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { api, ApiError } from "@/lib/api";
import type { TeamLayoutRef } from "@/lib/types";

import styles from "./LayoutManager.module.css";

export const TEAM_LAYOUTS_CHANGED = "slab:team-layouts-changed";

interface Props {
  deptSlug: string;
  departmentName: string;
  categoryId: string;
  layouts: TeamLayoutRef[];
  currentSlug: string | null;
  /** `goTo`: a layout slug to open, `null` for the department's default, or
   *  undefined to stay and just refetch. */
  onChanged: (goTo?: string | null) => void;
}

export default function LayoutManager({
  deptSlug, departmentName, categoryId, layouts, currentSlug, onChanged,
}: Props) {
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [creando, setCreando] = useState(false);
  const [nuevo, setNuevo] = useState("");
  const [renombrando, setRenombrando] = useState<string | null>(null);
  const [nombre, setNombre] = useState("");
  const [error, setError] = useState<string | null>(null);

  const correr = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  const crear = () => correr(async () => {
    const creado = await api<TeamLayoutRef>(`/reports/${deptSlug}/layouts`, {
      method: "POST",
      body: JSON.stringify({ category_id: categoryId, name: nuevo }),
    });
    toast.success(`Vista «${creado.name}» creada.`);
    setCreando(false);
    setNuevo("");
    onChanged(creado.slug);
  });

  const renombrar = (l: TeamLayoutRef) => correr(async () => {
    const r = await api<TeamLayoutRef>(`/reports/layouts/${l.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: nombre }),
    });
    toast.success("Vista renombrada.");
    setRenombrando(null);
    // Renaming moves the slug: follow it if it is the one on screen.
    onChanged(l.slug === currentSlug ? r.slug : undefined);
  });

  const mover = (i: number, dir: -1 | 1) => correr(async () => {
    const orden = [...layouts];
    const [x] = orden.splice(i, 1);
    orden.splice(i + dir, 0, x);
    await api(`/reports/layouts/reorder`, {
      method: "POST",
      body: JSON.stringify({ layout_ids: orden.map((l) => l.id) }),
    });
    onChanged();
  });

  const eliminar = async (l: TeamLayoutRef) => {
    const ok = await confirm({
      title: `Eliminar la vista «${l.name}»`,
      message: `Se eliminan la vista y todos sus gráficos de ${departmentName}. No se puede deshacer.`,
      confirmLabel: "Eliminar vista",
      variant: "danger",
    });
    if (!ok) return;
    await correr(async () => {
      await api(`/reports/layouts/${l.id}`, { method: "DELETE" });
      toast.success(`Vista «${l.name}» eliminada.`);
      onChanged(l.slug === currentSlug ? null : undefined);
    });
  };

  return (
    <section className={styles.panel} aria-labelledby="layout-manager-title">
      <header className={styles.head}>
        <h2 id="layout-manager-title" className={styles.title}>Vistas de {departmentName}</h2>
        <p className={styles.hint}>
          {layouts.length === 1
            ? "Con una sola vista, el menú muestra el departamento como siempre. Agregá otra y se vuelve un submenú."
            : "El menú muestra estas vistas en este orden; la primera es la que abre el departamento."}
        </p>
      </header>

      <ol className={styles.list}>
        {layouts.map((l, i) => (
          <li key={l.id} className={`${styles.row} ${l.slug === currentSlug ? styles.current : ""}`}>
            {renombrando === l.id ? (
              <form className={styles.inline} onSubmit={(e) => { e.preventDefault(); renombrar(l); }}>
                <input className={styles.input} value={nombre} autoFocus maxLength={120}
                  aria-label={`Nuevo nombre para ${l.name}`} onChange={(e) => setNombre(e.target.value)}
                  aria-invalid={error ? true : undefined} aria-describedby={error ? "layout-mgr-error" : undefined} />
                <button type="submit" className={styles.primary} disabled={busy || !nombre.trim()}>Guardar</button>
                <button type="button" className={styles.ghost} onClick={() => setRenombrando(null)}>Cancelar</button>
              </form>
            ) : (
              <>
                <span className={styles.name}>{l.name}</span>
                {i === 0 && layouts.length > 1 && <span className={styles.badge}>por defecto</span>}
                <span className={styles.actions}>
                  <button type="button" className={styles.icon} disabled={busy || i === 0}
                    onClick={() => mover(i, -1)} aria-label={`Subir ${l.name}`}><ArrowUp size={14} /></button>
                  <button type="button" className={styles.icon} disabled={busy || i === layouts.length - 1}
                    onClick={() => mover(i, 1)} aria-label={`Bajar ${l.name}`}><ArrowDown size={14} /></button>
                  <button type="button" className={styles.icon} disabled={busy}
                    onClick={() => { setRenombrando(l.id); setNombre(l.name); setError(null); }}
                    aria-label={`Renombrar ${l.name}`}><Pencil size={14} /></button>
                  <button type="button" className={`${styles.icon} ${styles.danger}`}
                    disabled={busy || layouts.length === 1}
                    title={layouts.length === 1 ? "Es la única vista: no se puede eliminar" : undefined}
                    onClick={() => eliminar(l)} aria-label={`Eliminar ${l.name}`}><Trash2 size={14} /></button>
                </span>
              </>
            )}
          </li>
        ))}
      </ol>

      {creando ? (
        <form className={styles.inline} onSubmit={(e) => { e.preventDefault(); crear(); }}>
          <input className={styles.input} value={nuevo} autoFocus maxLength={120}
            placeholder="Nombre de la vista (ej. Lesiones)" aria-label="Nombre de la nueva vista"
            onChange={(e) => setNuevo(e.target.value)}
            aria-invalid={error ? true : undefined} aria-describedby={error ? "layout-mgr-error" : undefined} />
          <button type="submit" className={styles.primary} disabled={busy || !nuevo.trim()}>Crear</button>
          <button type="button" className={styles.ghost} onClick={() => { setCreando(false); setNuevo(""); }}>
            Cancelar
          </button>
        </form>
      ) : (
        <button type="button" className={styles.add} onClick={() => { setCreando(true); setError(null); }}>
          <Plus size={14} aria-hidden="true" /> Nueva vista
        </button>
      )}

      {error && <p id="layout-mgr-error" role="alert" className={styles.error}>{error}</p>}
    </section>
  );
}
