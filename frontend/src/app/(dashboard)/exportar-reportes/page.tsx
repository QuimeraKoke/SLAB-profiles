"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Download, FileStack } from "lucide-react";

import { api, getToken } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import ProfileTabs, { panelIdFor } from "@/components/perfil/ProfileTabs/ProfileTabs";
import { useToast } from "@/components/ui/Toast/Toast";
import styles from "../exportar/page.module.css";

interface PlayerLite {
  id: string;
  first_name: string;
  last_name: string;
  position: { id: string; name: string; abbreviation: string; role: string } | null;
}
interface Area { slug: string | null; name: string }

/** One tab per kind of report. Each tab is its own exporter; add the next
 *  one here (the URL keeps the selected tab: `?tab=`). */
const TABS = [
  { id: "infografia", label: "Infografía (ficha)" },
  { id: "informe", label: "Informe de plantel" },
];

/**
 * Datos › Exportar reportes — the player reports the staff prints in bulk.
 * Informe de plantel: the long A4 report, by sections. Infografía: pick the area (Físico by default — the ficha the profe uses)
 * and the players, and download ALL their fichas joined in one PDF, a page
 * each, in roster order (by position, then name).
 */
function ExportarReportes() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : TABS[0].id;
  const setTab = (t: string) => {
    const sp = new URLSearchParams(params.toString());
    if (t === TABS[0].id) sp.delete("tab"); else sp.set("tab", t);
    router.replace(`${pathname}${sp.size ? `?${sp}` : ""}`, { scroll: false });
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.h1}><FileStack size={20} aria-hidden="true" /> Exportar reportes</h1>
        <p className={styles.sub}>Elige el tipo de reporte y los jugadores: se descargan todos juntos en un archivo.</p>
      </header>
      <ProfileTabs tabs={TABS} activeTab={tab} onTabChange={setTab} />
      <div role="tabpanel" id={panelIdFor(tab)} aria-labelledby={`tab-${tab}`} style={{ marginTop: 16 }}>
        {tab === "infografia" && <FichasExport />}
        {tab === "informe" && <InformeExport />}
      </div>
    </div>
  );
}

function FichasExport() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const { toast } = useToast();
  const [areas, setAreas] = useState<Area[]>([]);
  const [area, setArea] = useState<string | null>("fisico");
  const [maxPlayers, setMaxPlayers] = useState(60);
  const [players, setPlayers] = useState<PlayerLite[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) setSel(new Set()); });
    api<{ areas: Area[]; max_players: number }>(`/export/fichas/options?category_id=${categoryId}`)
      .then((d) => {
        if (cancelled) return;
        setAreas(d.areas);
        setMaxPlayers(d.max_players);
        // Físico by default; else the first area the user can see.
        setArea((cur) => (d.areas.some((a) => a.slug === cur) ? cur
          : d.areas.some((a) => a.slug === "fisico") ? "fisico" : d.areas[0]?.slug ?? null));
      })
      .catch(() => { if (!cancelled) setAreas([]); });
    api<PlayerLite[]>(`/players?category_id=${categoryId}`)
      .then((p) => { if (!cancelled) setPlayers(p); })
      .catch(() => { if (!cancelled) setPlayers([]); });
    return () => { cancelled = true; };
  }, [categoryId]);

  const byPosition = useMemo(() => {
    const m = new Map<string, PlayerLite[]>();
    const sorted = [...players].sort((a, b) =>
      `${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`));
    for (const p of sorted) {
      const key = p.position?.role || p.position?.name || "Sin posición";
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(p);
    }
    return [...m.entries()].map(([label, items]) => ({ label, items }));
  }, [players]);

  // The PDF follows the list as shown: by position, then surname.
  const ordered = byPosition.flatMap((g) => g.items).filter((p) => sel.has(p.id));
  const allIds = byPosition.flatMap((g) => g.items.map((p) => p.id));

  function toggle(id: string) {
    const next = new Set(sel);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSel(next);
  }
  function toggleGroup(ids: string[]) {
    const all = ids.every((id) => sel.has(id));
    const next = new Set(sel);
    for (const id of ids) { if (all) next.delete(id); else next.add(id); }
    setSel(next);
  }

  async function download() {
    if (!categoryId || busy) return;
    if (ordered.length === 0) { setError("Elige al menos un jugador."); return; }
    if (ordered.length > maxPlayers) { setError(`Máximo ${maxPlayers} fichas por archivo.`); return; }
    setBusy(true);
    setError(null);
    try {
      const sp = new URLSearchParams({ category_id: categoryId, player_ids: ordered.map((p) => p.id).join(",") });
      if (area) sp.set("department", area);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";
      const headers = new Headers({ Accept: "application/pdf" });
      const token = getToken();
      if (token) headers.set("Authorization", `Bearer ${token}`);
      const res = await fetch(`${apiUrl}/export/fichas.pdf?${sp}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `fichas-${area ?? "integral"}-${categoryName || "equipo"}.pdf`.replace(/\s+/g, "_");
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`${ordered.length} ficha${ordered.length === 1 ? "" : "s"} descargada${ordered.length === 1 ? "" : "s"} en un PDF.`);
    } catch {
      setError("No se pudo generar el archivo. Intenta nuevamente.");
    } finally {
      setBusy(false);
    }
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Selecciona una categoría.</div>;
  const areaName = areas.find((a) => a.slug === area)?.name ?? "";

  return (
    <>
      <section className={styles.card} aria-labelledby="fx-area">
        <h2 id="fx-area" className={styles.cardTitle}>Ficha</h2>
        <div className={styles.examGrid} role="radiogroup" aria-labelledby="fx-area">
          {areas.map((a) => (
            <label key={a.slug ?? "general"} className={styles.check}>
              <input type="radio" name="ficha-area" checked={area === a.slug} onChange={() => setArea(a.slug)} />
              {a.name}
            </label>
          ))}
        </div>
        <p className={styles.hint} style={{ marginTop: 8 }}>
          {categoryName} · una página por jugador, la misma infografía que el botón “Ficha (PDF)” de su perfil.
        </p>
      </section>

      <section className={styles.playersCard} aria-labelledby="fx-players">
        <h2 id="fx-players" className={styles.cardTitle}>
          Jugadores {sel.size > 0 && <span className={styles.badge}>{sel.size}</span>}
          <button type="button" onClick={() => toggleGroup(allIds)}
            style={{ marginLeft: "auto", background: "none", border: 0, color: "#4f46e5", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            {allIds.length > 0 && allIds.every((id) => sel.has(id)) ? "Quitar todos" : "Seleccionar todos"}
          </button>
        </h2>
        {byPosition.map((g) => {
          const ids = g.items.map((p) => p.id);
          const n = ids.filter((id) => sel.has(id)).length;
          return (
            <div key={g.label} className={styles.posGroup}>
              <label className={styles.posHead}>
                <input type="checkbox"
                  ref={(el) => { if (el) { el.checked = n === ids.length && n > 0; el.indeterminate = n > 0 && n < ids.length; } }}
                  onChange={() => toggleGroup(ids)} />
                {g.label}
                <span className={styles.posCount}>{n}/{ids.length}</span>
              </label>
              <div className={styles.posGrid}>
                {g.items.map((p) => (
                  <label key={p.id} className={styles.check}>
                    <input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} />
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
        <button type="button" className={styles.downloadBtn} onClick={download} disabled={busy || sel.size === 0}>
          <Download size={16} aria-hidden="true" />
          {busy ? `Generando ${ordered.length} fichas…`
            : sel.size === 0 ? "Elige jugadores"
            : `Descargar ${ordered.length} ficha${ordered.length === 1 ? "" : "s"} (PDF)`}
        </button>
        {areaName && sel.size > 0 && !busy && <span className={styles.hint}>{areaName} · un solo PDF</span>}
        {error && <span className={styles.error} role="alert">{error}</span>}
      </div>
    </>
  );
}

/** The category's players, grouped by position then surname — the order the
 *  PDF follows. */
function useRoster(categoryId: string | null) {
  const [players, setPlayers] = useState<PlayerLite[]>([]);
  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<PlayerLite[]>(`/players?category_id=${categoryId}`)
      .then((p) => { if (!cancelled) setPlayers(p); })
      .catch(() => { if (!cancelled) setPlayers([]); });
    return () => { cancelled = true; };
  }, [categoryId]);
  return useMemo(() => {
    const m = new Map<string, PlayerLite[]>();
    const sorted = [...players].sort((a, b) =>
      `${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`));
    for (const p of sorted) {
      const key = p.position?.role || p.position?.name || "Sin posición";
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(p);
    }
    return [...m.entries()].map(([label, items]) => ({ label, items }));
  }, [players]);
}

function PlayerPicker({ groups, sel, setSel }: {
  groups: { label: string; items: PlayerLite[] }[];
  sel: Set<string>;
  setSel: (s: Set<string>) => void;
}) {
  const allIds = groups.flatMap((g) => g.items.map((p) => p.id));
  const toggle = (id: string) => {
    const next = new Set(sel);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSel(next);
  };
  const toggleGroup = (ids: string[]) => {
    const all = ids.every((id) => sel.has(id));
    const next = new Set(sel);
    for (const id of ids) { if (all) next.delete(id); else next.add(id); }
    setSel(next);
  };
  return (
    <section className={styles.playersCard} aria-labelledby="pp-players">
      <h2 id="pp-players" className={styles.cardTitle}>
        Jugadores {sel.size > 0 && <span className={styles.badge}>{sel.size}</span>}
        <button type="button" onClick={() => toggleGroup(allIds)}
          style={{ marginLeft: "auto", background: "none", border: 0, color: "#4f46e5", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
          {allIds.length > 0 && allIds.every((id) => sel.has(id)) ? "Quitar todos" : "Seleccionar todos"}
        </button>
      </h2>
      {groups.map((g) => {
        const ids = g.items.map((p) => p.id);
        const n = ids.filter((id) => sel.has(id)).length;
        return (
          <div key={g.label} className={styles.posGroup}>
            <label className={styles.posHead}>
              <input type="checkbox"
                ref={(el) => { if (el) { el.checked = n === ids.length && n > 0; el.indeterminate = n > 0 && n < ids.length; } }}
                onChange={() => toggleGroup(ids)} />
              {g.label}
              <span className={styles.posCount}>{n}/{ids.length}</span>
            </label>
            <div className={styles.posGrid}>
              {g.items.map((p) => (
                <label key={p.id} className={styles.check}>
                  <input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} />
                  {p.first_name} {p.last_name}
                </label>
              ))}
            </div>
          </div>
        );
      })}
      {allIds.length === 0 && <p className={styles.muted}>Sin jugadores.</p>}
    </section>
  );
}

/** Downloads an authenticated PDF (the API is on another origin). A `body`
 *  makes it a POST (the informe's comments can be long). Throws the API's
 *  message when it has one. */
async function downloadPdf(path: string, filename: string, body?: unknown) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";
  const headers = new Headers({ Accept: "application/pdf" });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (body !== undefined) headers.set("Content-Type", "application/json");
  const res = await fetch(`${apiUrl}${path}`, body !== undefined
    ? { method: "POST", headers, body: JSON.stringify(body) } : { headers });
  if (!res.ok) {
    const detail = await res.json().then((j) => j?.detail).catch(() => null);
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.replace(/\s+/g, "_");
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** How an area with a period can be grouped, and which statistics it offers
 *  (Kine and Lesiones are counted, not averaged). */
const GRAN_OPTIONS: Record<string, [string, string][]> = {
  cargas: [["detalle", "Partido"], ["semana", "Semana"], ["mes", "Mes"], ["semestre", "Semestre"]],
  condicion: [["detalle", "Evaluación"], ["semana", "Semana"], ["mes", "Mes"], ["semestre", "Semestre"]],
  composicion: [["detalle", "Medición"], ["semana", "Semana"], ["mes", "Mes"], ["semestre", "Semestre"]],
  kine: [["detalle", "Detalle"], ["semana", "Semana"], ["mes", "Mes"], ["semestre", "Semestre"]],
  lesiones: [["detalle", "Detalle"], ["semana", "Semana"], ["mes", "Mes"], ["semestre", "Semestre"]],
};
const STAT_OPTIONS: Record<string, [string, string][]> = {
  cargas: [["mean", "Promedio"], ["max", "Máximo"], ["min", "Mínimo"], ["sum", "Total"]],
  condicion: [["mean", "Promedio"], ["max", "Máximo"], ["min", "Mínimo"]],
  composicion: [["mean", "Promedio"], ["max", "Máximo"], ["min", "Mínimo"]],
};
type AreaView = { gran: string; stats: string[] };

/** What an area shows when it has no dates. */
const DEFAULT_SPAN: Record<string, string> = {
  cargas: "últimas N competiciones",
  condicion: "última evaluación de cada test",
  composicion: "últimas dos mediciones",
  kine: "último mes",
  lesiones: "todo el historial",
};

const SECTION_HINT: Record<string, string> = {
  cargas: "GPS de las últimas competiciones: tabla y gráficos de distancia, velocidad, ACC y DEC",
  condicion: "Última evaluación de cada test, su nivel (bandas de la categoría) y el cambio",
  composicion: "Antropometría: medición actual contra la anterior",
  kine: "Atenciones del último mes (notas de kinesiología)",
  lesiones: "Historial de lesiones, la más grave y las zonas que se repiten",
};

/**
 * Informe de plantel — the long A4 report (the club's "Informe club"): per
 * player, the sections picked here, each player starting a new page.
 */
function InformeExport() {
  const { categoryId, categories, loading: catLoading } = useCategoryContext();
  const { toast } = useToast();
  const groups = useRoster(categoryId);
  const [sections, setSections] = useState<{ key: string; label: string }[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [partidos, setPartidos] = useState(4);
  // {section: {from, to}} — each area of the report has its own period.
  const [ranges, setRanges] = useState<Record<string, { from: string; to: string }>>({});
  const setRange = (k: string, part: "from" | "to", v: string) =>
    setRanges((r) => ({ ...r, [k]: { from: r[k]?.from ?? "", to: r[k]?.to ?? "", [part]: v } }));
  const badRange = (k: string) => !!(ranges[k]?.from && ranges[k]?.to && ranges[k].from > ranges[k].to);
  const cargasRange = !!(ranges.cargas?.from || ranges.cargas?.to);
  // {section: {gran, stats}} — how an area with a period is grouped.
  const [views, setViews] = useState<Record<string, AreaView>>({});
  const viewOf = (k: string): AreaView => views[k] ?? { gran: "detalle", stats: ["mean"] };
  const setView = (k: string, v: Partial<AreaView>) => setViews((all) => ({ ...all, [k]: { ...viewOf(k), ...v } }));
  const toggleStat = (k: string, st: string) => {
    const cur = viewOf(k).stats;
    const next = cur.includes(st) ? cur.filter((x) => x !== st) : [...cur, st];
    // Keep the menu's order (the first one is what the charts plot), never empty.
    const order = (STAT_OPTIONS[k] ?? []).map(([id]) => id);
    setView(k, { stats: next.length ? order.filter((id) => next.includes(id)) : cur });
  };
  // {player_id: text} — the doctor's comment, per player.
  const [comments, setComments] = useState<Record<string, string>>({});
  const [maxPlayers, setMaxPlayers] = useState(60);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const categoryName = categories.find((c) => c.id === categoryId)?.name ?? "";

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) setSel(new Set()); });
    api<{ sections: { key: string; label: string }[]; max_players: number }>(
      `/export/informe-plantel/options?category_id=${categoryId}`)
      .then((d) => {
        if (cancelled) return;
        setSections(d.sections);
        setMaxPlayers(d.max_players);
        setChosen((cur) => (cur.size ? cur : new Set(d.sections.map((x) => x.key))));
      })
      .catch(() => { if (!cancelled) setSections([]); });
    return () => { cancelled = true; };
  }, [categoryId]);

  const ordered = groups.flatMap((g) => g.items).filter((p) => sel.has(p.id));
  const toggleSection = (k: string) => {
    const next = new Set(chosen);
    if (next.has(k)) next.delete(k); else next.add(k);
    setChosen(next);
  };

  async function download() {
    if (!categoryId || busy) return;
    if (ordered.length === 0) { setError("Elige al menos un jugador."); return; }
    if (chosen.size === 0) { setError("Elige al menos una sección."); return; }
    if (ordered.length > maxPlayers) { setError(`Máximo ${maxPlayers} jugadores por archivo.`); return; }
    const bad = sections.find((x) => chosen.has(x.key) && badRange(x.key));
    if (bad) { setError(`${bad.label}: la fecha Desde es posterior a Hasta.`); return; }
    setBusy(true);
    setError(null);
    try {
      await downloadPdf("/export/informe-plantel.pdf", `informe-plantel-${categoryName || "equipo"}.pdf`, {
        category_id: categoryId,
        player_ids: ordered.map((p) => p.id),
        sections: sections.map((x) => x.key).filter((k) => chosen.has(k)),
        partidos,
        ranges: Object.fromEntries(sections.filter((x) => chosen.has(x.key) && (ranges[x.key]?.from || ranges[x.key]?.to))
          .map((x) => [x.key, {
            date_from: ranges[x.key].from || null, date_to: ranges[x.key].to || null,
            granularity: viewOf(x.key).gran, stats: viewOf(x.key).stats,
          }])),
        comments: Object.fromEntries(ordered.map((p) => [p.id, comments[p.id] ?? ""]).filter(([, t]) => t.trim())),
      });
      toast.success(`Informe de ${ordered.length} jugador${ordered.length === 1 ? "" : "es"} descargado.`);
    } catch (e) {
      const msg = e instanceof Error && !e.message.startsWith("HTTP") ? e.message : "";
      setError(msg || "No se pudo generar el informe. Intenta nuevamente.");
    } finally {
      setBusy(false);
    }
  }

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Selecciona una categoría.</div>;

  return (
    <>
      <section className={styles.card} aria-labelledby="ip-sections">
        <h2 id="ip-sections" className={styles.cardTitle}>
          Áreas del informe {chosen.size > 0 && <span className={styles.badge}>{chosen.size}</span>}
        </h2>
        <div className={styles.sectionTable} role="table" aria-label="Áreas del informe y su período">
          <div role="row" className={`${styles.sectionRow} ${styles.sectionHead}`}>
            <span role="columnheader">Área</span>
            <span role="columnheader">Desde</span>
            <span role="columnheader">Hasta</span>
            <span role="columnheader">Sin fechas</span>
          </div>
          {sections.map((x) => {
            const on = chosen.has(x.key);
            const r = ranges[x.key] ?? { from: "", to: "" };
            const bad = badRange(x.key);
            return (
              <div key={x.key} role="row" className={styles.sectionRow} style={{ opacity: on ? 1 : 0.55 }}>
                <label role="cell" className={styles.check}>
                  <input type="checkbox" checked={on} onChange={() => toggleSection(x.key)} />
                  <span>
                    <strong style={{ color: "#0a2240", fontWeight: 600 }}>{x.label}</strong>
                    <span className={styles.hint} style={{ display: "block" }}>{SECTION_HINT[x.key] ?? ""}</span>
                  </span>
                </label>
                <input type="date" value={r.from} disabled={!on} max={r.to || undefined}
                  aria-label={`${x.label}: desde`} aria-invalid={bad}
                  onChange={(e) => setRange(x.key, "from", e.target.value)} className={styles.dateInput} />
                <input type="date" value={r.to} disabled={!on} min={r.from || undefined}
                  aria-label={`${x.label}: hasta`} aria-invalid={bad}
                  onChange={(e) => setRange(x.key, "to", e.target.value)} className={styles.dateInput} />
                <span role="cell" className={styles.hint}>
                  {r.from || r.to
                    ? <button type="button" onClick={() => setRanges((all) => { const n = { ...all }; delete n[x.key]; return n; })}
                        style={{ background: "none", border: 0, color: "#4f46e5", fontWeight: 600, fontSize: 12, cursor: "pointer", padding: 0 }}>
                        Quitar fechas</button>
                    : DEFAULT_SPAN[x.key]}
                </span>
                {on && (r.from || r.to) && GRAN_OPTIONS[x.key] && (
                  <div className={styles.viewRow}>
                    <span className={styles.viewLabel}>Ver por</span>
                    <div role="group" aria-label={`${x.label}: ver por`} className={styles.segmented}>
                      {GRAN_OPTIONS[x.key].map(([id, lab]) => (
                        <button key={id} type="button" aria-pressed={viewOf(x.key).gran === id}
                          onClick={() => setView(x.key, { gran: id })}>{lab}</button>
                      ))}
                    </div>
                    {viewOf(x.key).gran !== "detalle" && STAT_OPTIONS[x.key] && (
                      <>
                        <span className={styles.viewLabel}>Mostrar</span>
                        <div role="group" aria-label={`${x.label}: estadísticos`} className={styles.statChips}>
                          {STAT_OPTIONS[x.key].map(([id, lab]) => (
                            <label key={id} className={styles.statChip}>
                              <input type="checkbox" checked={viewOf(x.key).stats.includes(id)}
                                onChange={() => toggleStat(x.key, id)} />
                              {lab}
                            </label>
                          ))}
                        </div>
                      </>
                    )}
                    {viewOf(x.key).gran !== "detalle" && !STAT_OPTIONS[x.key] && (
                      <span className={styles.hint}>
                        {x.key === "kine" ? "Atenciones por período, por tipo y tratante." : "Lesiones y días perdidos por período, más el listado."}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {chosen.has("cargas") && cargasRange && viewOf("cargas").gran === "detalle" && (
          <p className={styles.hint} style={{ marginTop: 6 }}>Cargas: todas las competiciones con GPS de su período (máximo 10).</p>
        )}
        {chosen.has("cargas") && !cargasRange && (
          <label className={styles.check} style={{ marginTop: 8 }}>
            Competiciones con GPS a incluir
            <select value={partidos} onChange={(e) => setPartidos(Number(e.target.value))}
              style={{ border: "1px solid #e8eaf0", borderRadius: 8, padding: "4px 8px", fontSize: 13, color: "#101828" }}>
              {[3, 4, 5, 6, 8].map((n) => <option key={n} value={n}>Últimas {n}</option>)}
            </select>
          </label>
        )}
        <p className={styles.hint} style={{ marginTop: 8 }}>
          {categoryName} · A4 vertical, cada jugador empieza en una página nueva (unas 2 páginas por jugador con todas las áreas).
        </p>
      </section>

      <PlayerPicker groups={groups} sel={sel} setSel={setSel} />

      {ordered.length > 0 && (
        <section className={styles.card} aria-labelledby="ip-comments" style={{ marginTop: 16 }}>
          <h2 id="ip-comments" className={styles.cardTitle}>
            Comentario médico <span className={styles.hint}>· opcional, sale al final del informe de cada jugador</span>
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {ordered.map((p) => (
              <label key={p.id} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, color: "#344054" }}>
                <span style={{ fontWeight: 600, color: "#0a2240" }}>{p.first_name} {p.last_name}</span>
                <textarea value={comments[p.id] ?? ""} rows={2} maxLength={4000}
                  placeholder="Sin comentario: la sección no aparece en su informe."
                  onChange={(e) => setComments((c) => ({ ...c, [p.id]: e.target.value }))}
                  style={{ border: "1px solid #e8eaf0", borderRadius: 8, padding: "8px 10px", fontSize: 13,
                    fontFamily: "inherit", color: "#101828", resize: "vertical" }} />
              </label>
            ))}
          </div>
        </section>
      )}

      <div className={styles.footer}>
        <button type="button" className={styles.downloadBtn} onClick={download}
          disabled={busy || sel.size === 0 || chosen.size === 0}>
          <Download size={16} aria-hidden="true" />
          {busy ? `Generando informe de ${ordered.length}…`
            : sel.size === 0 ? "Elige jugadores"
            : `Descargar informe de ${ordered.length} jugador${ordered.length === 1 ? "" : "es"} (PDF)`}
        </button>
        {error && <span className={styles.error} role="alert">{error}</span>}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<div className={styles.muted}>Cargando…</div>}>
      <ExportarReportes />
    </Suspense>
  );
}
