"use client";

/**
 * Comparador de jugadores entre divisiones.
 *
 * Responde la pregunta de proyección del club: *¿este juvenil ya rinde como un
 * jugador de Primer Equipo en su puesto?* Dos tarjetas a los costados, la
 * comparación al medio, y un switch que la pasa de tabla a gráfico.
 *
 * El gráfico tiene dos modos, y la diferencia importa:
 *
 * - **Valor vs valor** — los últimos valores, uno al lado del otro.
 * - **Evolución** — las dos series SIN forzar que las fechas calcen. Cruzarlas
 *   por día calendario es lo que rompe la comparación entre divisiones: dos
 *   chicos de categorías distintas entrenan otros días, otros ciclos, otras
 *   temporadas, y el resultado es una línea con un punto y la otra vacía. Acá
 *   el eje es relativo y cada serie arranca en su propio origen, así que se
 *   comparan las FORMAS de las curvas.
 *
 * El eje relativo tiene a su vez dos orígenes, y el segundo es el que contesta
 * la pregunta de proyección:
 *
 * - **Desde el primer registro** — compara trayectorias desde que empezamos a
 *   medir a cada uno. Puntos de partida arbitrarios: depende de cuándo entró
 *   cada jugador al sistema.
 * - **Por edad** — dónde estaba cada uno a la misma edad. Con 98,5% de fechas
 *   de nacimiento cargadas, es el eje que de verdad compara un Sub 15 con un
 *   Sub 20.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, PolarAngleAxis, PolarGrid,
  PolarRadiusAxis, Radar as RadarSerie, RadarChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "@/lib/api";
import { type InjuryRange, day as isoDay } from "@/lib/injuryRanges";
import type {
  ComparisonMetric, ComparisonPlayer, ComparisonSection,
  PlayerComparisonPayload, PlayerSummary,
} from "@/lib/types";

import DateRangeControl, { type DateRangeValue }
  from "@/components/common/DateRangeControl";
import { referenceBandAreas } from "@/components/dashboards/widgets/ReferenceBands";

import { InjuryRail, type RailMarker } from "./InjuryRail";
import LesionesComparadas from "./LesionesComparadas";
import PlayerPicker from "./PlayerPicker";
import styles from "./page.module.css";

/** Un color por jugador, estable entre la tarjeta, la tabla y el gráfico. */
const COLORES = ["#2563eb", "#db2777", "#16a34a", "#f59e0b", "#7c3aed", "#0891b2"];

type Vista = "tabla" | "grafico";
type Origen = "registro" | "edad";

export default function CompararPage() {
  const [elegidos, setElegidos] = useState<PlayerSummary[]>([]);
  const [metricas, setMetricas] = useState<ComparisonMetric[]>([]);
  // Una configuración por sección, guardada POR CLUB: qué se mira es una
  // curaduría del cuerpo técnico, no una preferencia personal. `claves` es la
  // unión de las tres — se pide una sola vez y cada sección filtra lo suyo.
  const [secciones, setSecciones] = useState<Record<ComparisonSection, string[]>>(
    { cards: [], radar: [], table: [] });
  const [editando, setEditando] = useState<ComparisonSection | null>(null);
  const claves = useMemo(
    () => [...new Set([...secciones.cards, ...secciones.radar, ...secciones.table])],
    [secciones]);
  const [datos, setDatos] = useState<PlayerComparisonPayload | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 6 meses por defecto. Una comparación sin ventana mezcla el estado actual
  // con lecturas de hace dos años, y en el formativo eso son dos categorías
  // distintas del mismo chico.
  const [rango, setRango] = useState<DateRangeValue>(
    { preset: "180", date: { from: "", to: "" } });
  const [vista, setVista] = useState<Vista>("tabla");
  const [origen, setOrigen] = useState<Origen>("registro");

  // ── catálogo de métricas ────────────────────────────────────────────
  // Endpoint propio del comparador y no `/alert-rules/meta`: aquel exige
  // permiso de alertas, y alguien con permiso de comparar habría visto el
  // selector vacío sin ningún error.
  useEffect(() => {
    const primera = elegidos[0]?.category_id;
    let cancelado = false;
    if (!primera) {
      Promise.resolve().then(() => {
        if (cancelado) return;
        setMetricas([]);
        setSecciones({ cards: [], radar: [], table: [] });
      });
      return () => { cancelado = true; };
    }
    api<{ templates?: { slug: string; name: string; fields?: { key: string; label: string; unit?: string; has_band_rule?: boolean }[] }[] }>(
      `/players/comparison/metrics?category_id=${primera}`,
    )
      .then((meta) => {
        if (cancelado) return;
        const out: ComparisonMetric[] = [];
        const conBanda: string[] = [];
        for (const t of meta.templates ?? []) {
          for (const f of t.fields ?? []) {
            const key = `${t.slug}:${f.key}`;
            out.push({
              key, field_key: f.key, template: t.slug,
              template_label: t.name, label: f.label, unit: f.unit ?? "",
              direction_of_good: "neutral",
            });
            if (f.has_band_rule) conBanda.push(key);
          }
        }
        setMetricas(out);
        // Lo guardado manda; una sección sin guardar cae al default: las
        // métricas para las que el club definió bandas en esta categoría. Son
        // sus indicadores elegidos, ~10 de 238 campos. Antes el default eran
        // "los primeros cinco del catálogo", que no significaba nada — ese
        // orden lo decide el esquema, no el criterio de nadie.
        const porDefecto = conBanda.length ? conBanda : out.slice(0, 5).map((m) => m.key);
        api<Record<ComparisonSection, string[]>>(
          `/players/comparison/sections?category_id=${primera}`,
        )
          .then((g) => {
            if (cancelado) return;
            setSecciones({
              cards: g.cards?.length ? g.cards : porDefecto,
              radar: g.radar?.length ? g.radar : porDefecto,
              table: g.table?.length ? g.table : porDefecto,
            });
          })
          .catch(() => {
            if (!cancelado) setSecciones({
              cards: porDefecto, radar: porDefecto, table: porDefecto });
          });
      })
      .catch(() => { if (!cancelado) setMetricas([]); });
    return () => { cancelado = true; };
  }, [elegidos]);

  // ── lesiones de los elegidos ────────────────────────────────────────
  // Aparte de la comparación: no dependen de las métricas ni de la vista, y
  // un fallo acá deja los gráficos sin marcadores, no sin gráficos.
  const [lesiones, setLesiones] = useState<InjuryRange[]>([]);
  useEffect(() => {
    let cancelado = false;
    if (elegidos.length === 0) {
      Promise.resolve().then(() => setLesiones([]));
      return;
    }
    api<InjuryRange[]>(`/injuries/ranges?players=${elegidos.map((p) => p.id).join(",")}`)
      .then((r) => { if (!cancelado) setLesiones(r); })
      .catch(() => { if (!cancelado) setLesiones([]); });
    return () => { cancelado = true; };
  }, [elegidos]);

  // ── la comparación ──────────────────────────────────────────────────
  const traer = useCallback(() => {
    if (elegidos.length === 0 || claves.length === 0) {
      Promise.resolve().then(() => setDatos(null));
      return;
    }
    // Mismo microtask que arriba: `traer` la llama un effect, así que sus
    // setState tienen que ser asíncronos para React 19.
    Promise.resolve().then(() => { setCargando(true); setError(null); });
    api<PlayerComparisonPayload>(
      `/players/comparison?players=${elegidos.map((p) => p.id).join(",")}`
      + `&metrics=${encodeURIComponent(claves.join(","))}`
      // En tabla no viaja ninguna serie: las tarjetas y la tabla sólo usan el
      // último valor. En gráfico se dibuja UNA por métrica, así que ahí sí se
      // piden todas — y el costo pasa a depender de cuántas métricas elegiste,
      // que es lo que el selector controla.
      + (vista === "grafico" && secciones.table.length
        ? `&series=${encodeURIComponent(secciones.table.join(","))}` : "")
      // El radar necesita el percentil intra-categoría; es opt-in porque
      // cuesta una consulta por (plantilla, categoría).
      + (secciones.radar.length ? "&percentiles=true" : "")
      + ventana(rango),
    )
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "No se pudo comparar."))
      .finally(() => setCargando(false));
  }, [elegidos, claves, vista, secciones, rango]);

  useEffect(() => { traer(); }, [traer]);

  const guardarSeccion = useCallback((seccion: ComparisonSection, keys: string[]) => {
    setSecciones((prev) => ({ ...prev, [seccion]: keys }));
    const categoria = elegidos[0]?.category_id;
    if (!categoria) return;
    // Optimista: la sección ya se redibujó. Si el guardado falla, lo que se ve
    // sigue siendo correcto para esta sesión y el próximo ingreso vuelve a lo
    // guardado — preferible a bloquear la pantalla por una preferencia.
    api(`/players/comparison/sections/${seccion}`, {
      method: "PUT",
      body: JSON.stringify({ category_id: categoria, metric_keys: keys }),
    }).catch(() => { /* ver arriba */ });
  }, [elegidos]);

  const colorDe = useCallback(
    (i: number) => COLORES[i % COLORES.length], [],
  );

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.h1}>Comparar jugadores</h1>
          <p className={styles.sub}>
            Entre divisiones, contra la media de su línea en Primer Equipo.
          </p>
        </div>
      </header>

      <div className={styles.controles}>
        <PlayerPicker elegidos={elegidos} onChange={setElegidos} />
        <DateRangeControl value={rango} onChange={setRango} variant="compact" />
      </div>

      {error && <p className={styles.error}>{error}</p>}

      {elegidos.length === 0 ? (
        <p className={styles.vacio}>
          Elegí un jugador para ver su ficha, o dos o más para compararlos.
        </p>
      ) : !datos ? (
        <p className={styles.vacio}>{cargando ? "Cargando…" : "Sin datos."}</p>
      ) : (
        <div className={styles.comparador}>
          {/* ── 1 · Tarjetas ───────────────────────────────────────── */}
          <SeccionCabecera
            titulo="Ficha" seccion="cards" n={secciones.cards.length}
            editando={editando} onEditar={setEditando} />
          {editando === "cards" && (
            <MetricPicker metricas={metricas} claves={secciones.cards}
              onChange={(k) => guardarSeccion("cards", k)} />
          )}
          <div className={styles.tarjetas}>
            {datos.players.map((p, i) => (
              <PlayerCard
                key={p.id} player={p}
                metrics={filtrar(datos.metrics, secciones.cards)}
                color={colorDe(i)} benchmark={datos.benchmark} />
            ))}
          </div>

          {/* ── 2 · Radar ──────────────────────────────────────────── */}
          <SeccionCabecera
            titulo="Perfil por percentil" seccion="radar"
            n={secciones.radar.length}
            editando={editando} onEditar={setEditando} />
          {editando === "radar" && (
            <MetricPicker metricas={metricas} claves={secciones.radar}
              onChange={(k) => guardarSeccion("radar", k)} />
          )}
          <Radar datos={datos} metricas={filtrar(datos.metrics, secciones.radar)}
            colorDe={colorDe} />

          {/* ── 3 · Tabla y gráficos ───────────────────────────────── */}
          <SeccionCabecera
            titulo="Detalle" seccion="table" n={secciones.table.length}
            editando={editando} onEditar={setEditando} />
          {editando === "table" && (
            <MetricPicker metricas={metricas} claves={secciones.table}
              onChange={(k) => guardarSeccion("table", k)} />
          )}
          <section className={styles.centro}>
            <div className={styles.switchRow}>
              <div className={styles.segmented} role="tablist" aria-label="Vista">
                <button type="button" role="tab" aria-selected={vista === "tabla"}
                  className={vista === "tabla" ? styles.segOn : styles.seg}
                  onClick={() => setVista("tabla")}>Tabla</button>
                <button type="button" role="tab" aria-selected={vista === "grafico"}
                  className={vista === "grafico" ? styles.segOn : styles.seg}
                  onClick={() => setVista("grafico")}>Gráfico</button>
              </div>
              {vista === "grafico" && (
                <div className={styles.segmented} role="tablist" aria-label="Origen del eje">
                  <button type="button" role="tab" aria-selected={origen === "registro"}
                    className={origen === "registro" ? styles.segOn : styles.seg}
                    onClick={() => setOrigen("registro")}>Desde el 1er registro</button>
                  <button type="button" role="tab" aria-selected={origen === "edad"}
                    className={origen === "edad" ? styles.segOn : styles.seg}
                    onClick={() => setOrigen("edad")}>Por edad</button>
                </div>
              )}
            </div>

            {vista === "tabla" ? (
              <ComparisonTable
                datos={{ ...datos, metrics: filtrar(datos.metrics, secciones.table) }}
                colorDe={colorDe} />
            ) : (
              <GraficosPorExamen
                datos={{ ...datos, metrics: filtrar(datos.metrics, secciones.table) }}
                colorDe={colorDe} origen={origen} lesiones={lesiones} />
            )}
          </section>

          {/* ── 4 · Lesiones ───────────────────────────────────────── */}
          <LesionesComparadas
            players={datos.players} lesiones={lesiones} colorDe={colorDe}
            {...periodo(rango)} />
        </div>
      )}
    </div>
  );
}

/** Las métricas de una sección, en el orden en que la configuración las dejó. */
function filtrar(todas: ComparisonMetric[], claves: string[]): ComparisonMetric[] {
  const porClave = new Map(todas.map((m) => [m.key, m]));
  return claves.map((k) => porClave.get(k)).filter(Boolean) as ComparisonMetric[];
}

/* ── cabecera de sección ─────────────────────────────────────────────── */

function SeccionCabecera({
  titulo, seccion, n, editando, onEditar,
}: {
  titulo: string;
  seccion: ComparisonSection;
  n: number;
  editando: ComparisonSection | null;
  onEditar: (s: ComparisonSection | null) => void;
}) {
  const abierto = editando === seccion;
  return (
    <div className={styles.seccionCab}>
      <h2 className={styles.seccionTitulo}>{titulo}</h2>
      <button type="button" className={styles.linkBtn}
        aria-expanded={abierto}
        onClick={() => onEditar(abierto ? null : seccion)}>
        {abierto ? "Listo" : `Configurar (${n})`}
      </button>
    </div>
  );
}

/* ── radar de percentiles ────────────────────────────────────────────── */

/**
 * Un eje por métrica, un polígono por jugador, y el valor es el PERCENTIL del
 * jugador dentro de su propia categoría.
 *
 * Por qué percentil y no el valor: el radar mezcla km/h, kg, segundos y
 * centímetros, que no comparten escala; y entre divisiones el valor crudo sólo
 * diría la edad — un Sub 13 contra un Sub 20 saldría aplastado contra el
 * centro. El percentil contra sus propios pares contesta lo que importa: quién
 * está mejor parado en su grupo.
 *
 * El backend ya invirtió el percentil donde el valor crudo mejor es el más
 * bajo, así que **más lejos del centro es siempre mejor, en todos los ejes**.
 * Aun así cada etiqueta lleva su flecha (↑ / ↓) diciendo hacia dónde mejora la
 * métrica cruda: sin eso, alguien que mira "T10" a 90 podría leer que corre
 * lento. El tooltip muestra las dos cosas — el valor real y el percentil.
 */
function Radar({
  datos, metricas, colorDe,
}: {
  datos: PlayerComparisonPayload;
  metricas: ComparisonMetric[];
  colorDe: (i: number) => string;
}) {
  const [modo, setModo] = useState<"percentil" | "valor">("percentil");
  const pct = datos.percentiles;
  const porPercentil = modo === "percentil" && !!pct;

  const filas = useMemo(() => metricas.map((m) => {
    const flecha = m.direction_of_good === "down" ? "↓"
      : m.direction_of_good === "up" ? "↑" : "";
    const fila: Record<string, string | number | null> = {
      eje: `${m.label}${flecha ? ` ${flecha}` : ""}`,
      __unidad: m.unit,
    };
    // En modo valor cada eje se escala al MÁXIMO de los jugadores comparados.
    // Sin eso, un 1RM en kg (~150) aplasta un T10 en segundos (~1,7) y el
    // polígono se vuelve una púa. El número real va en el tooltip.
    const crudos = datos.players.map(
      (p) => (p.values?.[m.key]?.value ?? null));
    const tope = Math.max(...crudos.map((v) => v ?? 0), 0) || 1;
    datos.players.forEach((p, i) => {
      const e = pct?.[p.id]?.[m.key];
      const crudo = crudos[i];
      fila[`p${i}`] = porPercentil
        ? (e?.pct ?? null)
        : (crudo === null ? null : Math.round((crudo / tope) * 100));
      fila[`p${i}__valor`] = crudo;
      fila[`p${i}__pct`] = e?.pct ?? null;
      fila[`p${i}__n`] = e?.n ?? 0;
    });
    return fila;
  }), [metricas, datos.players, pct, porPercentil]);

  if (metricas.length === 0) {
    return <p className={styles.vacio}>Configurá las métricas de esta sección.</p>;
  }
  if (metricas.length < 3) {
    // Con menos de tres ejes el polígono degenera en una línea y engaña.
    return (
      <p className={styles.vacio}>
        El radar necesita al menos 3 métricas — hay {metricas.length}.
      </p>
    );
  }

  return (
    <section className={styles.centro}>
      <div className={styles.switchRow}>
        <div className={styles.segmented} role="tablist" aria-label="Escala del radar">
          <button type="button" role="tab" aria-selected={modo === "percentil"}
            className={modo === "percentil" ? styles.segOn : styles.seg}
            disabled={!pct}
            onClick={() => setModo("percentil")}>Percentil</button>
          <button type="button" role="tab" aria-selected={modo === "valor"}
            className={modo === "valor" ? styles.segOn : styles.seg}
            onClick={() => setModo("valor")}>Valor</button>
        </div>
      </div>

      <p className={styles.radarLeyenda}>
        {porPercentil ? (
          <>
            Cada eje es el{" "}
            <strong>percentil del jugador dentro de su categoría</strong>, no el
            valor. Más lejos del centro es mejor en todos los ejes.
          </>
        ) : (
          <>
            Cada eje es el <strong>valor</strong>, escalado al máximo de los
            jugadores comparados — las unidades no comparten escala, así que sin
            eso una métrica aplastaría a las demás. ⚠️ Acá{" "}
            <strong>más lejos del centro NO siempre es mejor</strong>: en las
            métricas marcadas ↓ el valor bueno es el bajo.
          </>
        )}
        {" "}<span className={styles.flecha}>↑</span> la métrica mejora cuando el
        valor sube · <span className={styles.flecha}>↓</span> mejora cuando baja.
      </p>

      <div className={styles.chartArea}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={filas} outerRadius="72%">
            <PolarGrid stroke="#e5e7eb" />
            <PolarAngleAxis dataKey="eje" tick={{ fontSize: 10, fill: "#475467" }} />
            <PolarRadiusAxis domain={[0, 100]} tickCount={5}
              tick={{ fontSize: 9, fill: "#98a2b3" }} angle={90} />
            <Tooltip content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const fila = payload[0]?.payload as Record<string, unknown>;
              return (
                <div className={styles.tooltip}>
                  <strong>{String(fila.eje)}</strong>
                  {datos.players.map((p, i) => {
                    const valor = fila[`p${i}__valor`] as number | null;
                    const percentil = fila[`p${i}__pct`] as number | null;
                    const n = fila[`p${i}__n`] as number;
                    return (
                      <div key={p.id} style={{ color: colorDe(i) }}>
                        {p.name}:{" "}
                        {valor === null ? "sin dato"
                          : `${fmt(valor)} ${String(fila.__unidad ?? "")}`.trim()}
                        {percentil !== null && (
                          <span className={styles.n}> · pct {percentil} de {n}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            }} />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={8} />
            {datos.players.map((p, i) => (
              <RadarSerie key={p.id} name={p.name} dataKey={`p${i}`}
                stroke={colorDe(i)} fill={colorDe(i)} fillOpacity={0.14}
                strokeWidth={2} isAnimationActive={false} />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

/* ── tarjeta ─────────────────────────────────────────────────────────── */

function PlayerCard({
  player, metrics, color, benchmark,
}: {
  player: ComparisonPlayer;
  metrics: ComparisonMetric[];
  color: string;
  benchmark: PlayerComparisonPayload["benchmark"];
}) {
  const linea = player.line ? benchmark[player.line] : undefined;
  return (
    <article className={styles.card} style={{ borderTopColor: color }}>
      <div className={styles.avatarWrap}>
        {player.photo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={player.photo_url} alt="" className={styles.avatar} />
        ) : (
          // Hoy es el caso de los 445 del formativo: un monograma dice quién
          // es; un ícono de imagen rota sólo dice que algo falló.
          <div className={styles.avatarFallback} style={{ background: color }}
            aria-hidden="true">{iniciales(player.name)}</div>
        )}
      </div>
      <h2 className={styles.cardName}>{player.name}</h2>
      <p className={styles.cardMeta}>
        {[player.category, player.position].filter(Boolean).join(" · ") || "—"}
      </p>
      {player.line && (
        <p className={styles.cardLine}>
          Línea {player.line}
          {linea ? ` · ${linea.line_size} en Primer Equipo` : ""}
        </p>
      )}
      <dl className={styles.cardMetrics}>
        {metrics.map((m) => {
          const v = player.values[m.key];
          const etiqueta = player.band_labels?.[m.key] ?? null;
          const colorBanda = etiqueta
            ? (player.bands?.[m.key] ?? []).find((b) => b.label === etiqueta)?.color
            : undefined;
          return (
            <div key={m.key} className={styles.cardMetric}>
              <dt className={styles.cardMetricLabel}>{m.label}</dt>
              <dd className={styles.cardMetricValue}>
                {v ? fmt(v.value) : <span className={styles.nulo}>sin dato</span>}
                {v && m.unit ? <span className={styles.unidad}> {m.unit}</span> : null}
                {/* La banda de SU categoría, no una compartida: 41,89 cm de
                    CMJ no significan lo mismo en Sub 20 que en Sub 13. */}
                {etiqueta && (
                  <span className={styles.banda}
                    style={{ background: colorBanda ?? "#94a3b8" }}>
                    {etiqueta}
                  </span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </article>
  );
}

/** Métricas agrupadas por examen, conservando el orden en que vienen — que es
 *  el del selector. Lo comparten la tabla y los gráficos a propósito: si cada
 *  uno agrupara por su cuenta, el mismo conjunto de métricas podría salir en
 *  dos órdenes distintos según dónde lo mires. */
function agruparPorExamen(
  metrics: ComparisonMetric[],
): [string, ComparisonMetric[]][] {
  const out = new Map<string, ComparisonMetric[]>();
  for (const m of metrics) {
    const lista = out.get(m.template_label) ?? [];
    lista.push(m);
    out.set(m.template_label, lista);
  }
  return [...out.entries()];
}

/* ── tabla comparativa ───────────────────────────────────────────────── */

function ComparisonTable({
  datos, colorDe,
}: { datos: PlayerComparisonPayload; colorDe: (i: number) => string }) {
  // Por qué puede no haber referencia — y son tres motivos distintos que el
  // lector necesita distinguir. Hoy 91 jugadores activos del club no tienen
  // posición cargada (las Series 2016/2017/2018 enteras), y decirles "líneas
  // distintas" mandaría a buscar un problema que no existe.
  const { linea, motivo } = useMemo(() => {
    if (datos.players.some((p) => !p.line)) {
      return { linea: null, motivo: "sin posición cargada" };
    }
    const lineas = new Set(datos.players.map((p) => p.line));
    if (lineas.size > 1) return { linea: null, motivo: "líneas distintas" };
    return { linea: datos.players[0].line, motivo: "sin dato" };
  }, [datos.players]);

  const grupos = useMemo(
    () => agruparPorExamen(datos.metrics), [datos.metrics]);
  // Métrica + los jugadores + la columna de referencia.
  const columnas = datos.players.length + 2;

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Métrica</th>
            {datos.players.map((p, i) => (
              <th key={p.id} style={{ color: colorDe(i) }}>{p.name}</th>
            ))}
            <th>Primer Equipo</th>
          </tr>
        </thead>
        {grupos.map(([examen, metricas]) => (
          // Un <tbody> por examen en vez de filas sueltas: el agrupamiento es
          // real en el marcado, no sólo una fila que parece un título.
          <tbody key={examen}>
            <tr>
              <th scope="colgroup" colSpan={columnas} className={styles.grupoFila}>
                {examen}
              </th>
            </tr>
            {metricas.map((m) => {
            const valores = datos.players.map((p) => p.values[m.key]?.value ?? null);
            const mejor = mejorIndice(valores, m.direction_of_good);
            const ref = linea ? datos.benchmark[linea]?.metrics[m.key] : undefined;
            return (
              <tr key={m.key}>
                <th scope="row" className={styles.rowHead}>
                  {m.label}
                  {m.unit && <span className={styles.unidad}> ({m.unit})</span>}
                </th>
                {valores.map((v, i) => {
                  const jugador = datos.players[i];
                  const etiqueta = jugador.band_labels?.[m.key] ?? null;
                  const color = etiqueta
                    ? (jugador.bands?.[m.key] ?? [])
                        .find((b) => b.label === etiqueta)?.color
                    : undefined;
                  return (
                    <td key={jugador.id}
                      className={i === mejor ? styles.mejor : undefined}>
                      {v === null ? <span className={styles.nulo}>—</span> : fmt(v)}
                      {etiqueta && (
                        <span className={styles.banda}
                          style={{ background: color ?? "#94a3b8" }}>
                          {etiqueta}
                        </span>
                      )}
                    </td>
                  );
                })}
                <td className={styles.refCell}>
                  {ref?.mean !== null && ref?.mean !== undefined ? (
                    <>
                      {fmt(ref.mean)}
                      {/* La `n` va SIEMPRE pegada a la media: la línea de
                          arqueros son dos personas y eso no se puede leer
                          igual que una media de diez. */}
                      <span className={styles.n}> · n={ref.n}</span>
                    </>
                  ) : (
                    <span className={styles.nulo}>{motivo}</span>
                  )}
                </td>
              </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </div>
  );
}

/* ── un gráfico por métrica, agrupados por examen ─────────────────────── */

/**
 * Una sección por examen y, dentro, un gráfico por métrica apilados hacia
 * abajo. Reemplaza al selector de una métrica por vez: comparar dos jugadores
 * es una lectura de barrido —se mira la forma de varias curvas seguidas— y
 * obligar a un clic por métrica rompía esa lectura.
 *
 * El agrupado sale de `template_label` conservando el orden en que vienen las
 * métricas, que es el del selector: así lo que el usuario marca arriba es lo
 * que aparece abajo, en el mismo orden.
 */
function GraficosPorExamen({
  datos, colorDe, origen, lesiones,
}: {
  datos: PlayerComparisonPayload;
  colorDe: (i: number) => string;
  origen: Origen;
  lesiones: InjuryRange[];
}) {
  const grupos = useMemo(
    () => agruparPorExamen(datos.metrics), [datos.metrics]);

  if (grupos.length === 0) {
    return <p className={styles.vacio}>Elegí al menos una métrica.</p>;
  }

  return (
    <div className={styles.grupos}>
      {grupos.map(([examen, metricas]) => (
        <section key={examen} className={styles.grupo}>
          <h3 className={styles.grupoTitulo}>{examen}</h3>
          <div className={styles.grupoGraficos}>
            {metricas.map((m) => (
              <Evolucion key={m.key} datos={datos} colorDe={colorDe}
                metrica={m} origen={origen} lesiones={lesiones} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/* ── gráfico: evolución con eje relativo ─────────────────────────────── */

function Evolucion({
  datos, colorDe, metrica, origen, lesiones,
}: {
  datos: PlayerComparisonPayload;
  colorDe: (i: number) => string;
  metrica: ComparisonMetric | undefined;
  origen: Origen;
  lesiones: InjuryRange[];
}) {
  const sinEdad = origen === "edad"
    && datos.players.some((p) => !p.date_of_birth);

  // Cada serie lleva su propia x: no hay filas compartidas, porque compartir
  // filas es exactamente lo que obliga a que las fechas calcen. Recharts
  // dibuja varias `Line` con su propio `data` mientras el eje X sea numérico.
  const series = useMemo(() => {
    if (!metrica) return [];
    return datos.players.map((p, i) => {
      const puntos = p.series[metrica.key] ?? [];
      if (puntos.length === 0) return { player: p, color: colorDe(i), data: [], xDe: null };
      const cero = new Date(puntos[0].recorded_at).getTime();
      const nacimiento = p.date_of_birth
        ? new Date(p.date_of_birth).getTime() : null;
      // La x de ESTE jugador: la misma transformación sirve para sus puntos y
      // para sus lesiones, que es lo que hace caer el marcador bajo su curva.
      const xDe = (t: number) => origen === "edad" && nacimiento !== null
        ? (t - nacimiento) / (1000 * 60 * 60 * 24 * 365.25)   // años
        : (t - cero) / (1000 * 60 * 60 * 24);                 // días
      const data = puntos.map((pt) => {
        const t = new Date(pt.recorded_at).getTime();
        const x = xDe(t);
        // La fecha viaja con el punto: el eje es RELATIVO (días desde el
        // primer registro, o edad), así que sin esto no hay forma de saber
        // cuándo pasó lo que se está mirando.
        return { x: Number(x.toFixed(2)), y: pt.value, fecha: pt.recorded_at };
      });
      return { player: p, color: colorDe(i), data, xDe };
    });
  }, [datos, metrica, origen, colorDe]);

  // Los hooks van ANTES de cualquier return: si `metrica` se vuelve undefined
  // al cambiar de pestaña, un useMemo colgado después del early-return cambia
  // la cantidad de hooks entre renders y React tira.
  const dominio = useMemo(() => {
    const xs = series.flatMap((s) => s.data.map((d) => d.x));
    return xs.length ? [Math.min(...xs), Math.max(...xs)] as [number, number]
      : undefined;
  }, [series]);

  // Cada lesión en la x de su jugador. Sólo los jugadores con curva en esta
  // métrica: sin puntos no hay eje propio donde ubicarla.
  const marcadores = useMemo<RailMarker[]>(() => {
    const out: RailMarker[] = [];
    for (const s of series) {
      if (!s.xDe) continue;
      for (const l of lesiones) {
        if (l.player_id !== s.player.id) continue;
        const t0 = Date.parse(`${isoDay(l.started_at)}T00:00:00`);
        out.push({
          injury: l, color: s.color, x1: s.xDe(t0),
          x2: l.ended_at ? s.xDe(Date.parse(`${isoDay(l.ended_at)}T00:00:00`)) : null,
        });
      }
    }
    return out;
  }, [series, lesiones]);

  if (!metrica) return <p className={styles.vacio}>Elegí una métrica.</p>;

  const lineas = new Set(datos.players.map((p) => p.line));
  const linea = lineas.size === 1 ? datos.players[0].line : null;
  const ref = linea ? datos.benchmark[linea]?.metrics[metrica.key] : undefined;

  // Las bandas SÓLO cuando todos comparten categoría. Con jugadores de
  // divisiones distintas cada uno tiene su propia escala, y pintar una sola
  // franja detrás de las dos curvas mediría a uno con la vara del otro — que
  // es exactamente lo que las bandas por categoría vinieron a evitar, y encima
  // se vería perfectamente normal.
  const categorias = new Set(datos.players.map((p) => p.category));
  const mismaCategoria = categorias.size === 1;
  const bandas = mismaCategoria
    ? datos.players[0].bands?.[metrica.key] : undefined;

  return (
    <div>
      {/* El título va acá porque ya no hay selector de métrica: con N gráficos
          apilados, la etiqueta del eje Y sola obliga a leer de costado para
          saber qué se está mirando. */}
      <h4 className={styles.graficoTitulo}>
        {metrica.label}
        {metrica.unit && <span className={styles.unidad}> ({metrica.unit})</span>}
      </h4>
      {!mismaCategoria && (datos.players[0].bands?.[metrica.key]?.length ?? 0) > 0 && (
        <p className={styles.notaBandas}>
          Sin bandas: los jugadores son de categorías distintas y cada una tiene
          su propia escala. Los nombres de banda siguen en la tabla, donde cada
          valor se mide con la suya.
        </p>
      )}
      {sinEdad && (
        <p className={styles.aviso}>
          Falta la fecha de nacimiento de algún jugador: su curva se dibuja
          desde su primer registro.
        </p>
      )}
      <div className={styles.chartArea}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart margin={{ top: 8, right: 64, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            {referenceBandAreas(bandas, dominio)}
            {/* El inicio de cada lesión, tenue y en el color de su jugador: une
                el marcador de abajo con el punto de la curva. */}
            {marcadores.map((m) => (
              <ReferenceLine key={`les-${m.injury.id}`} x={m.x1} stroke={m.color}
                strokeOpacity={0.45} strokeDasharray="2 3" ifOverflow="hidden" />
            ))}
            <XAxis
              type="number" dataKey="x" domain={dominio ?? ["auto", "auto"]}
              tick={{ fontSize: 11, fill: "#6b7280" }} stroke="#d1d5db"
              height={44}
              label={{
                value: origen === "edad" ? "Edad (años)"
                  : "Días desde el primer registro",
                position: "insideBottom", offset: 0,
                style: { fill: "#6b7280", fontSize: 11, fontWeight: 600 },
              }} />
            <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} stroke="#d1d5db"
              width={64}
              label={{
                value: metrica.unit || "",
                angle: -90, position: "insideLeft", offset: 8,
                style: { textAnchor: "middle", fill: "#6b7280", fontSize: 11, fontWeight: 600 },
              }} />
            <Tooltip content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              return (
                <div className={styles.tooltip}>
                  {payload.map((s) => (
                    <div key={String(s.name)} style={{ color: s.color }}>
                      <span className={styles.tooltipNombre}>{String(s.name)}</span>
                      {" "}{fmt(Number(s.value))} {metrica.unit}
                      {(s.payload as { fecha?: string })?.fecha && (
                        <span className={styles.tooltipFecha}>
                          {" · "}{fechaCorta((s.payload as { fecha: string }).fecha)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              );
            }} />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={8} />
            {ref?.mean != null && (
              <ReferenceLine y={ref.mean} stroke="#7c3aed" strokeDasharray="5 4"
                label={{
                  value: `Primer Equipo ${fmt(ref.mean)} (n=${ref.n})`,
                  position: "right", fill: "#7c3aed", fontSize: 10, fontWeight: 600,
                }} />
            )}
            {series.map((s) => (
              <Line key={s.player.id} type="monotone" data={s.data}
                dataKey="y" name={s.player.name} stroke={s.color}
                strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false}
                connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <InjuryRail markers={marcadores} domain={dominio} />
    </div>
  );
}

/* ── selectores auxiliares ───────────────────────────────────────────── */

function MetricPicker({
  metricas, claves, onChange,
}: {
  metricas: ComparisonMetric[];
  claves: string[];
  onChange: (k: string[]) => void;
}) {
  const porPlantilla = useMemo(() => {
    const out = new Map<string, ComparisonMetric[]>();
    for (const m of metricas) {
      const lista = out.get(m.template_label) ?? [];
      lista.push(m);
      out.set(m.template_label, lista);
    }
    return [...out.entries()];
  }, [metricas]);

  const alternar = (k: string) =>
    onChange(claves.includes(k) ? claves.filter((x) => x !== k) : [...claves, k]);

  return (
    <details className={styles.metricPicker}>
      <summary className={styles.metricSummary}>
        Métricas ({claves.length} de {metricas.length})
      </summary>
      <div className={styles.metricGroups}>
        {porPlantilla.map(([plantilla, lista]) => (
          <div key={plantilla} className={styles.metricGroup}>
            <h3 className={styles.metricGroupTitle}>{plantilla}</h3>
            <div className={styles.metricChips}>
              {lista.map((m) => (
                <button key={m.key} type="button"
                  className={claves.includes(m.key) ? styles.chipOn : styles.chip}
                  aria-pressed={claves.includes(m.key)}
                  onClick={() => alternar(m.key)}>{m.label}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────── */

/** `2026-09-12T…` → `12 sep 2026`. El año va siempre: el comparador cruza
 *  temporadas, así que "12 sep" a secas sería ambiguo. */
function fechaCorta(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("es-CL", {
    day: "numeric", month: "short", year: "numeric",
  });
}

/** El rango como query string. El control ya trae los presets y el tope de dos
 *  años; acá sólo se traduce a lo que el endpoint espera. */
/** The date range as days, for the injury indicators (`ventana` builds the query). */
function periodo(r: DateRangeValue): { desde: string | null; hasta: string; periodoLabel: string } {
  const hoy = new Date().toISOString().slice(0, 10);
  if (r.preset === "custom") {
    return {
      desde: r.date.from || null, hasta: r.date.to || hoy,
      periodoLabel: r.date.from ? `${fechaCorta(r.date.from)} – ${fechaCorta(r.date.to || hoy)}` : "Período",
    };
  }
  const dias = Number(r.preset);
  const desde = new Date();
  desde.setDate(desde.getDate() - dias);
  return {
    desde: desde.toISOString().slice(0, 10), hasta: hoy,
    periodoLabel: dias >= 365 && dias % 365 === 0
      ? `Últimos ${dias / 365 === 1 ? "12 meses" : `${dias / 365} años`}` : `Últimos ${dias} días`,
  };
}

function ventana(r: DateRangeValue): string {
  if (r.preset === "custom") {
    return (r.date.from ? `&date_from=${r.date.from}` : "")
      + (r.date.to ? `&date_to=${r.date.to}` : "");
  }
  const dias = Number(r.preset);
  if (!Number.isFinite(dias)) return "";
  const desde = new Date();
  desde.setDate(desde.getDate() - dias);
  return `&date_from=${desde.toISOString().slice(0, 10)}`;
}

function fmt(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function iniciales(nombre: string): string {
  return nombre.split(/\s+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "").join("");
}

/** Índice del mejor valor según la dirección de la métrica, o -1.
 *  `neutral` no tiene ganador: resaltar uno sería afirmar algo que la métrica
 *  no dice. */
function mejorIndice(
  valores: (number | null)[], direccion: ComparisonMetric["direction_of_good"],
): number {
  if (direccion === "neutral") return -1;
  let mejor = -1;
  valores.forEach((v, i) => {
    if (v === null) return;
    if (mejor === -1) { mejor = i; return; }
    const actual = valores[mejor] as number;
    if (direccion === "up" ? v > actual : v < actual) mejor = i;
  });
  return mejor;
}
