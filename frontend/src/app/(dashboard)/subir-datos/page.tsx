"use client";

import React, { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Upload } from "lucide-react";

import { api } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { useToast } from "@/components/ui/Toast/Toast";
import BulkIngestForm from "@/components/forms/BulkIngestForm";
import TeamTableForm from "@/components/forms/TeamTableForm";
import type { ExamTemplate } from "@/lib/types";
import styles from "./page.module.css";

type TeamMode = "team_table" | "bulk_ingest";
const MODE_LABEL: Record<TeamMode, string> = {
  team_table: "Tabla por equipo",
  bulk_ingest: "Subir archivo",
};

function teamModes(t: ExamTemplate): TeamMode[] {
  const modes = t.input_config?.input_modes ?? [];
  return (["team_table", "bulk_ingest"] as TeamMode[]).filter((m) => modes.includes(m));
}

/**
 * "Subir datos" (§7.1) — self-service squad-wide data capture without leaving
 * to a player profile. Pick a department → template, then capture via the
 * existing team-table / bulk-file forms (category-scoped). Single-player entry
 * stays contextual on the profile. Mirror of "Exportar datos".
 */
export default function SubirDatosPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const { toast } = useToast();
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [selected, setSelected] = useState<ExamTemplate | null>(null);
  const [mode, setMode] = useState<TeamMode | null>(null);

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    // Reset off the synchronous effect body (React 19 set-state-in-effect).
    Promise.resolve().then(() => {
      if (cancelled) return;
      setSelected(null);
      setMode(null);
    });
    api<ExamTemplate[]>(`/templates?category_id=${categoryId}`)
      .then((all) => {
        if (!cancelled) setTemplates(all.filter((t) => teamModes(t).length > 0));
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  const byDept = useMemo(() => {
    const m = new Map<string, { name: string; items: ExamTemplate[] }>();
    for (const t of templates) {
      const key = t.department?.slug ?? "—";
      if (!m.has(key)) m.set(key, { name: t.department?.name ?? "Otros", items: [] });
      m.get(key)!.items.push(t);
    }
    return [...m.values()];
  }, [templates]);

  function pick(t: ExamTemplate) {
    const modes = teamModes(t);
    setSelected(t);
    setMode(modes[0]);
  }
  function reset() {
    setSelected(null);
    setMode(null);
  }
  function done() {
    toast.success("Datos guardados.");
    reset();
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;

  // ── Capture view ──────────────────────────────────────────────────────────
  if (selected && mode) {
    const modes = teamModes(selected);
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <button type="button" className={styles.backBtn} onClick={reset}>
            <ArrowLeft size={16} aria-hidden="true" /> Volver
          </button>
          <div>
            <h1 className={styles.h1}>{selected.name}</h1>
            <p className={styles.sub}>{selected.department?.name} · {categoryName}</p>
          </div>
        </header>

        {modes.length > 1 && (
          <div className={styles.modeToggle} role="group" aria-label="Modo de carga">
            {modes.map((m) => (
              <button
                key={m}
                type="button"
                className={mode === m ? styles.modeOn : styles.modeBtn}
                onClick={() => setMode(m)}
              >
                {MODE_LABEL[m]}
              </button>
            ))}
          </div>
        )}

        {mode === "team_table" ? (
          <TeamTableForm
            template={selected}
            categoryId={categoryId}
            onCommitted={done}
            onCancel={reset}
          />
        ) : (
          <BulkIngestForm
            template={selected}
            categoryId={categoryId}
            onCommitted={done}
            onCancel={reset}
          />
        )}
      </div>
    );
  }

  // ── Picker view ─────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>
            <Upload size={20} aria-hidden="true" /> Subir datos
          </h1>
          <p className={styles.sub}>{categoryName} · carga por equipo (tabla o archivo)</p>
        </div>
      </header>

      {byDept.length === 0 ? (
        <div className={styles.empty}>
          No hay exámenes con carga por equipo para esta categoría. La carga
          individual se hace desde la ficha del jugador.
        </div>
      ) : (
        byDept.map((d) => (
          <section key={d.name} className={styles.card}>
            <div className={styles.deptName}>{d.name}</div>
            <div className={styles.tplGrid}>
              {d.items.map((t) => (
                <button key={t.id} type="button" className={styles.tplBtn} onClick={() => pick(t)}>
                  <span className={styles.tplName}>{t.name}</span>
                  <span className={styles.tplModes}>
                    {teamModes(t).map((m) => MODE_LABEL[m]).join(" · ")}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
