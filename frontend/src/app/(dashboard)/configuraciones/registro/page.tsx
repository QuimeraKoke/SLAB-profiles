"use client";

/**
 * Configuraciones › Registro — the club's audit trail: every change to a
 * record (who, when, before → after), every opened player record or download,
 * and the daily backups. Read-only by design: the logs are append-only in the
 * database (backend `audit/`). Same audience as Usuarios (`auth.view_user`).
 */

import React, { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { api, ApiError, getToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { usePermission } from "@/lib/permissions";
import type { UsersMeta } from "@/lib/types";
import base from "../usuarios/page.module.css";
import styles from "./page.module.css";

type Tab = "cambios" | "accesos" | "respaldos";
const TABS: { id: Tab; label: string }[] = [
  { id: "cambios", label: "Cambios" },
  { id: "accesos", label: "Accesos" },
  { id: "respaldos", label: "Respaldos" },
];

interface ChangeRow {
  id: number; at: string; action: "create" | "update" | "delete"; action_label: string;
  model_label: string; object_label: string; object_id: string; player_name: string;
  actor: string; source: string; ip: string; changes: Record<string, unknown>;
}
interface AccessRow {
  id: number; at: string; kind: string; kind_label: string; player_name: string;
  actor: string; ip: string; path: string; detail: string;
}
interface BackupRow {
  started_at: string; finished_at: string | null; status: "ok" | "failed";
  size_bytes: number | null; tables: number | null; error: string;
}
interface Page<T> { rows: T[]; more: boolean }

const API_URL = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

const when = (iso: string) =>
  new Date(iso).toLocaleString("es-CL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

const show = (v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.map(show).join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  return s.length > 140 ? `${s.slice(0, 137)}…` : s;
};

function Changes({ row }: { row: ChangeRow }) {
  const entries = Object.entries(row.changes);
  if (row.action === "create") return <span className={base.muted}>Registro nuevo</span>;
  if (row.action === "delete") {
    return (
      <details>
        <summary className={styles.summary}>Ver contenido borrado ({entries.length} campos)</summary>
        <dl className={styles.diff}>
          {entries.map(([k, v]) => (
            <React.Fragment key={k}><dt>{k}</dt><dd>{show(v)}</dd></React.Fragment>
          ))}
        </dl>
      </details>
    );
  }
  return (
    <dl className={styles.diff}>
      {entries.map(([k, v]) => {
        const [a, b] = Array.isArray(v) && v.length === 2 ? v : [undefined, v];
        return (
          <React.Fragment key={k}>
            <dt>{k}</dt>
            <dd><del>{show(a)}</del> <span aria-hidden>→</span><span className={styles.srOnly}> cambió a </span> <ins>{show(b)}</ins></dd>
          </React.Fragment>
        );
      })}
    </dl>
  );
}

function RegistroInner() {
  const { membership } = useAuth();
  const canView = usePermission("auth.view_user");
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const tab = (TABS.find((t) => t.id === sp.get("tab"))?.id ?? "cambios") as Tab;
  const filters = {
    desde: sp.get("desde") ?? "", hasta: sp.get("hasta") ?? "",
    usuario: sp.get("usuario") ?? "", jugador: sp.get("jugador") ?? "", accion: sp.get("accion") ?? "",
  };
  const [meta, setMeta] = useState<UsersMeta | null>(null);
  const clubId = membership ? membership.club.id : sp.get("club") || meta?.clubs[0]?.id || "";

  const setUrl = useCallback((patch: Record<string, string>) => {
    const qs = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) { if (v) qs.set(k, v); else qs.delete(k); }
    router.replace(`${pathname}?${qs}`, { scroll: false });
  }, [sp, router, pathname]);

  const [draft, setDraft] = useState(filters);
  const filterKey = JSON.stringify(filters);
  useEffect(() => { setDraft(JSON.parse(filterKey)); }, [filterKey]);

  const [changes, setChanges] = useState<Page<ChangeRow> | null>(null);
  const [access, setAccess] = useState<Page<AccessRow> | null>(null);
  const [backups, setBackups] = useState<{ last_ok: BackupRow | null; runs: BackupRow[];
    retention: { daily_days: number; monthly_months: number } } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    if (!canView || membership) return;
    api<UsersMeta>("/users/meta").then(setMeta).catch(() => setMeta(null));
  }, [canView, membership]);

  const query = useCallback((extra: Record<string, string> = {}) => {
    const qs = new URLSearchParams();
    if (!membership && clubId) qs.set("club_id", clubId);
    const f: Record<string, string> = JSON.parse(filterKey);
    for (const [k, v] of Object.entries({ ...f, ...extra })) {
      if (v && !(k === "accion" && tab !== "cambios")) qs.set(k, v);
    }
    return qs.toString();
  }, [membership, clubId, filterKey, tab]);

  useEffect(() => {
    if (!canView || !clubId) return;
    let cancelled = false;
    const fail = (e: unknown) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar el registro."); };
    Promise.resolve().then(() => { if (!cancelled) setError(null); });
    if (tab === "cambios") {
      Promise.resolve().then(() => { if (!cancelled) setChanges(null); });
      api<Page<ChangeRow>>(`/audit/changes?${query()}`).then((d) => { if (!cancelled) setChanges(d); }).catch(fail);
    } else if (tab === "accesos") {
      Promise.resolve().then(() => { if (!cancelled) setAccess(null); });
      api<Page<AccessRow>>(`/audit/access?${query()}`).then((d) => { if (!cancelled) setAccess(d); }).catch(fail);
    } else {
      api<typeof backups>(`/audit/backups?${query()}`).then((d) => { if (!cancelled) setBackups(d); }).catch(fail);
    }
    return () => { cancelled = true; };
  }, [canView, clubId, tab, query]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      if (tab === "cambios" && changes) {
        const d = await api<Page<ChangeRow>>(`/audit/changes?${query({ before: String(changes.rows.at(-1)?.id ?? "") })}`);
        setChanges({ rows: [...changes.rows, ...d.rows], more: d.more });
      } else if (tab === "accesos" && access) {
        const d = await api<Page<AccessRow>>(`/audit/access?${query({ before: String(access.rows.at(-1)?.id ?? "") })}`);
        setAccess({ rows: [...access.rows, ...d.rows], more: d.more });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar más.");
    } finally {
      setLoadingMore(false);
    }
  };

  const download = async () => {
    const path = tab === "cambios" ? "changes.csv" : "access.csv";
    try {
      const res = await fetch(`${API_URL}/audit/${path}?${query()}`, { headers: { Authorization: `Bearer ${getToken() ?? ""}` } });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = tab === "cambios" ? "registro-cambios.csv" : "registro-accesos.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("No se pudo descargar el registro.");
    }
  };

  if (!canView) {
    return <div className={base.container}><div className={base.empty}>Esta sección es solo para administradores del club.</div></div>;
  }

  return (
    <div className={base.container}>
      <header className={base.header}>
        <div>
          <span className={base.eyebrow}>Administración</span>
          <h1 className={base.title}>Registro</h1>
          <p className={base.subtitle}>
            Quién creó, editó o borró cada registro y con qué valores; quién abrió cada ficha o descargó informes;
            y los respaldos diarios de la base. El registro no se puede editar ni borrar.
          </p>
        </div>
      </header>

      <div className={styles.tabs} role="tablist" aria-label="Registro">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
            className={`${styles.tab} ${tab === t.id ? styles.tabOn : ""}`}
            onClick={() => setUrl({ tab: t.id === "cambios" ? "" : t.id })}>
            {t.label}
          </button>
        ))}
      </div>

      <div className={base.toolbar}>
        {membership ? (
          <span className={base.chip}>Mostrando el registro de: {membership.club.name}</span>
        ) : (
          <label className={base.field}>
            <span className={base.label}>Club</span>
            <select value={clubId} onChange={(e) => setUrl({ club: e.target.value })}>
              {(meta?.clubs ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        )}
      </div>

      {tab !== "respaldos" && (
        <form className={styles.filters} onSubmit={(e) => { e.preventDefault(); setUrl(draft); }}>
          <label className={base.field}><span className={base.label}>Desde</span>
            <input type="date" value={draft.desde} onChange={(e) => setDraft({ ...draft, desde: e.target.value })} /></label>
          <label className={base.field}><span className={base.label}>Hasta</span>
            <input type="date" value={draft.hasta} onChange={(e) => setDraft({ ...draft, hasta: e.target.value })} /></label>
          <label className={base.field}><span className={base.label}>Usuario (correo)</span>
            <input type="search" value={draft.usuario} onChange={(e) => setDraft({ ...draft, usuario: e.target.value })} /></label>
          <label className={base.field}><span className={base.label}>Jugador</span>
            <input type="search" value={draft.jugador} onChange={(e) => setDraft({ ...draft, jugador: e.target.value })} /></label>
          {tab === "cambios" && (
            <label className={base.field}><span className={base.label}>Acción</span>
              <select value={draft.accion} onChange={(e) => setDraft({ ...draft, accion: e.target.value })}>
                <option value="">Todas</option>
                <option value="create">Creó</option>
                <option value="update">Editó</option>
                <option value="delete">Borró</option>
              </select></label>
          )}
          <div className={styles.filterActions}>
            <button type="submit" className={base.primaryBtn}>Filtrar</button>
            <button type="button" className={styles.secondaryBtn} onClick={download}>Descargar CSV</button>
          </div>
        </form>
      )}

      {error && <div className={base.error} role="alert">{error}</div>}

      {tab === "cambios" && (
        changes === null ? <div className={base.muted}>Cargando…</div>
          : changes.rows.length === 0 ? <div className={base.empty}>No hay cambios con esos filtros.</div> : (
          <div className={base.tableWrapper}>
            <table className={base.table}>
              <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Registro</th><th>Jugador</th><th>Cambios</th></tr></thead>
              <tbody>
                {changes.rows.map((r) => (
                  <tr key={r.id}>
                    <td className={styles.nowrap}>{when(r.at)}</td>
                    <td>{r.actor}{r.source !== "web" && r.source !== "sistema" && <div className={base.muted}>{r.source}</div>}</td>
                    <td><span className={`${styles.action} ${styles[`action_${r.action}`]}`}>{r.action_label}</span></td>
                    <td>{r.model_label}{r.object_label && <div className={base.muted}>{r.object_label}</div>}</td>
                    <td>{r.player_name || "—"}</td>
                    <td className={styles.changesCell}><Changes row={r} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {tab === "accesos" && (
        access === null ? <div className={base.muted}>Cargando…</div>
          : access.rows.length === 0 ? <div className={base.empty}>No hay accesos con esos filtros.</div> : (
          <>
            <p className={base.muted}>Una ficha abierta varias veces por la misma persona cuenta una vez cada 30 minutos. Las descargas se registran siempre.</p>
            <div className={base.tableWrapper}>
              <table className={base.table}>
                <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Jugador</th><th>IP</th></tr></thead>
                <tbody>
                  {access.rows.map((r) => (
                    <tr key={r.id}>
                      <td className={styles.nowrap}>{when(r.at)}</td>
                      <td>{r.actor}</td>
                      <td>{r.kind_label}</td>
                      <td>{r.player_name || "—"}</td>
                      <td className={base.muted}>{r.ip || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )
      )}

      {tab !== "respaldos" && ((tab === "cambios" && changes?.more) || (tab === "accesos" && access?.more)) && (
        <button type="button" className={styles.secondaryBtn} onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Cargando…" : "Cargar más"}
        </button>
      )}

      {tab === "respaldos" && (
        backups === null ? <div className={base.muted}>Cargando…</div> : (
          <>
            <section className={styles.backupCard} aria-labelledby="bk-head">
              <h2 id="bk-head" className={styles.h2}>Último respaldo correcto</h2>
              {backups.last_ok ? (
                <p>
                  <strong>{when(backups.last_ok.finished_at ?? backups.last_ok.started_at)}</strong> ·{" "}
                  {((backups.last_ok.size_bytes ?? 0) / 1e6).toLocaleString("es-CL", { maximumFractionDigits: 1 })} MB ·{" "}
                  {backups.last_ok.tables} tablas verificadas
                </p>
              ) : <p className={base.muted}>Todavía no hay respaldos registrados.</p>}
              <p className={base.muted}>
                Copia completa de la base cada noche (03:30), verificada antes de guardarla, cifrada (AES-256) en un
                almacenamiento separado de la aplicación. Se guardan los diarios por {backups.retention.daily_days} días
                y uno por mes durante {backups.retention.monthly_months} meses.
              </p>
            </section>
            {backups.runs.length > 0 && (
              <div className={base.tableWrapper}>
                <table className={base.table}>
                  <thead><tr><th>Fecha</th><th>Estado</th><th>Tamaño</th><th>Tablas</th></tr></thead>
                  <tbody>
                    {backups.runs.map((r) => (
                      <tr key={r.started_at}>
                        <td className={styles.nowrap}>{when(r.started_at)}</td>
                        <td>
                          <span className={`${styles.action} ${r.status === "ok" ? styles.action_create : styles.action_delete}`}>
                            {r.status === "ok" ? "Correcto" : "Falló"}
                          </span>
                          {r.error && <div className={base.muted}>{r.error}</div>}
                        </td>
                        <td>{r.size_bytes ? `${(r.size_bytes / 1e6).toLocaleString("es-CL", { maximumFractionDigits: 1 })} MB` : "—"}</td>
                        <td>{r.tables ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )
      )}
    </div>
  );
}

/** useSearchParams needs a Suspense boundary for the production build. */
export default function RegistroPage() {
  return <Suspense fallback={null}><RegistroInner /></Suspense>;
}
