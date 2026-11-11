"use client";

import React, { useEffect, useState } from "react";
import { ExternalLink, FileSpreadsheet, Plug, Share2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import styles from "./page.module.css";

interface SourceExam { slug: string; name: string; count: number; last: string | null; loaded: string | null; exact: boolean }
interface Source {
  key: string; name: string; kind: "sheet" | "api"; what: string; schedule: string; tab: string;
  status: "ok" | "atrasada" | "manual" | "sin_configurar" | "sin_datos";
  last_loaded: string | null;
  docs: { id: string | null; title: string | null; url: string | null }[];
  exams: SourceExam[];
}
interface Payload { club: string; sources: Source[]; service_account: string | null }

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
 */
export default function FuentesPage() {
  const { categoryId, loading: catLoading } = useCategoryContext();
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<Payload>(`/data-sources?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudieron cargar las fuentes."); });
    return () => { cancelled = true; };
  }, [categoryId]);

  if (catLoading) return <div className={styles.muted}>Cargando…</div>;
  if (!categoryId) return <div className={styles.muted}>Seleccioná una categoría.</div>;

  const sheets = data?.sources.filter((s) => s.kind === "sheet") ?? [];
  const apis = data?.sources.filter((s) => s.kind === "api") ?? [];

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

      {data && (
        <>
          {data.service_account && (
            <p className={styles.note}>
              Para sumar una planilla nueva, compartila (como lector) con la cuenta{" "}
              <code className={styles.code}>{data.service_account}</code> y avisá al equipo de SLAB.
            </p>
          )}

          <h2 className={styles.groupTitle}><FileSpreadsheet size={16} aria-hidden="true" /> Planillas de Google Drive</h2>
          <div className={styles.grid}>
            {sheets.map((s) => <SourceCard key={s.key} s={s} now={now} />)}
          </div>

          <h2 className={styles.groupTitle}><Plug size={16} aria-hidden="true" /> Integraciones (API)</h2>
          <div className={styles.grid}>
            {apis.map((s) => <SourceCard key={s.key} s={s} now={now} />)}
          </div>

          <p className={styles.footnote}>
            Lo que no viene de estas fuentes se carga a mano en SLAB (Registrar examen, Subir datos, notas del Daily).
            “Atrasada”: no llegan datos nuevos hace más de lo normal para esa fuente (20 h en wellness, 2 días en peso,
            3 en kine, 4 en GPS); conviene revisar la planilla o la conexión. En VALD, COMET y Wellness Primer
            Equipo los números son el total del examen en el club: son su única fuente automática.
          </p>
        </>
      )}
    </div>
  );
}

function SourceCard({ s, now }: { s: Source; now: number }) {
  const st = STATUS[s.status];
  return (
    <section className={styles.card} aria-labelledby={`src-${s.key}`}>
      <div className={styles.cardHead}>
        <h3 id={`src-${s.key}`} className={styles.cardTitle}>{s.name}</h3>
        <span className={`${styles.pill} ${styles[st.cls]}`}>{st.label}</span>
      </div>
      <p className={styles.what}>{s.what}</p>
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
