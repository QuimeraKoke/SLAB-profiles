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
}

/**
 * "Exportar datos" (§5) — self-service raw-data download. Pick exams
 * (grouped by department), players and a date range, then pull an Excel
 * workbook (one sheet per exam, row = jugador-fecha, calculated included)
 * from GET /export/results.xlsx. Empty selections = everything.
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

  function toggle(set: Set<string>, setSet: (s: Set<string>) => void, id: string) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSet(next);
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

      <div className={styles.grid}>
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>Rango de fechas</h2>
          <div className={styles.dates}>
            <label>
              Desde
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>
              Hasta
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </label>
          </div>
          <p className={styles.hint}>
            Vacío = todo el historial. Sin selección de exámenes/jugadores se
            exportan todos.
          </p>
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>
            Exámenes {selTpl.size > 0 && <span className={styles.badge}>{selTpl.size}</span>}
          </h2>
          {byDept.map((d) => (
            <div key={d.name} className={styles.deptBlock}>
              <div className={styles.deptName}>{d.name}</div>
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
          ))}
          {templates.length === 0 && <p className={styles.muted}>Sin exámenes.</p>}
        </section>

        <section className={styles.card}>
          <h2 className={styles.cardTitle}>
            Jugadores {selPl.size > 0 && <span className={styles.badge}>{selPl.size}</span>}
          </h2>
          <div className={styles.playerList}>
            {players.map((p) => (
              <label key={p.id} className={styles.check}>
                <input
                  type="checkbox"
                  checked={selPl.has(p.id)}
                  onChange={() => toggle(selPl, setSelPl, p.id)}
                />
                {p.first_name} {p.last_name}
              </label>
            ))}
            {players.length === 0 && <p className={styles.muted}>Sin jugadores.</p>}
          </div>
        </section>
      </div>

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
