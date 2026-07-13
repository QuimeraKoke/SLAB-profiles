"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Database, Download } from "lucide-react";

import { api, getToken } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import styles from "./page.module.css";

interface TemplateLite {
  id: string;
  name: string;
  department: { id: string; name: string; slug: string };
}
interface PlayerLite {
  id: string;
  first_name: string;
  last_name: string;
  position: { id: string; name: string; abbreviation: string; role: string } | null;
}

/**
 * "Exportar datos" (§5) — self-service raw-data download. Pick exams (by
 * department), players (grouped by position, with per-position select-all)
 * and a date range, then pull an Excel workbook (one sheet per exam, row =
 * jugador-fecha, calculated included). Empty selections = everything.
 */
export default function ExportarPage() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const [templates, setTemplates] = useState<TemplateLite[]>([]);
  const [players, setPlayers] = useState<PlayerLite[]>([]);
  const [selTpl, setSelTpl] = useState<Set<string>>(new Set());
  const [selPl, setSelPl] = useState<Set<string>>(new Set());
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    setSelTpl(new Set());
    setSelPl(new Set());
    api<TemplateLite[]>(`/templates?category_id=${categoryId}`)
      .then((t) => { if (!cancelled) setTemplates(t); })
      .catch(() => { if (!cancelled) setTemplates([]); });
    api<PlayerLite[]>(`/players?category_id=${categoryId}`)
      .then((p) => { if (!cancelled) setPlayers(p); })
      .catch(() => { if (!cancelled) setPlayers([]); });
    return () => { cancelled = true; };
  }, [categoryId]);

  const byDept = useMemo(() => {
    const m = new Map<string, { name: string; items: TemplateLite[] }>();
    for (const t of templates) {
      const key = t.department?.slug ?? "—";
      if (!m.has(key)) m.set(key, { name: t.department?.name ?? "Otros", items: [] });
      m.get(key)!.items.push(t);
    }
    return [...m.values()];
  }, [templates]);

  const byPosition = useMemo(() => {
    const m = new Map<string, PlayerLite[]>();
    for (const p of players) {
      const key = p.position?.role || p.position?.name || "Sin posición";
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(p);
    }
    return [...m.entries()].map(([label, items]) => ({ label, items }));
  }, [players]);

  function toggle(set: Set<string>, setSet: (s: Set<string>) => void, id: string) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSet(next);
  }

  function toggleGroup(items: PlayerLite[]) {
    const ids = items.map((p) => p.id);
    const allSelected = ids.every((id) => selPl.has(id));
    const next = new Set(selPl);
    for (const id of ids) {
      if (allSelected) next.delete(id);
      else next.add(id);
    }
    setSelPl(next);
  }

  async function download() {
    if (!categoryId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({ category_id: categoryId });
      if (selTpl.size) params.set("templates", [...selTpl].join(","));
      if (selPl.size) params.set("player_ids", [...selPl].join(","));
      if (from) params.set("date_from", from);
      if (to) params.set("date_to", to);
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";
      const token = getToken();
      const headers = new Headers();
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const res = await fetch(`${apiUrl}/export/results.xlsx?${params.toString()}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `export-${(categoryName || "datos").replace(/\s+/g, "_")}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("No se pudo generar el archivo. Intentá nuevamente.");
    } finally {
      setBusy(false);
    }
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.h1}>
          <Database size={20} aria-hidden="true" /> Exportar datos
        </h1>
        <p className={styles.sub}>{categoryName} · descargá el dato crudo en Excel</p>
      </header>

      <section className={styles.dateRow}>
        <span className={styles.dateRowLabel}>Rango de fechas</span>
        <p className={styles.hint}>Vacío = todo el historial. Sin selección se exportan todos.</p>
        <div className={styles.dateInputs}>
          <label>
            Desde
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label>
            Hasta
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
        </div>
      </section>

      <section className={styles.card}>
        <h2 className={styles.cardTitle}>
          Exámenes {selTpl.size > 0 && <span className={styles.badge}>{selTpl.size}</span>}
        </h2>
        {byDept.map((d) => (
          <div key={d.name} className={styles.deptBlock}>
            <div className={styles.deptName}>{d.name}</div>
            <div className={styles.examGrid}>
              {d.items.map((t) => (
                <label key={t.id} className={styles.check}>
                  <input
                    type="checkbox"
                    checked={selTpl.has(t.id)}
                    onChange={() => toggle(selTpl, setSelTpl, t.id)}
                  />
                  {t.name}
                </label>
              ))}
            </div>
          </div>
        ))}
        {templates.length === 0 && <p className={styles.muted}>Sin exámenes.</p>}
      </section>

      <section className={styles.playersCard}>
        <h2 className={styles.cardTitle}>
          Jugadores {selPl.size > 0 && <span className={styles.badge}>{selPl.size}</span>}
        </h2>
        {byPosition.map((g) => {
          const ids = g.items.map((p) => p.id);
          const sel = ids.filter((id) => selPl.has(id)).length;
          return (
            <div key={g.label} className={styles.posGroup}>
              <label className={styles.posHead}>
                <input
                  type="checkbox"
                  ref={(el) => {
                    if (el) {
                      el.checked = sel === ids.length && sel > 0;
                      el.indeterminate = sel > 0 && sel < ids.length;
                    }
                  }}
                  onChange={() => toggleGroup(g.items)}
                />
                {g.label}
                <span className={styles.posCount}>{sel}/{ids.length}</span>
              </label>
              <div className={styles.posGrid}>
                {g.items.map((p) => (
                  <label key={p.id} className={styles.check}>
                    <input
                      type="checkbox"
                      checked={selPl.has(p.id)}
                      onChange={() => toggle(selPl, setSelPl, p.id)}
                    />
                    {p.first_name} {p.last_name}
                  </label>
                ))}
              </div>
            </div>
          );
        })}
        {players.length === 0 && <p className={styles.muted}>Sin jugadores.</p>}
      </section>

      <div className={styles.footer}>
        <button
          type="button"
          className={styles.downloadBtn}
          onClick={download}
          disabled={busy}
        >
          <Download size={16} aria-hidden="true" /> {busy ? "Generando…" : "Descargar Excel"}
        </button>
        {error && <span className={styles.error} role="alert">{error}</span>}
      </div>
    </div>
  );
}
