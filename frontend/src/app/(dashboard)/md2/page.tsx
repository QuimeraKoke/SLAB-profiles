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
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

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
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const partidoParam = params.get("partido") ?? "";
  const cargando = params.get("modo") === "carga" && canEdit;

  const [data, setData] = useState<Md2Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [borrador, setBorrador] = useState<Record<string, Record<string, Record<string, string>>>>({});
  const [guardando, setGuardando] = useState(false);

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
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "No se pudo cargar MD+2."); });
    return () => { cancelled = true; };
  }, [categoryId, catLoading, partidoParam]);

  const jugaron = useMemo(() => (data?.jugadores ?? []).filter((j) => j.jugo), [data]);
  const otros = useMemo(() => (data?.jugadores ?? []).filter((j) => !j.jugo), [data]);
  const resumen = useMemo(() => {
    const c = { verde: 0, amarillo: 0, rojo: 0, sin: 0 };
    for (const j of jugaron) {
      if (j.general) c[j.general] += 1; else c.sin += 1;
    }
    return c;
  }, [jugaron]);

  const editar = (pid: string, prueba: string, campo: string, valor: string) =>
    setBorrador((b) => ({ ...b, [pid]: { ...b[pid], [prueba]: { ...b[pid]?.[prueba], [campo]: valor } } }));

  const cambios = Object.keys(borrador).length;

  async function guardar() {
    if (!data?.partido || !categoryId || cambios === 0) return;
    setGuardando(true);
    try {
      const filas = Object.entries(borrador).map(([player_id, valores]) => ({ player_id, valores }));
      const out = await api<Md2Payload & { creados: number; actualizados: number }>("/md2", {
        method: "POST",
        body: JSON.stringify({ category_id: categoryId, event_id: data.partido.id, filas }),
      });
      setData(out);
      setBorrador({});
      toast.success(`MD+2 guardado: ${out.creados} nuevo(s), ${out.actualizados} actualizado(s).`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setGuardando(false);
    }
  }

  if (error) return <div className={styles.page}><p role="alert" className={styles.error}>{error}</p></div>;
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
                    const val = borrador[j.player_id]?.[pr.key]?.[c.key] ?? (actual == null ? "" : String(actual));
                    return (
                      <td key={`${pr.key}.${c.key}`}>
                        <input
                          className={styles.input}
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
        </div>
        <div className={styles.controls}>
          <label className={styles.selectLabel}>
            <span>Partido</span>
            <select className={styles.select} value={p.id}
              onChange={(e) => { setBorrador({}); setUrl({ partido: e.target.value }); }}>
              {data.opciones.map((o) => (
                <option key={o.id} value={o.id}>{fecha(o.fecha)} · {o.titulo}</option>
              ))}
            </select>
          </label>
          {canEdit && (
            <button type="button" className={cargando ? styles.secondary : styles.primary}
              onClick={() => { setBorrador({}); setUrl({ modo: cargando ? null : "carga" }); }}>
              {cargando ? "Ver semáforo" : "Cargar datos"}
            </button>
          )}
        </div>
      </header>

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
            {cambios ? `${cambios} jugador(es) con cambios sin guardar` : "Sin cambios"}
            {" · "}Se guarda vinculado al partido y fechado el {fecha(p.fecha_md2)}.
          </span>
          <button type="button" className={styles.primary} disabled={!cambios || guardando} onClick={guardar}>
            {guardando ? "Guardando…" : "Guardar"}
          </button>
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
