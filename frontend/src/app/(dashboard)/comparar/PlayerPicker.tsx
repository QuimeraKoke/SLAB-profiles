"use client";

/**
 * Selector de jugadores del comparador.
 *
 * `cross_category=true` es el punto: la pantalla existe para cruzar divisiones,
 * así que el buscador tiene que ver todo el club y no sólo las categorías del
 * usuario. El backend igual lo acota a su club.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";

import { api } from "@/lib/api";
import type { Category, PlayerSummary } from "@/lib/types";

import styles from "./page.module.css";

const MAX = 6;

export default function PlayerPicker({
  elegidos, onChange,
}: {
  elegidos: PlayerSummary[];
  onChange: (p: PlayerSummary[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [resultados, setResultados] = useState<PlayerSummary[]>([]);
  const [abierto, setAbierto] = useState(false);
  // id → nombre, y el ORDEN en que la API las devuelve (que es el del club:
  // Primer Equipo primero, después la escalera del formativo). Ordenar por
  // nombre pondría "PEF" antes que "Primer Equipo", que no es el orden que el
  // club tiene en la cabeza.
  const [categorias, setCategorias] = useState<Category[]>([]);
  const caja = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelado = false;
    api<Category[]>("/categories")
      .then((c) => { if (!cancelado) setCategorias(c); })
      .catch(() => { /* sin nombres el selector sigue sirviendo */ });
    return () => { cancelado = true; };
  }, []);

  useEffect(() => {
    const q = query.trim();
    let cancelado = false;
    if (q.length < 2) {
      Promise.resolve().then(() => { if (!cancelado) setResultados([]); });
      return () => { cancelado = true; };
    }
    const t = setTimeout(() => {
      api<PlayerSummary[]>(
        `/players?search=${encodeURIComponent(q)}&limit=10&cross_category=true`,
      )
        .then((r) => { if (!cancelado) setResultados(r); })
        .catch(() => { if (!cancelado) setResultados([]); });
    }, 250);
    return () => { cancelado = true; clearTimeout(t); };
  }, [query]);

  // Cerrar al hacer clic afuera: el desplegable tapa la tabla de abajo.
  useEffect(() => {
    const fuera = (e: MouseEvent) => {
      if (caja.current && !caja.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", fuera);
    return () => document.removeEventListener("mousedown", fuera);
  }, []);

  // Agrupado por categoría, y dentro de cada una por posición. `sort_order`
  // es el orden de cancha (arquero → defensa → mediocampo → ataque) desde que
  // se normalizó el catálogo; antes era 0 en casi todas y no ordenaba nada.
  const grupos = useMemo(() => {
    const porId = new Map(categorias.map((c, i) => [c.id, { nombre: c.name, orden: i }]));
    const mapa = new Map<string, { nombre: string; orden: number; jugadores: PlayerSummary[] }>();
    for (const p of resultados) {
      const meta = porId.get(p.category_id);
      const clave = p.category_id;
      if (!mapa.has(clave)) {
        mapa.set(clave, {
          nombre: meta?.nombre ?? "Sin categoría",
          orden: meta?.orden ?? 999,
          jugadores: [],
        });
      }
      mapa.get(clave)!.jugadores.push(p);
    }
    for (const g of mapa.values()) {
      g.jugadores.sort((a, b) => {
        // Sin posición van al final: son un hueco de datos, no una posición.
        const oa = a.position?.sort_order ?? 9999;
        const ob = b.position?.sort_order ?? 9999;
        if (oa !== ob) return oa - ob;
        return `${a.first_name} ${a.last_name}`.localeCompare(
          `${b.first_name} ${b.last_name}`, "es");
      });
    }
    return [...mapa.values()].sort((a, b) => a.orden - b.orden);
  }, [resultados, categorias]);

  const yaEsta = new Set(elegidos.map((p) => p.id));
  const lleno = elegidos.length >= MAX;

  const agregar = (p: PlayerSummary) => {
    if (yaEsta.has(p.id) || lleno) return;
    onChange([...elegidos, p]);
    setQuery("");
    setResultados([]);
    setAbierto(false);
  };

  return (
    <div className={styles.picker}>
      <div className={styles.elegidos}>
        {elegidos.map((p) => (
          <span key={p.id} className={styles.pill}>
            {p.first_name} {p.last_name}
            <button type="button" className={styles.pillX}
              aria-label={`Quitar a ${p.first_name} ${p.last_name}`}
              onClick={() => onChange(elegidos.filter((x) => x.id !== p.id))}>
              <X size={13} />
            </button>
          </span>
        ))}
      </div>

      <div className={styles.searchBox} ref={caja}>
        <Search size={15} className={styles.searchIcon} aria-hidden="true" />
        <input
          className={styles.searchInput}
          value={query}
          placeholder={lleno ? `Máximo ${MAX} jugadores` : "Buscar jugador…"}
          disabled={lleno}
          aria-label="Buscar jugador"
          onChange={(e) => { setQuery(e.target.value); setAbierto(true); }}
          onFocus={() => setAbierto(true)}
        />
        {abierto && grupos.length > 0 && (
          <ul className={styles.resultados} role="listbox">
            {grupos.map((g) => (
              <li key={g.nombre} role="presentation">
                <p className={styles.grupoCat}>{g.nombre}</p>
                <ul role="group" aria-label={g.nombre} className={styles.grupoLista}>
                  {g.jugadores.map((p) => (
                    <li key={p.id}>
                      <button type="button" className={styles.resultado}
                        disabled={yaEsta.has(p.id)}
                        onClick={() => agregar(p)}>
                        <span>{p.first_name} {p.last_name}</span>
                        {p.position && (
                          <span className={styles.resultadoPos}>{p.position.name}</span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
