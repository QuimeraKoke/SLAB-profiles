"use client";

import React, { useEffect, useId, useState } from "react";
import { ExternalLink, Search, Sparkles } from "lucide-react";

import Modal from "@/components/ui/Modal/Modal";
import { useToast } from "@/components/ui/Toast/Toast";
import { api, ApiError } from "@/lib/api";
import { openInSheet } from "./openInSheet";
import Examples from "./Examples";
import styles from "./page.module.css";

interface Candidate {
  id: string; name: string; category: string; birth_year: number | null; active: boolean;
  reasons?: string[]; recommended?: boolean;
}
interface MatchOpt { date: string; opponent: string; kind: string; recommended: boolean }
interface Option {
  action: "link" | "dismiss" | "assign_match" | "not_a_match" | "info";
  title: string; explanation: string; impact: string; recommended: boolean;
  candidates?: Candidate[]; search?: boolean; matches?: MatchOpt[]; url?: string | null;
}
interface Solutions {
  issue: {
    id: string; subject: string; kind_label: string; document: string; detail: string; rows: number;
    examples: string[]; locations: string[]; has_sheet: boolean;
  };
  same_name: { source: string; document: string; rows: number }[];
  options: Option[];
}

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const day = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

/**
 * "Ver soluciones" for one import problem: each way to fix it, explained, with
 * what it would do. Applying is always a second, explicit step (Aplicar →
 * Confirmar); closing the panel changes nothing.
 */
export default function SolutionsModal({ issueId, categoryId, sourceNames, onClose, onApplied }: {
  issueId: string; categoryId: string; sourceNames: Record<string, string>;
  onClose: () => void; onApplied: () => void;
}) {
  const { toast } = useToast();
  const [data, setData] = useState<Solutions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Which option is waiting for confirmation, and with what.
  const [pending, setPending] = useState<{ opt: Option; label: string; body: Record<string, string> } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Solutions>(`/data-sources/issues/${issueId}/solutions?category_id=${categoryId}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudieron cargar las soluciones."); });
    return () => { cancelled = true; };
  }, [issueId, categoryId]);

  const openSheet = async (n: number) => {
    const err = await openInSheet(categoryId, issueId, n);
    if (err) toast.error(err);
  };

  const apply = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ message: string }>(`/data-sources/issues/${issueId}/apply?category_id=${categoryId}`, {
        method: "POST", body: JSON.stringify({ action: pending.opt.action, ...pending.body }),
      });
      toast.success(r.message);
      onApplied();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo aplicar la solución.");
      setBusy(false);
    }
  };

  return (
    <Modal open title="Soluciones" onClose={onClose}>
      <div className={styles.sol}>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {!data && !error && <p className={styles.muted}>Buscando soluciones…</p>}
        {data && (
          <>
            <div className={styles.solIssue}>
              <span className={styles.label}>{data.issue.kind_label}</span>
              <strong className={styles.solSubject}>{data.issue.subject}</strong>
              <p className={styles.issueDetail}>{data.issue.detail}</p>
              <div className={styles.issueMeta}>
                {data.issue.document && <span>{data.issue.document}</span>}
                {data.issue.rows > 0 && <span>{data.issue.rows} {data.issue.rows === 1 ? "fila" : "filas"} sin cargar</span>}
                {data.issue.examples.length > 0 && (
                  <span>Ej.:{" "}
                    <Examples examples={data.issue.examples} locations={data.issue.locations} onOpen={(n) => openSheet(n)} />
                  </span>
                )}
              </div>
              {data.issue.has_sheet && (
                <button type="button" className={`${styles.solveBtn} ${styles.sheetBtn}`} style={{ marginTop: 8, marginLeft: 0 }}
                  onClick={() => openSheet(0)} aria-label="Ver en la planilla (se abre en otra pestaña)">
                  Ver en la planilla <ExternalLink size={12} aria-hidden="true" />
                </button>
              )}
              {data.same_name.length > 0 && (
                <p className={styles.solNote}>
                  Este nombre también falta en:{" "}
                  {data.same_name.map((s) => `${sourceNames[s.source] ?? s.source}${s.document ? ` (${s.document})` : ""}`
                    + (s.rows ? ` · ${s.rows} filas` : "")).join("; ")}. Vincularlo lo resuelve en todas.
                </p>
              )}
            </div>

            {pending ? (
              <div className={styles.confirm} role="group" aria-label="Confirmar solución">
                <p><strong>¿Aplicar esta solución?</strong></p>
                <p>{pending.label}</p>
                {pending.opt.impact && <p className={styles.muted}>{pending.opt.impact}</p>}
                <div className={styles.confirmRow}>
                  <button type="button" className={styles.btnGhost} onClick={() => setPending(null)} disabled={busy}>Volver</button>
                  <button type="button" className={styles.btnPrimary} onClick={apply} disabled={busy} autoFocus>
                    {busy ? "Aplicando…" : "Confirmar"}
                  </button>
                </div>
              </div>
            ) : (
              <ol className={styles.solList}>
                {data.options.map((o, i) => (
                  <li key={o.action + i} className={`${styles.solOpt} ${o.recommended ? styles.solRec : ""}`}>
                    <div className={styles.solHead}>
                      <span className={styles.solTitle}>{o.title}</span>
                      {o.recommended && <span className={`${styles.pill} ${styles.ok}`}><Sparkles size={11} aria-hidden="true" /> Recomendada</span>}
                    </div>
                    <p className={styles.issueDetail}>{o.explanation}</p>
                    {o.impact && <p className={styles.solImpact}>{o.impact}</p>}
                    <OptionBody opt={o} categoryId={categoryId} onPick={(label, body) => setPending({ opt: o, label, body })}
                      subject={data.issue.subject} />
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function OptionBody({ opt, categoryId, subject, onPick }: {
  opt: Option; categoryId: string; subject: string; onPick: (label: string, body: Record<string, string>) => void;
}) {
  if (opt.action === "link") return <LinkPicker opt={opt} categoryId={categoryId} subject={subject} onPick={onPick} />;
  if (opt.action === "assign_match") return <MatchPicker opt={opt} subject={subject} onPick={onPick} />;
  if (opt.action === "info") {
    return opt.url ? (
      <a href={opt.url} target="_blank" rel="noopener noreferrer" className={styles.docLink}>
        Abrir la planilla en Drive <ExternalLink size={12} aria-hidden="true" />
      </a>
    ) : null;
  }
  const label = opt.action === "not_a_match"
    ? `La pestaña «${subject}» queda marcada como «no es partido».`
    : `«${subject}» se oculta y no vuelve a aparecer (${opt.title.toLowerCase()}).`;
  return (
    <button type="button" className={styles.btnGhost} onClick={() => onPick(label, {})}>Aplicar…</button>
  );
}

function LinkPicker({ opt, categoryId, subject, onPick }: {
  opt: Option; categoryId: string; subject: string; onPick: (label: string, body: Record<string, string>) => void;
}) {
  const cands = opt.candidates ?? [];
  const [sel, setSel] = useState<Candidate | null>(cands.find((c) => c.recommended) ?? null);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Candidate[]>([]);
  const searchId = useId();

  useEffect(() => {
    if (q.trim().length < 3) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api<{ items: Candidate[] }>(`/data-sources/players?category_id=${categoryId}&q=${encodeURIComponent(q)}`)
        .then((r) => { if (!cancelled) setFound(r.items); })
        .catch(() => { if (!cancelled) setFound([]); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q, categoryId]);

  const shown = q.trim().length >= 3 ? found : [];
  const row = (c: Candidate, group: string) => (
    <label key={group + c.id} className={`${styles.cand} ${sel?.id === c.id ? styles.candOn : ""}`}>
      <input type="radio" name={`cand-${group}`} checked={sel?.id === c.id} onChange={() => setSel(c)} />
      <span>
        <strong>{c.name}</strong>
        <span className={styles.candMeta}>
          {[c.category, c.birth_year ? `nac. ${c.birth_year}` : null, c.active ? null : "inactivo"].filter(Boolean).join(" · ")}
        </span>
        {c.reasons && c.reasons.length > 0 && <span className={styles.candWhy}>{c.reasons.join(" · ")}</span>}
      </span>
      {c.recommended && <span className={`${styles.pill} ${styles.ok}`}>Sugerido</span>}
    </label>
  );

  return (
    <div className={styles.picker}>
      {cands.length > 0 ? (
        <div role="radiogroup" aria-label="Jugadores sugeridos">
          <span className={styles.label}>Sugeridos</span>
          {cands.map((c) => row(c, "s"))}
        </div>
      ) : (
        <p className={styles.muted}>No hay un jugador del plantel con un nombre parecido. Búscalo por nombre si está.</p>
      )}
      <label htmlFor={searchId} className={styles.label} style={{ marginTop: 8 }}>Otro jugador del club</label>
      <div className={styles.searchBox}>
        <Search size={14} aria-hidden="true" />
        <input id={searchId} type="search" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Nombre o apellido (mín. 3 letras)" className={styles.searchInput} />
      </div>
      {shown.length > 0 && <div role="radiogroup" aria-label="Resultados de búsqueda">{shown.map((c) => row(c, "q"))}</div>}
      {q.trim().length >= 3 && shown.length === 0 && <p className={styles.muted}>Sin resultados.</p>}
      <button type="button" className={styles.btnPrimary} disabled={!sel}
        onClick={() => sel && onPick(`«${subject}» quedará vinculado a ${sel.name}${sel.category ? ` (${sel.category})` : ""}, en todas las planillas.`,
          { player_id: sel.id })}>
        {sel ? `Vincular a ${sel.name}…` : "Elige un jugador"}
      </button>
    </div>
  );
}

function MatchPicker({ opt, subject, onPick }: {
  opt: Option; subject: string; onPick: (label: string, body: Record<string, string>) => void;
}) {
  const matches = opt.matches ?? [];
  const [value, setValue] = useState(matches.find((m) => m.recommended)?.date ?? "");
  const id = useId();
  if (!matches.length) return <p className={styles.muted}>No hay partidos de este equipo en la temporada.</p>;
  const m = matches.find((x) => x.date === value);
  return (
    <div className={styles.picker}>
      <label htmlFor={id} className={styles.label}>Partido</label>
      <select id={id} className={styles.select} value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">Elige el partido…</option>
        {matches.map((x) => (
          <option key={x.date} value={x.date}>
            {day(x.date)} · {x.opponent || "rival sin registrar"}{x.kind === "friendly" ? " (amistoso)" : ""}{x.recommended ? " — sugerido" : ""}
          </option>
        ))}
      </select>
      <button type="button" className={styles.btnPrimary} disabled={!m}
        onClick={() => m && onPick(`La pestaña «${subject}» quedará asignada al partido del ${day(m.date)}${m.opponent ? ` vs ${m.opponent}` : ""}.`,
          { match_date: m.date })}>
        Asignar…
      </button>
    </div>
  );
}
