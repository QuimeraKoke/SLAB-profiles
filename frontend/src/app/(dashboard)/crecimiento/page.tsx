"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Info, TrendingUp } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import styles from "./page.module.css";

/** Maduración y crecimiento.
 *
 *  A parallel module to /desarrollo rather than a section inside it, because it
 *  answers a different question: that page asks "does he play above his age
 *  group?", this one asks "where is he in his growth?". Together they answer the
 *  objection neither can alone — a boy playing up may just be maturing earlier,
 *  and a late maturer holding his own may be the best prospect in the group.
 *
 *  Two things the UI has to be honest about, both measured (PRD §9.4):
 *   · The early/late classification compares each player to peers of HIS OWN
 *     AGE, never to a fixed threshold, because Mirwald's estimate drifts +1.19
 *     years between ages 10 and 17 while individual spread is only ~0.55.
 *   · Maturity bands stop being informative above SUB-15, where everyone is past
 *     the growth peak. The table says so per team instead of implying otherwise.
 */

interface Band {
  key: string;
  label: string;
}
interface TeamRow {
  team: string | null;
  players: number;
  counts: Record<string, number>;
  bands_occupied: number;
  informative: boolean;
  still_growing: number;
}
interface Suggestion {
  team: string;
  median_offset: number;
  own_median_offset: number;
  gain_years: number;
  direction: "up" | "down";
}
interface PlayerRow {
  player_id: string;
  player_name: string;
  team: string | null;
  birth_year: number;
  measured_on: string;
  age_years: number;
  offset_years: number;
  aphv_years: number;
  stage: string;
  stage_label: string;
  band: string;
  band_label: string;
  confident: boolean;
  timing: "early" | "on_time" | "late" | null;
  timing_label: string | null;
  timing_z: number | null;
  velocity_cm_year: number | null;
  velocity_provisional: boolean | null;
  velocity_days: number | null;
  female: boolean;
  suggestion: Suggestion | null;
  cohort_year: number;
  cohort_label: string;
}
interface Cohort {
  cohort_year: number;
  label: string;
  players: number;
}
interface Payload {
  players: PlayerRow[];
  season: number;
  seasons: number[];
  cohorts: Cohort[];
  bands: Band[];
  teams: TeamRow[];
  skipped: Record<string, number>;
  notes: {
    min_timing_peers: number;
    valid_age: [number, number];
    velocity_min_days: number;
    velocity_confident_days: number;
  };
}

const TIMING_CLASS: Record<string, string> = {
  early: styles.early,
  late: styles.late,
  on_time: styles.onTime,
};

/** ≥3 cm/year is the threshold the backend counts as "still growing" — the point
 *  at which training load is worth revisiting. */
const GROWING_CM = 3.0;

/** Table filters. Each is a question a coach actually asks, and each one the
 *  data can answer without inventing anything. `sube`/`baja` read off the
 *  maturity RESEMBLANCE, not a recommendation — see `suggest_team`. */
const FILTERS: { key: string; label: string; hint: string }[] = [
  { key: "", label: "Todos", hint: "Todos los jugadores con medición utilizable" },
  {
    key: "desalineados",
    label: "Desalineados",
    hint: "Su madurez se parece más a la de otro plantel que a la del propio",
  },
  {
    key: "sube",
    label: "Se parecen a un grupo mayor",
    hint: "Su madurez está por delante de la mediana de su plantel",
  },
  {
    key: "baja",
    label: "Se parecen a un grupo menor",
    hint: "Su madurez está por detrás de la mediana de su plantel",
  },
  {
    key: "temprano",
    label: "Maduración temprana",
    hint: "Adelantados respecto a los jugadores de su misma edad",
  },
  {
    key: "tardio",
    label: "Maduración tardía",
    hint: "Atrasados respecto a los jugadores de su misma edad",
  },
  {
    key: "estiron",
    label: "En pleno estirón",
    hint: `Creciendo ${GROWING_CM} cm/año o más: momento de revisar la carga`,
  },
];

function matchesFilter(p: PlayerRow, key: string): boolean {
  switch (key) {
    case "desalineados":
      return p.suggestion !== null;
    case "sube":
      return p.suggestion?.direction === "up";
    case "baja":
      return p.suggestion?.direction === "down";
    case "temprano":
      return p.timing === "early";
    case "tardio":
      return p.timing === "late";
    case "estiron":
      return (p.velocity_cm_year ?? 0) >= GROWING_CM;
    default:
      return true;
  }
}

function CrecimientoContent() {
  const router = useRouter();
  const params = useSearchParams();

  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settled, setSettled] = useState(false);

  const teamFilter = params.get("equipo") ?? "";
  const situacion = params.get("situacion") ?? "";
  // Sin `?temporada=` el backend usa el año en curso, que es lo que se quiere ver
  // por defecto; el selector sólo hace explícito lo que ya estaba pasando.
  const seasonParam = params.get("temporada") ?? "";

  const setParam = useCallback(
    (key: string, next: string) => {
      const qs = new URLSearchParams(Array.from(params.entries()));
      if (next) qs.set(key, next);
      else qs.delete(key);
      router.replace(qs.toString() ? `?${qs.toString()}` : "?", { scroll: false });
    },
    [params, router],
  );

  const setSituacion = useCallback(
    (next: string) => {
      const qs = new URLSearchParams(Array.from(params.entries()));
      if (next) qs.set("situacion", next);
      else qs.delete("situacion");
      router.replace(qs.toString() ? `?${qs.toString()}` : "?", { scroll: false });
    },
    [params, router],
  );

  const setTeam = useCallback(
    (next: string) => {
      const qs = new URLSearchParams(Array.from(params.entries()));
      if (next) qs.set("equipo", next);
      else qs.delete("equipo");
      router.replace(qs.toString() ? `?${qs.toString()}` : "?", { scroll: false });
    },
    [params, router],
  );

  const cohortParam = params.get("cohorte") ?? "";

  useEffect(() => {
    let cancelled = false;
    const qs = new URLSearchParams();
    if (seasonParam) qs.set("season", seasonParam);
    if (cohortParam) qs.set("cohort", cohortParam);
    api<Payload>(
      `/maturation/overview${qs.toString() ? `?${qs.toString()}` : ""}`,
    )
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof ApiError ? e.message : "No se pudo cargar la maduración",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setSettled(true);
      });
    return () => {
      cancelled = true;
    };
  }, [seasonParam, cohortParam]);

  const teams = data?.teams ?? [];
  // Memoised because `?? []` allocates a fresh array every render, which would
  // invalidate the `byBand` memo below on each pass.
  const bands = useMemo(() => data?.bands ?? [], [data]);

  const shown = useMemo(
    () =>
      (data?.players ?? []).filter(
        (p) =>
          (!teamFilter || p.team === teamFilter)
          && matchesFilter(p, situacion),
      ),
    [data, teamFilter, situacion],
  );

  // Counts on the chips so an empty filter is visibly empty rather than looking
  // broken. Computed over the team-filtered set so they agree with what's shown.
  const counts = useMemo(() => {
    const base = (data?.players ?? []).filter(
      (p) => !teamFilter || p.team === teamFilter,
    );
    return Object.fromEntries(
      FILTERS.map((f) => [f.key, base.filter((p) => matchesFilter(p, f.key)).length]),
    ) as Record<string, number>;
  }, [data, teamFilter]);

  const byBand = useMemo(() => {
    const out = new Map<string, PlayerRow[]>();
    for (const b of bands) out.set(b.key, []);
    for (const p of shown) out.get(p.band)?.push(p);
    return out;
  }, [shown, bands]);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Maduración y crecimiento</h1>
          <p className={styles.subtitle}>
            En qué punto de su crecimiento está cada jugador, y quién madura
            antes o después que sus pares de la misma edad.
          </p>
        </div>
        {data && data.seasons.length > 0 && (
          /* A visible label, not just `aria-label`: bare year buttons give a
             sighted user nothing to go on. `aria-labelledby` points at the same
             words on screen so the accessible name and the visible one match. */
          <div className={styles.seasonPicker}>
            <span className={styles.seasonLabel} id="crecimiento-temporada">
              Temporada
            </span>
            <div
              className={styles.tabs}
              role="tablist"
              aria-labelledby="crecimiento-temporada"
            >
              {data.seasons.map((y) => (
                <button
                  key={y}
                  role="tab"
                  type="button"
                  aria-selected={y === data.season}
                  className={`${styles.tab} ${y === data.season ? styles.tabOn : ""}`}
                  onClick={() => setParam("temporada", String(y))}
                >
                  {y}
                </button>
              ))}
            </div>
          </div>
        )}
      </header>

      {data && data.cohorts.length > 0 && (
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>Equipo</h2>
          <p className={styles.note}>
            <Info size={12} aria-hidden="true" />
            <span>
              Un equipo es un <strong>año de nacimiento</strong>, que no cambia.
              La categoría en que compite sí — se deriva del año, así que los de
              2013 son <strong>Sub 12 en 2025</strong> y{" "}
              <strong>Sub 13 en 2026</strong>. Por eso el selector es por
              cohorte y no por etiqueta.
            </span>
          </p>
          <div className={styles.chips} role="group" aria-label="Cohorte">
            <button
              type="button"
              aria-pressed={cohortParam === ""}
              className={`${styles.chip} ${cohortParam === "" ? styles.chipOn : ""}`}
              onClick={() => setParam("cohorte", "")}
            >
              Todos
              <span className={styles.chipCount}>
                {data.cohorts.reduce((n, c) => n + c.players, 0)}
              </span>
            </button>
            {data.cohorts.map((c) => (
              <button
                key={c.cohort_year}
                type="button"
                title={`Nacidos en ${c.cohort_year} · en ${data.season} compiten en ${c.label}`}
                aria-pressed={cohortParam === String(c.cohort_year)}
                className={`${styles.chip} ${
                  cohortParam === String(c.cohort_year) ? styles.chipOn : ""
                }`}
                onClick={() => setParam("cohorte", String(c.cohort_year))}
              >
                {c.cohort_year}
                <span className={styles.chipLabel}>{c.label}</span>
                <span className={styles.chipCount}>{c.players}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
      {!settled && <p className={styles.empty}>Cargando…</p>}

      {data && (
        <>
          <section className={styles.card}>
            <h2 className={styles.cardTitle}>Por equipo</h2>
            <p className={styles.note}>
              <Info size={12} aria-hidden="true" />
              <span>
                Las <strong>bandas de madurez</strong> agrupan por punto del
                crecimiento en vez de por año de nacimiento. Cuando un equipo cae
                entero en una sola banda, la agrupación no aporta nada que no
                dijera ya su edad — pasa de SUB-16 hacia arriba, donde todos
                superaron el pico.
              </span>
            </p>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Equipo</th>
                    <th className={styles.num}>Jugadores</th>
                    {bands.map((b) => (
                      <th key={b.key} className={styles.num}>
                        {b.label}
                      </th>
                    ))}
                    <th className={styles.num}>Creciendo</th>
                    <th>Bandas</th>
                  </tr>
                </thead>
                <tbody>
                  {teams.map((t) => (
                    <tr
                      key={t.team ?? "—"}
                      className={teamFilter === t.team ? styles.rowOn : ""}
                    >
                      <td>
                        <button
                          type="button"
                          className={styles.linkBtn}
                          onClick={() => setTeam(teamFilter === t.team ? "" : t.team ?? "")}
                          aria-pressed={teamFilter === t.team}
                        >
                          {t.team}
                        </button>
                      </td>
                      <td className={styles.num}>{t.players}</td>
                      {bands.map((b) => (
                        <td key={b.key} className={styles.num}>
                          {t.counts[b.key] ? (
                            t.counts[b.key]
                          ) : (
                            <span className={styles.muted}>·</span>
                          )}
                        </td>
                      ))}
                      <td className={styles.num}>
                        {t.still_growing > 0 ? (
                          <span className={styles.growing}>
                            <TrendingUp size={11} aria-hidden="true" />
                            {t.still_growing}
                          </span>
                        ) : (
                          <span className={styles.muted}>·</span>
                        )}
                      </td>
                      <td>
                        {t.informative ? (
                          <span className={styles.pillOk}>
                            {t.bands_occupied} bandas
                          </span>
                        ) : (
                          <span className={styles.muted}>homogéneo</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className={styles.note}>
              <Info size={12} aria-hidden="true" />
              <span>
                <strong>Creciendo</strong> = al menos {GROWING_CM} cm/año, el
                punto donde vale la pena revisar la carga de entrenamiento.
              </span>
            </p>
          </section>

          <section className={styles.card}>
            <h2 className={styles.cardTitle}>
              Jugadores
              {teamFilter && (
                <button
                  type="button"
                  className={styles.clear}
                  onClick={() => setTeam("")}
                >
                  {teamFilter} ✕
                </button>
              )}
            </h2>
            <div className={styles.chips} role="group" aria-label="Filtrar jugadores">
              {FILTERS.map((f) => (
                <button
                  key={f.key || "todos"}
                  type="button"
                  title={f.hint}
                  aria-pressed={situacion === f.key}
                  disabled={counts[f.key] === 0 && f.key !== ""}
                  className={`${styles.chip} ${
                    situacion === f.key ? styles.chipOn : ""
                  }`}
                  onClick={() => setSituacion(situacion === f.key ? "" : f.key)}
                >
                  {f.label}
                  <span className={styles.chipCount}>{counts[f.key] ?? 0}</span>
                </button>
              ))}
            </div>

            <p className={styles.note}>
              <Info size={12} aria-hidden="true" />
              <span>
                <strong>Temprano / tardío</strong> se decide comparando contra
                jugadores de <strong>la misma edad</strong>, no contra un valor
                de referencia fijo: la estimación se corre con la edad, así que un
                umbral constante mediría sobre todo cuántos años tiene el chico.
                Con menos de {data.notes.min_timing_peers} pares no se clasifica.
              </span>
            </p>
            <p className={styles.note}>
              <Info size={12} aria-hidden="true" />
              <span>
                La columna <strong>Se parece a</strong> dice a qué plantel se
                parece su madurez, no a cuál debería ir. Agrupar por madurez
                sirve tanto para que el que va adelantado enfrente rivales
                parejos y tenga que resolver con técnica, como para que el
                atrasado juegue sin estar en desventaja física — cuál de las dos
                cosas conviene es una decisión del cuerpo técnico.
              </span>
            </p>

            {shown.length === 0 && (
              <p className={styles.empty}>Sin mediciones utilizables.</p>
            )}

            {bands.map((b) => {
              const rows = byBand.get(b.key) ?? [];
              if (rows.length === 0) return null;
              return (
                <div key={b.key} className={styles.group}>
                  <h3 className={styles.groupTitle}>
                    {b.label}
                    <span className={styles.count}>{rows.length}</span>
                  </h3>
                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Jugador</th>
                          <th>Cohorte</th>
                          <th>Plantel</th>
                          <th className={styles.num}>Edad</th>
                          <th className={styles.num}>Años del pico</th>
                          <th>Maduración</th>
                          <th className={styles.num}>Crecimiento</th>
                          <th>Se parece a</th>
                          <th>Medido</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((p) => (
                          <tr key={p.player_id}>
                            <td className={styles.strong}>{p.player_name}</td>
                            <td>
                              {p.cohort_year}
                              <span className={styles.derived}>
                                {p.cohort_label}
                              </span>
                            </td>
                            <td className={styles.muted}>{p.team}</td>
                            <td className={styles.num}>
                              {p.age_years.toFixed(1)}
                            </td>
                            <td className={styles.num}>
                              {p.offset_years > 0 ? "+" : ""}
                              {p.offset_years.toFixed(2)}
                              {!p.confident && (
                                <span
                                  className={styles.muted}
                                  title="Lejos del pico: la estimación pierde precisión"
                                >
                                  {" "}
                                  ~
                                </span>
                              )}
                            </td>
                            <td>
                              {p.timing ? (
                                <span className={TIMING_CLASS[p.timing]}>
                                  {p.timing_label}
                                </span>
                              ) : (
                                <span className={styles.muted}>
                                  sin referencia
                                </span>
                              )}
                            </td>
                            <td className={styles.num}>
                              {p.velocity_cm_year === null ? (
                                <span className={styles.muted}>—</span>
                              ) : (
                                <>
                                  <span
                                    className={
                                      p.velocity_cm_year >= GROWING_CM
                                        ? styles.growing
                                        : undefined
                                    }
                                  >
                                    {p.velocity_cm_year} cm/a
                                  </span>
                                  {p.velocity_provisional && (
                                    <span
                                      className={styles.muted}
                                      title={`Intervalo de ${p.velocity_days} días: menos de un año, así que es provisional`}
                                    >
                                      {" "}
                                      prov.
                                    </span>
                                  )}
                                </>
                              )}
                            </td>
                            <td>
                              {p.suggestion ? (
                                <span
                                  className={
                                    p.suggestion.direction === "up"
                                      ? styles.sugUp
                                      : styles.sugDown
                                  }
                                  title={`Su madurez (${p.offset_years.toFixed(2)}) está más cerca de la mediana de ${p.suggestion.team} (${p.suggestion.median_offset.toFixed(2)}) que de la de su propio plantel (${p.suggestion.own_median_offset.toFixed(2)}), por ${p.suggestion.gain_years.toFixed(2)} años`}
                                >
                                  {p.suggestion.direction === "up" ? "↑" : "↓"}{" "}
                                  {p.suggestion.team}
                                </span>
                              ) : (
                                <span className={styles.muted}>su plantel</span>
                              )}
                            </td>
                            <td className={styles.muted}>{p.measured_on}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </section>
        </>
      )}
    </div>
  );
}

/** `useSearchParams` needs a Suspense boundary or the production build fails
 *  with "Missing Suspense boundary with useSearchParams" — and in development
 *  the problem is invisible because routes render on demand. */
export default function CrecimientoPage() {
  return (
    <Suspense fallback={<p className={styles.empty}>Cargando…</p>}>
      <CrecimientoContent />
    </Suspense>
  );
}
