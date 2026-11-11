"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ExternalLink, FileSpreadsheet, Plug, Share2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import ProfileTabs, { panelIdFor } from "@/components/perfil/ProfileTabs/ProfileTabs";
import SolutionsModal from "./SolutionsModal";
import { openInSheet } from "./openInSheet";
import Examples from "./Examples";
import { useToast } from "@/components/ui/Toast/Toast";
import styles from "./page.module.css";

interface SourceExam { slug: string; name: string; count: number; last: string | null; loaded: string | null; exact: boolean }
interface Source {
  key: string; name: string; kind: "sheet" | "api"; what: string; schedule: string; tab: string;
  status: "ok" | "atrasada" | "manual" | "sin_configurar" | "sin_datos";
  last_loaded: string | null;
  docs: { id: string | null; title: string | null; url: string | null }[];
  exams: SourceExam[];
  issues: number;
}
interface Issue {
  id: string; source: string; kind: string; kind_label: string; subject: string; document: string;
  detail: string; rows: number; examples: string[]; locations: string[]; has_sheet: boolean;
  latest_data_date: string | null;
  first_seen_at: string | null; last_seen_at: string | null;
}
interface Payload { club: string; sources: Source[]; issues: Issue[]; service_account: string | null }

const STATUS: Record<Source["status"], { label: string; cls: string }> = {
  ok: { label: "Al día", cls: "ok" },
  atrasada: { label: "Atrasada", cls: "warn" },
  manual: { label: "Carga a mano", cls: "neutral" },
  sin_configurar: { label: "Sin configurar", cls: "neutral" },
  sin_datos: { label: "Sin datos", cls: "warn" },
};

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const dateLabel = (iso: string | null) => {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
};
function ago(iso: string | null, now: number): string {
  if (!iso) return "sin cargas";
  const min = Math.round((now - new Date(iso).getTime()) / 60000);
  if (min < 1) return "hace instantes";
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} días`;
}
const fmtInt = (n: number) => n.toLocaleString("es-CL");

/**
 * Datos › Fuentes — which Drive document (or API) feeds which exam, how often
 * it syncs, how many results it wrote and the newest one. Read-only: the
 * documents themselves are edited in Drive.
 *
 * Tab "Problemas": what the syncs could NOT load and the club can fix (a name
 * not in the roster, an unshared sheet, a new form question…). One row per
 * problem; it disappears by itself when the next sync no longer finds it.
 * URL: `?tab=problemas&fuente=<key>`.
 */
export default function FuentesPage() {
  return <Suspense fallback={null}><Fuentes /></Suspense>;
}

function Fuentes() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = params.get("tab") === "problemas" ? "problemas" : "fuentes";
  const fuente = params.get("fuente") ?? "";
  const setUrl = (next: { tab?: string; fuente?: string }) => {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(next)) {
      if (!v || (k === "tab" && v === "fuentes")) sp.delete(k); else sp.set(k, v);
    }
    router.replace(`${pathname}${sp.size ? `?${sp}` : ""}`, { scroll: false });
  };
  const { categoryId, loading: catLoading } = useCategoryContext();
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<Payload>(`/data-sources?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudieron cargar las fuentes."); });
    return () => { cancelled = true; };
  }, [categoryId, reload]);

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Selecciona una categoría.</div>;

  const sheets = data?.sources.filter((s) => s.kind === "sheet") ?? [];
  const apis = data?.sources.filter((s) => s.kind === "api") ?? [];
  const nIssues = data?.issues.length ?? 0;
  const tabs = [
    { id: "fuentes", label: "Fuentes" },
    { id: "problemas", label: nIssues ? `Problemas (${nIssues})` : "Problemas" },
  ];
  const openIssues = (key: string) => setUrl({ tab: "problemas", fuente: key });

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.h1}><Share2 size={20} aria-hidden="true" /> Fuentes de datos</h1>
        <p className={styles.sub}>
          Qué documento de Drive o sistema alimenta cada examen{data ? ` · ${data.club}` : ""}. Los números son los
          registros que cada fuente cargó y la fecha del dato más reciente.
        </p>
      </header>

      {error && <div className={styles.error} role="alert">{error}</div>}
      {!data && !error && <p className={styles.muted}>Cargando…</p>}

      {data && <ProfileTabs tabs={tabs} activeTab={tab} onTabChange={(t) => setUrl({ tab: t, fuente: "" })} />}

      {data && tab === "problemas" && (
        <div role="tabpanel" id={panelIdFor("problemas")} aria-labelledby="tab-problemas" className={styles.panel}>
          <IssuesView data={data} fuente={fuente} onFuente={(f) => setUrl({ fuente: f })} now={now}
            categoryId={categoryId} onChanged={() => setReload((n) => n + 1)} reload={reload} />
        </div>
      )}

      {data && tab === "fuentes" && (
        <div role="tabpanel" id={panelIdFor("fuentes")} aria-labelledby="tab-fuentes" className={styles.panel}>
          {data.service_account && (
            <p className={styles.note}>
              Para sumar una planilla nueva, compártela (como lector) con la cuenta{" "}
              <code className={styles.code}>{data.service_account}</code> y avisa al equipo de SLAB.
            </p>
          )}

          <h2 className={styles.groupTitle}><FileSpreadsheet size={16} aria-hidden="true" /> Planillas de Google Drive</h2>
          <div className={styles.grid}>
            {sheets.map((s) => <SourceCard key={s.key} s={s} now={now} onIssues={openIssues} />)}
          </div>

          <h2 className={styles.groupTitle}><Plug size={16} aria-hidden="true" /> Integraciones (API)</h2>
          <div className={styles.grid}>
            {apis.map((s) => <SourceCard key={s.key} s={s} now={now} onIssues={openIssues} />)}
          </div>

          <p className={styles.footnote}>
            Lo que no viene de estas fuentes se carga a mano en SLAB (Registrar examen, Subir datos, notas del Daily).
            “Atrasada”: no llegan datos nuevos hace más de lo normal para esa fuente (20 h en wellness, 2 días en peso,
            3 en kine, 4 en GPS); conviene revisar la planilla o la conexión. En VALD, COMET y Wellness Primer
            Equipo los números son el total del examen en el club: son su única fuente automática.
          </p>
        </div>
      )}
    </div>
  );
}

function SourceCard({ s, now, onIssues }: { s: Source; now: number; onIssues: (key: string) => void }) {
  const st = STATUS[s.status];
  return (
    <section className={styles.card} aria-labelledby={`src-${s.key}`}>
      <div className={styles.cardHead}>
        <h3 id={`src-${s.key}`} className={styles.cardTitle}>{s.name}</h3>
        <span className={`${styles.pill} ${styles[st.cls]}`}>{st.label}</span>
      </div>
      <p className={styles.what}>{s.what}</p>
      {s.issues > 0 && (
        <button type="button" className={styles.issueLink} onClick={() => onIssues(s.key)}>
          <AlertTriangle size={14} aria-hidden="true" />
          {s.issues === 1 ? "1 problema de importación" : `${s.issues} problemas de importación`} →
        </button>
      )}
      <dl className={styles.meta}>
        <div><dt>Sincroniza</dt><dd>{s.schedule}</dd></div>
        <div><dt>Última carga</dt><dd>{ago(s.last_loaded, now)}</dd></div>
        {s.tab && <div><dt>Hojas</dt><dd>{s.tab}</dd></div>}
      </dl>

      {s.docs.length > 0 && (
        <div className={styles.docs}>
          <span className={styles.label}>{s.docs.length === 1 ? "Documento" : `Documentos (${s.docs.length})`}</span>
          <ul>
            {s.docs.map((d, i) => (
              <li key={d.id ?? d.title ?? i}>
                {d.url ? (
                  <a href={d.url} target="_blank" rel="noopener noreferrer" className={styles.docLink}
                    title="Abrir en Google Drive (otra pestaña)">
                    {d.title || `Planilla ${d.id?.slice(0, 8)}…`} <ExternalLink size={12} aria-hidden="true" />
                  </a>
                ) : (
                  <span>{d.title}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {s.exams.length > 0 ? (
        <table className={styles.table}>
          <thead>
            <tr><th scope="col">Alimenta</th><th scope="col" className={styles.num}>Registros</th><th scope="col">Último dato</th></tr>
          </thead>
          <tbody>
            {s.exams.map((e) => (
              <tr key={e.slug}>
                <th scope="row">{e.name}</th>
                <td className={styles.num}>{fmtInt(e.count)}</td>
                <td>{dateLabel(e.last)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={styles.muted}>Alimenta el calendario de partidos (no exámenes).</p>
      )}
    </section>
  );
}

const KIND_TONE: Record<string, string> = {
  planilla_inaccesible: "bad", proteccion: "bad", columna_faltante: "bad",
  columna_nueva: "warn", pestana_sin_partido: "warn", fila_rechazada: "warn", fuera_de_rango: "warn",
  jugador_no_encontrado: "neutral", nombre_ambiguo: "neutral",
};
// Structural problems first (a whole sheet or column lost), then by how recent
// the affected data is, then by how many rows it costs.
const KIND_ORDER = ["planilla_inaccesible", "proteccion", "columna_faltante", "columna_nueva",
  "pestana_sin_partido", "nombre_ambiguo", "jugador_no_encontrado", "fila_rechazada", "fuera_de_rango"];
const SHOW = 8;

function IssuesView({ data, fuente, onFuente, now, categoryId, onChanged, reload }: {
  data: Payload; fuente: string; onFuente: (f: string) => void; now: number;
  categoryId: string; onChanged: () => void; reload: number;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const names = useMemo(() => Object.fromEntries(data.sources.map((s) => [s.key, s.name])), [data]);
  const groups = useMemo(() => {
    const bySource = new Map<string, Issue[]>();
    for (const i of data.issues) {
      if (fuente && i.source !== fuente) continue;
      bySource.set(i.source, [...(bySource.get(i.source) ?? []), i]);
    }
    return data.sources
      .filter((s) => bySource.has(s.key))
      .map((s) => ({
        source: s,
        items: bySource.get(s.key)!.sort((a, b) =>
          KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)
          || (b.latest_data_date ?? "").localeCompare(a.latest_data_date ?? "")
          || b.rows - a.rows || a.subject.localeCompare(b.subject)),
      }));
  }, [data, fuente]);
  const withIssues = data.sources.filter((s) => s.issues > 0);

  return (
    <>
      <p className={styles.sub} style={{ marginBottom: 12 }}>
        Lo que las sincronizaciones automáticas no pudieron cargar y se corrige en la planilla o en el plantel.
        Cada problema desaparece solo cuando la siguiente sincronización ya no lo encuentra.
      </p>
      {withIssues.length > 0 && (
        <div className={styles.filters}>
          <label htmlFor="issue-source" className={styles.label} style={{ margin: 0 }}>Fuente</label>
          <select id="issue-source" className={styles.select} value={fuente} onChange={(e) => onFuente(e.target.value)}>
            <option value="">Todas ({data.issues.length})</option>
            {withIssues.map((s) => <option key={s.key} value={s.key}>{s.name} ({s.issues})</option>)}
          </select>
        </div>
      )}
      {groups.length === 0 && (
        <p className={styles.empty}>Sin problemas de importación{fuente ? " en esta fuente" : ""}. Todo lo que llega se está cargando.</p>
      )}
      {groups.map((g) => <IssueGroup key={g.source.key} source={g.source} items={g.items} now={now} onSolve={setOpen}
        categoryId={categoryId} />)}
      <DismissedList categoryId={categoryId} names={names} reload={reload} onChanged={onChanged} />
      {open && (
        <SolutionsModal issueId={open} categoryId={categoryId} sourceNames={names} onClose={() => setOpen(null)}
          onApplied={() => { setOpen(null); onChanged(); }} />
      )}
    </>
  );
}

function IssueGroup({ source, items, now, onSolve, categoryId }: {
  source: Source; items: Issue[]; now: number; onSolve: (id: string) => void; categoryId: string;
}) {
  const { toast } = useToast();
  const open = async (id: string, i: number) => {
    const err = await openInSheet(categoryId, id, i);
    if (err) toast.error(err);
  };
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, SHOW);
  const lost = items.reduce((n, i) => n + i.rows, 0);
  return (
    <section className={styles.issueGroup} aria-labelledby={`ig-${source.key}`}>
      <h2 id={`ig-${source.key}`} className={styles.groupTitle} style={{ marginTop: 0 }}>
        {source.name}
        <span className={styles.groupMeta}>
          {items.length} {items.length === 1 ? "problema" : "problemas"}
          {lost > 0 && ` · ${fmtInt(lost)} filas sin cargar`}
        </span>
      </h2>
      <ul className={styles.issueList}>
        {shown.map((i) => (
          <li key={i.id} className={styles.issue}>
            <div className={styles.issueHead}>
              <span className={`${styles.pill} ${styles[KIND_TONE[i.kind] ?? "neutral"]}`}>{i.kind_label}</span>
              <strong className={styles.issueSubject}>{i.subject}</strong>
              {i.rows > 0 && <span className={styles.issueRows}>{fmtInt(i.rows)} {i.rows === 1 ? "fila" : "filas"} sin cargar</span>}
              {i.has_sheet && (
                <button type="button" className={`${styles.solveBtn} ${styles.sheetBtn}`} onClick={() => open(i.id, 0)}
                  title="Abrir la planilla en Drive, en la pestaña y fila del problema (otra pestaña)"
                  aria-label={`Ver ${i.subject} en la planilla (se abre en otra pestaña)`}>
                  Ver en la planilla <ExternalLink size={12} aria-hidden="true" />
                </button>
              )}
              {i.id !== "vald-unlinked" && (
                <button type="button" className={styles.solveBtn} onClick={() => onSolve(i.id)}
                  aria-label={`Ver soluciones para ${i.subject}`}>
                  Ver soluciones
                </button>
              )}
            </div>
            <p className={styles.issueDetail}>{i.detail}</p>
            <div className={styles.issueMeta}>
              {i.document && <span>{i.document}</span>}
              {i.examples.length > 0 && (
                <span>Ej.:{" "}
                  <Examples examples={i.examples} locations={i.locations} onOpen={(n) => open(i.id, n)} />
                </span>
              )}
              {i.latest_data_date && <span>Dato más reciente: {dateLabel(i.latest_data_date)}</span>}
              {i.first_seen_at && <span>Detectado {ago(i.first_seen_at, now)}</span>}
            </div>
          </li>
        ))}
      </ul>
      {items.length > SHOW && (
        <button type="button" className={styles.more} onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? "Ver menos" : `Ver todos (${items.length})`}
        </button>
      )}
    </section>
  );
}

interface Dismissed { id: string; source: string; kind_label: string; subject: string; document: string; note: string; by: string; at: string }

/** What the staff chose to hide ("No es del plantel", "Ignorar"), with undo. */
function DismissedList({ categoryId, names, reload, onChanged }: {
  categoryId: string; names: Record<string, string>; reload: number; onChanged: () => void;
}) {
  const { toast } = useToast();
  const [items, setItems] = useState<Dismissed[]>([]);
  const [show, setShow] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api<{ items: Dismissed[] }>(`/data-sources/issues/dismissed?category_id=${categoryId}`)
      .then((r) => { if (!cancelled) setItems(r.items); })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, [categoryId, reload]);
  if (!items.length) return null;
  const restore = async (d: Dismissed) => {
    try {
      await api(`/data-sources/issues/${d.id}/restore?category_id=${categoryId}`, { method: "POST" });
      toast.success(`«${d.subject}» vuelve a la lista de problemas.`);
      onChanged();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo restaurar.");
    }
  };
  return (
    <section className={styles.issueGroup}>
      <button type="button" className={styles.more} onClick={() => setShow((v) => !v)} aria-expanded={show}>
        {show ? "Ocultar ignorados" : `Ignorados (${items.length})`}
      </button>
      {show && (
        <ul className={styles.issueList}>
          {items.map((d) => (
            <li key={d.id} className={styles.issue}>
              <div className={styles.issueHead}>
                <span className={`${styles.pill} ${styles.neutral}`}>{d.note || d.kind_label}</span>
                <strong className={styles.issueSubject}>{d.subject}</strong>
                <button type="button" className={styles.solveBtn} onClick={() => restore(d)}>Restaurar</button>
              </div>
              <div className={styles.issueMeta}>
                <span>{names[d.source] ?? d.source}{d.document ? ` · ${d.document}` : ""}</span>
                <span>{d.by ? `${d.by}, ` : ""}{dateLabel(d.at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

