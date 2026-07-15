"use client";

import React, { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Upload } from "lucide-react";

import { api } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import { useToast } from "@/components/ui/Toast/Toast";
import BulkIngestForm from "@/components/forms/BulkIngestForm";
import TeamTableForm from "@/components/forms/TeamTableForm";
import DynamicUploader from "@/components/forms/DynamicUploader";
import type { ExamTemplate } from "@/lib/types";
import styles from "./page.module.css";

type Mode = "team_table" | "bulk_ingest" | "single";
const MODE_LABEL: Record<Mode, string> = {
  team_table: "Tabla por equipo",
  bulk_ingest: "Subir archivo",
  single: "Individual",
};

/** Every exam is enterable per-player (Individual). Templates that opt into
 *  team_table / bulk_ingest also offer those. So the picker lists ALL exams. */
function availableModes(t: ExamTemplate): Mode[] {
  const modes = t.input_config?.input_modes ?? [];
  const team = (["team_table", "bulk_ingest"] as Mode[]).filter((m) => modes.includes(m));
  return [...team, "single"];
}

/**
 * "Subir datos" (§7.1) — self-service data capture without leaving to a player
 * profile. Pick a department → exam, then capture via team-table / bulk-file
 * (category-scoped) OR individually (pick a player → the exam form). Lists
 * EVERY exam, not just the team-configured ones.
 */
export default function SubirDatosPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const { toast } = useToast();
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [players, setPlayers] = useState<{ id: string; name: string }[]>([]);
  const [selected, setSelected] = useState<ExamTemplate | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [singlePlayerId, setSinglePlayerId] = useState("");

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    // Reset off the synchronous effect body (React 19 set-state-in-effect).
    Promise.resolve().then(() => {
      if (cancelled) return;
      setSelected(null);
      setMode(null);
      setSinglePlayerId("");
    });
    api<ExamTemplate[]>(`/templates?category_id=${categoryId}`)
      .then((all) => {
        if (!cancelled) setTemplates(all.filter((t) => availableModes(t).length > 0));
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      });
    api<{ players: { id: string; name: string }[] }>(`/roster?category_id=${categoryId}`)
      .then((r) => {
        if (!cancelled) setPlayers(r.players.map((p) => ({ id: p.id, name: p.name })));
      })
      .catch(() => {
        if (!cancelled) setPlayers([]);
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
    setSelected(t);
    setMode(availableModes(t)[0]);
    setSinglePlayerId("");
  }
  function reset() {
    setSelected(null);
    setMode(null);
    setSinglePlayerId("");
  }
  function done() {
    toast.success("Datos guardados.");
    reset();
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;

  // ── Capture view ──────────────────────────────────────────────────────────
  if (selected && mode) {
    const modes = availableModes(selected);
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
                onClick={() => { setMode(m); setSinglePlayerId(""); }}
              >
                {MODE_LABEL[m]}
              </button>
            ))}
          </div>
        )}

        {mode === "team_table" && (
          <TeamTableForm
            template={selected}
            categoryId={categoryId}
            onCommitted={done}
            onCancel={reset}
          />
        )}
        {mode === "bulk_ingest" && (
          <BulkIngestForm
            template={selected}
            categoryId={categoryId}
            onCommitted={done}
            onCancel={reset}
          />
        )}
        {mode === "single" && (
          <div className={styles.singleWrap}>
            <label className={styles.playerPick}>
              <span className={styles.playerPickLabel}>Jugador</span>
              <select
                className={styles.playerSelect}
                value={singlePlayerId}
                onChange={(e) => setSinglePlayerId(e.target.value)}
              >
                <option value="">— elegí un jugador —</option>
                {players.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>
            {singlePlayerId ? (
              <DynamicUploader
                key={singlePlayerId}
                template={selected}
                playerId={singlePlayerId}
                onSaved={() => {
                  // Stay on the exam so the next player can be entered quickly.
                  toast.success("Datos guardados.");
                  setSinglePlayerId("");
                }}
                onCancel={reset}
              />
            ) : (
              <p className={styles.muted}>Elegí un jugador para cargar los datos.</p>
            )}
          </div>
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
          <p className={styles.sub}>{categoryName} · por equipo, archivo o individual</p>
        </div>
      </header>

      {byDept.length === 0 ? (
        <div className={styles.empty}>
          No hay exámenes para esta categoría.
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
                    {availableModes(t).map((m) => MODE_LABEL[m]).join(" · ")}
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
