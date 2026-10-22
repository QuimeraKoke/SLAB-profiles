"use client";

/**
 * MD+2 — the post-match check, on one screen.
 *
 * Two days after a match the staff take CK, urine density, CMJ and central
 * fatigue. Here the match is chosen for them (the latest PLAYED one; any
 * other from the list), the players who played it come first, and one table
 * both takes the four tests ("Cargar datos") and reads them as a traffic
 * light per test and per player ("Ver semáforo"). Match and mode live in the
 * URL. Backend: `api/md2.py`.
 *
 * Several areas fill it AT ONCE, so it stays in sync quietly:
 *  - every 30 s it asks the server for a fingerprint of the match's MD+2
 *    (`/md2/version`) and refetches only when it moved; paused while the tab
 *    is hidden or a save is in flight, re-checked on return, stopped on
 *    leaving the page. A failed poll never shows an error — after a few in a
 *    row a discreet "sin conexión, reintentando" appears;
 *  - a refresh never touches a cell being typed in: inputs show the draft
 *    over the server value, so only untouched cells move;
 *  - each edited cell remembers the value its author saw; if someone else
 *    saved that same cell meanwhile, the server keeps theirs and returns a
 *    conflict to resolve here (replace / keep);
 *  - the draft survives leaving the page or reloading (sessionStorage,
 *    per match) until it is saved or discarded.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { useConfirm } from "@/components/ui/ConfirmDialog/ConfirmDialog";
import { useToast } from "@/components/ui/Toast/Toast";
import { useCategoryContext } from "@/context/CategoryContext";
import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";

import styles from "./page.module.css";

type Nivel = "verde" | "amarillo" | "rojo";

interface Campo { key: string; label: string; unit?: string | null; min?: number | null; max?: number | null; step?: number | null }
interface Prueba { key: string; label: string; template_id: string; relativo: boolean; campos: Campo[] }
interface Luz { nivel: Nivel | null; valor: number; texto?: string; detalle?: string; cambio_pct?: number }
interface Jugador {
  player_id: string; nombre: string; posicion: string; jugo: boolean;
  minutos: number | null; rol: string | null;
  valores: Record<string, Record<string, number | string | null>>;
  luces: Record<string, Luz | null>;
  general: Nivel | null;
  cmj_referencia: number | null;
}
interface Partido { id: string; titulo: string; fecha: string; fecha_md2: string;
  marcador?: { home?: number; away?: number } | null }
interface Md2Payload {
  partido: Partido | null; fecha_md2?: string; es_hoy?: boolean; opciones: Partido[];
  pruebas: Prueba[]; jugadores: Jugador[];
  criterio_cmj?: { amarillo: number; rojo: number; n: number };
  version?: string;
}
interface Conflicto {
  player_id: string; nombre: string; prueba: string; prueba_label: string;
  campo: string; campo_label: string; guardado: number | string; propuesto: number | string;
}
type Celdas<T> = Record<string, Record<string, Record<string, T>>>;
/** The unsaved edits of one match, and the server value each edited cell
 *  showed when its author started typing (what a conflict is judged on). */
interface Borrador { partido: string | null; valores: Celdas<string>; vistos: Celdas<number | string | null> }

const SIN_BORRADOR: Borrador = { partido: null, valores: {}, vistos: {} };
const SONDEO_MS = 30_000;
const FALLOS_ANTES_DE_AVISAR = 3;
const claveBorrador = (partido: string) => `md2:borrador:${partido}`;

function leerBorrador(partido: string): Borrador {
  try {
    const raw = sessionStorage.getItem(claveBorrador(partido));
    const b = raw ? (JSON.parse(raw) as Partial<Borrador>) : null;
    if (b?.valores && Object.keys(b.valores).length) {
      return { partido, valores: b.valores, vistos: b.vistos ?? {} };
    }
  } catch { /* storage blocked or corrupt — start clean */ }
  return { ...SIN_BORRADOR, partido };
}

function escribirBorrador(b: Borrador) {
  if (!b.partido) return;
  try {
    if (Object.keys(b.valores).length) {
      sessionStorage.setItem(claveBorrador(b.partido), JSON.stringify({ valores: b.valores, vistos: b.vistos }));
    } else {
      sessionStorage.removeItem(claveBorrador(b.partido));
    }
  } catch { /* storage blocked — the draft just won't survive a reload */ }
}

/** `celdas` without the given (player, test, field) cells, pruning empties. */
function sinCeldas<T>(celdas: Celdas<T>, quitar: { player_id: string; prueba: string; campo: string }[]): Celdas<T> {
  const out: Celdas<T> = JSON.parse(JSON.stringify(celdas));
  for (const { player_id, prueba, campo } of quitar) {
    delete out[player_id]?.[prueba]?.[campo];
    if (out[player_id]?.[prueba] && !Object.keys(out[player_id][prueba]).length) delete out[player_id][prueba];
    if (out[player_id] && !Object.keys(out[player_id]).length) delete out[player_id];
  }
  return out;
}

function hora(): string {
  return new Date().toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
}

const NIVEL_LABEL: Record<Nivel, string> = { verde: "Bien", amarillo: "Vigilar", rojo: "Alerta" };

function fecha(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function num(v: unknown): string {
  if (typeof v !== "number") return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 3 : 1).replace(/\.?0+$/, "");
}

export default function Md2Page() {
  const { categoryId, loading: catLoading } = useCategoryContext();
  const canEdit = usePermission("exams.add_examresult");
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const partidoParam = params.get("partido") ?? "";
  const cargando = params.get("modo") === "carga" && canEdit;

  const [data, setData] = useState<Md2Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorGuardar, setErrorGuardar] = useState<string | null>(null);
  const [draft, setDraft] = useState<Borrador>(SIN_BORRADOR);
  const [conflictos, setConflictos] = useState<Conflicto[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [sync, setSync] = useState<{ hora: string | null; deOtro: boolean; sinConexion: boolean }>(
    { hora: null, deOtro: false, sinConexion: false });

  const partidoId = data?.partido?.id ?? null;
  // The draft on screen is only the one of the match on screen.
  const borrador = draft.partido === partidoId ? draft.valores : {};

  // What the poller needs to read without restarting: the version on screen,
  // whether a save is in flight, and a counter that tells a late poll its
  // answer is older than what a save (or a match switch) already put there.
  const versionRef = useRef<string | null>(null);
  const guardandoRef = useRef(false);
  const generacionRef = useRef(0);
  useEffect(() => { versionRef.current = data?.version ?? null; }, [data]);
  useEffect(() => { guardandoRef.current = guardando; }, [guardando]);

  const mostrar = useCallback((d: Md2Payload) => {
    generacionRef.current += 1;
    setData(d);
  }, []);

  const setUrl = useCallback((cambios: Record<string, string | null>) => {
    const sp = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(cambios)) {
      if (v) sp.set(k, v); else sp.delete(k);
    }
    router.replace(`${pathname}?${sp.toString()}`, { scroll: false });
  }, [params, pathname, router]);

  useEffect(() => {
    if (catLoading || !categoryId) return;
    let cancelled = false;
    const sp = new URLSearchParams({ category_id: categoryId });
    if (partidoParam) sp.set("event_id", partidoParam);
    api<Md2Payload>(`/md2?${sp}`)
      .then((d) => { if (!cancelled) { mostrar(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar MD+2."); });
    return () => { cancelled = true; };
  }, [categoryId, catLoading, partidoParam, mostrar]);

  // Bring back this match's unsaved draft (a reload, or leaving and coming back).
  useEffect(() => {
    if (!partidoId) return;
    queueMicrotask(() => {
      setDraft((d) => (d.partido === partidoId ? d : leerBorrador(partidoId)));
      setConflictos([]);
    });
  }, [partidoId]);
  useEffect(() => { escribirBorrador(draft); }, [draft]);

  // Quiet 30 s sync — see the header comment.
  useEffect(() => {
    if (!partidoId || !categoryId) return;
    let vivo = true;
    let enCurso: AbortController | null = null;
    let fallos = 0;
    let ultimo = Date.now();
    const sp = new URLSearchParams({ category_id: categoryId, event_id: partidoId });

    const revisar = async () => {
      if (!vivo || enCurso || document.hidden || guardandoRef.current) return;
      enCurso = new AbortController();
      ultimo = Date.now();
      const generacion = generacionRef.current;
      try {
        const { version } = await api<{ version: string }>(`/md2/version?${sp}`, { signal: enCurso.signal });
        if (version !== versionRef.current) {
          const d = await api<Md2Payload>(`/md2?${sp}`, { signal: enCurso.signal });
          if (vivo && generacion === generacionRef.current && !guardandoRef.current && d.partido?.id === partidoId) {
            mostrar(d);
            setSync({ hora: hora(), deOtro: true, sinConexion: false });
          }
        } else if (vivo) {
          setSync((s) => (s.sinConexion ? { ...s, sinConexion: false } : s));
        }
        fallos = 0;
      } catch (e) {
        if (!vivo || (e instanceof DOMException && e.name === "AbortError")) return;
        fallos += 1;
        if (fallos >= FALLOS_ANTES_DE_AVISAR) setSync((s) => ({ ...s, sinConexion: true }));
      } finally {
        enCurso = null;
      }
    };

    const intervalo = window.setInterval(() => { void revisar(); }, SONDEO_MS);
    // Back on the tab (or the network): check now rather than wait the rest of the 30 s.
    const alVolver = () => {
      if (!document.hidden && Date.now() - ultimo > 5_000) void revisar();
    };
    document.addEventListener("visibilitychange", alVolver);
    window.addEventListener("online", alVolver);
    return () => {
      vivo = false;
      enCurso?.abort();
      window.clearInterval(intervalo);
      document.removeEventListener("visibilitychange", alVolver);
      window.removeEventListener("online", alVolver);
    };
  }, [partidoId, categoryId, mostrar]);

  const jugaron = useMemo(() => (data?.jugadores ?? []).filter((j) => j.jugo), [data]);
  const otros = useMemo(() => (data?.jugadores ?? []).filter((j) => !j.jugo), [data]);
  const resumen = useMemo(() => {
    const c = { verde: 0, amarillo: 0, rojo: 0, sin: 0 };
    for (const j of jugaron) {
      if (j.general) c[j.general] += 1; else c.sin += 1;
    }
    return c;
  }, [jugaron]);

  const valorServidor = (pid: string, prueba: string, campo: string) => {
    const v = data?.jugadores.find((j) => j.player_id === pid)?.valores[prueba]?.[campo];
    return v == null || v === "" ? null : v;
  };

  const editar = (pid: string, prueba: string, campo: string, valor: string) => {
    if (!partidoId) return;
    const visto = valorServidor(pid, prueba, campo);
    setDraft((d) => {
      const base = d.partido === partidoId ? d : { ...SIN_BORRADOR, partido: partidoId };
      const yaVisto = base.vistos[pid]?.[prueba] && campo in base.vistos[pid][prueba];
      return {
        partido: partidoId,
        valores: { ...base.valores, [pid]: { ...base.valores[pid], [prueba]: { ...base.valores[pid]?.[prueba], [campo]: valor } } },
        vistos: yaVisto ? base.vistos
          : { ...base.vistos, [pid]: { ...base.vistos[pid], [prueba]: { ...base.vistos[pid]?.[prueba], [campo]: visto } } },
      };
    });
  };

  const cambios = Object.keys(borrador).length;

  type Guardado = Md2Payload & { creados: number; actualizados: number; conflictos: Conflicto[] };

  async function enviar(filas: unknown[]): Promise<Guardado | null> {
    if (!partidoId || !categoryId) return null;
    setGuardando(true);
    guardandoRef.current = true;
    setErrorGuardar(null);
    try {
      const out = await api<Guardado>("/md2", {
        method: "POST",
        body: JSON.stringify({ category_id: categoryId, event_id: partidoId, filas }),
      });
      mostrar(out);
      return out;
    } catch (e) {
      // The draft stays as it was: nothing typed is lost on a failed save.
      setErrorGuardar(e instanceof ApiError ? e.message : "No se pudo guardar. Revisa la conexión e inténtalo de nuevo.");
      return null;
    } finally {
      guardandoRef.current = false;
      setGuardando(false);
    }
  }

  async function guardar() {
    if (cambios === 0 || guardando) return;
    const filas = Object.entries(borrador).map(([player_id, valores]) => ({
      player_id, valores, previos: draft.vistos[player_id] ?? {},
    }));
    const out = await enviar(filas);
    if (!out) return;
    const enConflicto = out.conflictos ?? [];
    // Keep only the cells that clashed; everything else is saved.
    setDraft((d) => ({
      partido: d.partido,
      valores: Object.fromEntries(Object.entries(d.valores).flatMap(([pid, pruebas]) => {
        const quedan = Object.fromEntries(Object.entries(pruebas).flatMap(([pr, campos]) => {
          const c = Object.fromEntries(Object.entries(campos).filter(([k]) =>
            enConflicto.some((x) => x.player_id === pid && x.prueba === pr && x.campo === k)));
          return Object.keys(c).length ? [[pr, c]] : [];
        }));
        return Object.keys(quedan).length ? [[pid, quedan]] : [];
      })),
      vistos: d.vistos,
    }));
    setConflictos(enConflicto);
    if (out.creados + out.actualizados > 0) {
      toast.success(`MD+2 guardado: ${out.creados} nuevo(s), ${out.actualizados} actualizado(s).`);
    }
  }

  async function reemplazar() {
    const porJugador: Record<string, Record<string, Record<string, number | string>>> = {};
    for (const c of conflictos) {
      ((porJugador[c.player_id] ??= {})[c.prueba] ??= {})[c.campo] = c.propuesto;
    }
    const out = await enviar(Object.entries(porJugador).map(([player_id, valores]) => ({ player_id, valores, forzar: true })));
    if (!out) return;
    descartarConflictos();
    toast.success(`Se reemplazaron ${conflictos.length} valor(es) con los tuyos.`);
  }

  function descartarConflictos() {
    setDraft((d) => ({ partido: d.partido, valores: sinCeldas(d.valores, conflictos), vistos: sinCeldas(d.vistos, conflictos) }));
    setConflictos([]);
  }

  async function descartar() {
    const ok = await confirm({
      title: "Descartar cambios",
      message: `¿Descartar los cambios sin guardar de ${cambios} jugador(es)? No se puede deshacer.`,
      confirmLabel: "Descartar",
      variant: "danger",
    });
    if (!ok) return;
    setDraft({ ...SIN_BORRADOR, partido: partidoId });
    setConflictos([]);
  }

  if (error && !data) return <div className={styles.page}><p role="alert" className={styles.error}>{error}</p></div>;
  if (!data) return <div className={styles.page}><p className={styles.muted}>Cargando…</p></div>;
  if (!data.partido) {
    return (
      <div className={styles.page}>
        <h1 className={styles.title}>MD+2</h1>
        <p className={styles.muted}>Esta categoría no tiene partidos jugados registrados.</p>
      </div>
    );
  }
  if (data.pruebas.length === 0) {
    return (
      <div className={styles.page}>
        <h1 className={styles.title}>MD+2</h1>
        <p className={styles.muted}>Ninguna de las pruebas de MD+2 (CK, hidratación, CMJ, fatiga central) aplica a esta categoría.</p>
      </div>
    );
  }

  const p = data.partido;
  const tabla = (lista: Jugador[]) => (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.colJugador}>Jugador</th>
            {!cargando && <th>Estado</th>}
            {data.pruebas.map((pr) => (
              <th key={pr.key} colSpan={cargando ? pr.campos.length : 1}>{pr.label}</th>
            ))}
          </tr>
          {cargando && (
            <tr className={styles.subhead}>
              <th />
              {data.pruebas.flatMap((pr) => pr.campos.map((c) => (
                <th key={`${pr.key}.${c.key}`}>{c.label}{c.unit ? ` (${c.unit})` : ""}</th>
              )))}
            </tr>
          )}
        </thead>
        <tbody>
          {lista.map((j) => (
            <tr key={j.player_id}>
              <th scope="row" className={styles.colJugador}>
                <span className={styles.nombre}>{j.nombre}</span>
                <span className={styles.meta}>{[j.posicion, j.rol].filter(Boolean).join(" · ")}</span>
              </th>
              {!cargando && (
                <td><Semaforo nivel={j.general} grande /></td>
              )}
              {cargando
                ? data.pruebas.flatMap((pr) => pr.campos.map((c) => {
                    const actual = j.valores[pr.key]?.[c.key];
                    const propio = borrador[j.player_id]?.[pr.key]?.[c.key];
                    const val = propio ?? (actual == null ? "" : String(actual));
                    // Someone saved this very cell after this user started typing in it.
                    const visto = draft.vistos[j.player_id]?.[pr.key]?.[c.key];
                    const pisado = propio != null && visto !== undefined
                      && String(visto ?? "") !== String(actual ?? "") && String(actual ?? "") !== propio;
                    return (
                      <td key={`${pr.key}.${c.key}`}>
                        <input
                          className={`${styles.input} ${pisado ? styles.inputPisado : ""}`}
                          title={pisado ? `Otra persona guardó ${actual ?? "vacío"} mientras editabas` : undefined}
                          type="number" inputMode="decimal"
                          step={c.step ?? "any"} min={c.min ?? undefined} max={c.max ?? undefined}
                          value={val}
                          aria-label={`${pr.label} · ${c.label} · ${j.nombre}`}
                          onChange={(e) => editar(j.player_id, pr.key, c.key, e.target.value)}
                        />
                      </td>
                    );
                  }))
                : data.pruebas.map((pr) => {
                    const luz = j.luces[pr.key];
                    return (
                      <td key={pr.key} title={luz?.detalle || undefined}>
                        {luz ? (
                          <span className={styles.celda}>
                            <Semaforo nivel={luz.nivel} />
                            <span className={styles.valor}>{luz.texto ?? num(luz.valor)}</span>
                            {luz.detalle && <span className={styles.detalle}>{luz.detalle}</span>}
                          </span>
                        ) : <span className={styles.muted}>—</span>}
                      </td>
                    );
                  })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>MD+2</h1>
          <p className={styles.subtitle}>
            <strong>{p.titulo}</strong>
            {p.marcador && typeof p.marcador.home === "number" && ` (${p.marcador.home}–${p.marcador.away})`}
            {` · jugado el ${fecha(p.fecha)} · MD+2: ${fecha(p.fecha_md2)}`}
            {data.es_hoy && <span className={styles.hoy}>hoy</span>}
          </p>
          <p className={`${styles.sync} ${sync.sinConexion ? styles.syncAviso : ""}`} aria-live="polite">
            {sync.sinConexion
              ? "Sin conexión con el servidor — reintentando…"
              : sync.deOtro && sync.hora
                ? `Actualizado con datos de otras áreas a las ${sync.hora}`
                : "Se actualiza solo cada 30 s"}
          </p>
        </div>
        <div className={styles.controls}>
          <label className={styles.selectLabel}>
            <span>Partido</span>
            <select className={styles.select} value={p.id}
              onChange={(e) => setUrl({ partido: e.target.value })}>
              {data.opciones.map((o) => (
                <option key={o.id} value={o.id}>{fecha(o.fecha)} · {o.titulo}</option>
              ))}
            </select>
          </label>
          {canEdit && (
            <button type="button" className={cargando ? styles.secondary : styles.primary}
              onClick={() => setUrl({ modo: cargando ? null : "carga" })}>
              {cargando ? "Ver semáforo" : "Cargar datos"}
            </button>
          )}
        </div>
      </header>

      {error && <p role="alert" className={styles.error}>{error}</p>}

      {conflictos.length > 0 && (
        <section className={styles.conflictos} role="alert" aria-labelledby="md2-conflictos">
          <h2 id="md2-conflictos" className={styles.h2}>
            Otra persona guardó {conflictos.length === 1 ? "este valor" : "estos valores"} mientras editabas
          </h2>
          <ul>
            {conflictos.map((c) => (
              <li key={`${c.player_id}.${c.prueba}.${c.campo}`}>
                <strong>{c.nombre}</strong> · {c.prueba_label}{c.campo_label !== c.prueba_label && ` · ${c.campo_label}`}:{" "}
                guardado <strong>{num(c.guardado)}</strong>, el tuyo <strong>{num(c.propuesto)}</strong>
              </li>
            ))}
          </ul>
          <div className={styles.conflictoAcciones}>
            <button type="button" className={styles.secondary} disabled={guardando} onClick={descartarConflictos}>
              Mantener lo guardado
            </button>
            <button type="button" className={styles.primary} disabled={guardando} onClick={reemplazar}>
              Reemplazar con los míos
            </button>
          </div>
        </section>
      )}

      {!cargando && (
        <section className={styles.resumen} aria-label="Resumen del plantel">
          <span><Semaforo nivel="rojo" /> {resumen.rojo} en alerta</span>
          <span><Semaforo nivel="amarillo" /> {resumen.amarillo} a vigilar</span>
          <span><Semaforo nivel="verde" /> {resumen.verde} bien</span>
          <span className={styles.muted}>{resumen.sin} sin datos · de {jugaron.length} que jugaron</span>
        </section>
      )}

      {jugaron.length > 0 ? (
        <section>
          <h2 className={styles.h2}>Jugaron el partido ({jugaron.length})</h2>
          {tabla(jugaron)}
        </section>
      ) : (
        <p className={styles.muted}>La ficha del partido no tiene jugadores con minutos.</p>
      )}

      {otros.length > 0 && (
        <details className={styles.otros}>
          <summary>Otros jugadores del plantel ({otros.length})</summary>
          {tabla(otros)}
        </details>
      )}

      {cargando && (
        <div className={styles.saveBar}>
          <span className={styles.muted}>
            {errorGuardar
              ? <span role="alert" className={styles.error}>{errorGuardar}</span>
              : <>
                  {cambios ? `${cambios} jugador(es) con cambios sin guardar` : "Sin cambios"}
                  {" · "}Se guarda vinculado al partido y fechado el {fecha(p.fecha_md2)}.
                </>}
          </span>
          <span className={styles.saveAcciones}>
            {cambios > 0 && (
              <button type="button" className={styles.secondary} disabled={guardando} onClick={descartar}>
                Descartar
              </button>
            )}
            <button type="button" className={styles.primary} disabled={!cambios || guardando} onClick={guardar}>
              {guardando ? "Guardando…" : "Guardar"}
            </button>
          </span>
        </div>
      )}

      <footer className={styles.leyenda}>
        <span><Semaforo nivel="verde" /> Bien</span>
        <span><Semaforo nivel="amarillo" /> Vigilar</span>
        <span><Semaforo nivel="rojo" /> Alerta</span>
        <span className={styles.muted}>
          CK, hidratación y fatiga central: bandas de cada prueba.
          {data.criterio_cmj && ` CMJ: frente al promedio de sus últimas ${data.criterio_cmj.n} mediciones `
            + `(caída de ${Math.abs(data.criterio_cmj.amarillo)} % vigilar, de ${Math.abs(data.criterio_cmj.rojo)} % alerta).`}
          {" "}Estado = la peor de sus pruebas.
        </span>
      </footer>
    </div>
  );
}

function Semaforo({ nivel, grande }: { nivel: Nivel | null; grande?: boolean }) {
  const label = nivel ? NIVEL_LABEL[nivel] : "Sin referencia";
  return (
    <span className={`${styles.dot} ${grande ? styles.dotGrande : ""} ${nivel ? styles[nivel] : styles.sinNivel}`}
      role="img" aria-label={label} title={label} />
  );
}
