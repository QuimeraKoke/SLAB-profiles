"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowUp, ArrowDown, Info, Minus, Star } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useCategoryContext } from "@/context/CategoryContext";
import styles from "./page.module.css";

/** Desarrollo por cohorte.
 *
 *  Makes visible the distinction the cohort model introduced, which no single
 *  label can carry: the EQUIPO is the durable group of people (identified by
 *  birth year) and the CATEGORÍA DE COMPETENCIA is where that group plays this
 *  season. This club's team labels are a frozen 2025 snapshot, so showing only
 *  the name is actively misleading — the team called SUB-11 competes in Sub 12.
 *
 *  The season lives in the URL (`?temporada=`) per IA principle 2, so a finding
 *  worth sharing is a link.
 */

interface TeamSeason {
  season: number;
  bracket: string;
  bracket_order: number;
  derived: boolean;
}
interface Team {
  id: string;
  name: string;
  cohort_year: number | null;
  is_age_group: boolean;
  seasons: TeamSeason[];
}
interface TeamsPayload {
  teams: Team[];
  seasons: number[];
}

type Status =
  | "muy_por_encima"
  | "por_encima"
  | "su_cohorte"
  | "por_debajo"
  | "sin_datos";

interface DevRow {
  player_id: string;
  player_name: string;
  birth_year: number | null;
  team: string | null;
  season: number;
  played_bracket: string | null;
  natural_bracket: string | null;
  appearances: number;
  appearances_total: number;
  rungs_above: number | null;
  status: Status;
  status_label: string;
}
interface DevPayload {
  seasons: number[];
  summary: {
    total: number;
    judged: number;
    counts: { status: Status; label: string; players: number }[];
    standouts: DevRow[];
  };
  rows: DevRow[];
}

interface Fixture {
  event_id: string;
  title: string;
  starts_at: string;
  bracket: string | null;
  competition: string | null;
  round: string | null;
  is_home: boolean | null;
  opponent: string | null;
  venue: string | null;
  layer: string;
  layer_label: string;
}
interface FixturesPayload {
  own_brackets: string[];
  likely_brackets: string[];
  counts: Record<string, number>;
  layers: { key: string; label: string; fixtures: Fixture[] }[];
}

const STATUS_ORDER: Status[] = [
  "muy_por_encima",
  "por_encima",
  "su_cohorte",
  "por_debajo",
  "sin_datos",
];

function StatusIcon({ status }: { status: Status }) {
  if (status === "muy_por_encima") return <Star size={13} aria-hidden="true" />;
  if (status === "por_encima") return <ArrowUp size={13} aria-hidden="true" />;
  if (status === "por_debajo") return <ArrowDown size={13} aria-hidden="true" />;
  return <Minus size={13} aria-hidden="true" />;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("es-CL", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
}

function DesarrolloContent() {
  const router = useRouter();
  const params = useSearchParams();
  const { categoryId } = useCategoryContext();

  const [teams, setTeams] = useState<TeamsPayload | null>(null);
  const [dev, setDev] = useState<DevPayload | null>(null);
  const [fixtures, setFixtures] = useState<FixturesPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Which season the loaded payload belongs to. Written only from the fetch
  // callbacks, so `loading` can be DERIVED instead of set synchronously inside
  // an effect (react-hooks/set-state-in-effect).
  const [settledSeason, setSettledSeason] = useState<number | null>(null);

  // The URL is the source of truth; fall back to the newest season the API
  // reports rather than to a hardcoded year, so a fresh club isn't empty.
  const seasonParam = params.get("temporada");
  const season = useMemo(() => {
    const n = seasonParam ? Number(seasonParam) : NaN;
    if (Number.isFinite(n)) return n;
    return teams?.seasons?.[0] ?? null;
  }, [seasonParam, teams]);

  const setSeason = useCallback(
    (next: number) => {
      const qs = new URLSearchParams(Array.from(params.entries()));
      qs.set("temporada", String(next));
      router.replace(`?${qs.toString()}`, { scroll: false });
    },
    [params, router],
  );

  useEffect(() => {
    let cancelled = false;
    api<TeamsPayload>("/teams")
      .then((d) => {
        if (!cancelled) setTeams(d);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "No se pudieron cargar los equipos");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (season == null) return;
    let cancelled = false;
    api<DevPayload>(`/development/cohorts?season=${season}`)
      .then((d) => {
        if (cancelled) return;
        setDev(d);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "No se pudo cargar el desarrollo");
      })
      .finally(() => {
        // Settled either way — an error must not leave the view spinning.
        if (!cancelled) setSettledSeason(season);
      });
    return () => {
      cancelled = true;
    };
  }, [season]);

  const loading = season != null && settledSeason !== season;

  useEffect(() => {
    if (!categoryId) return;
    let cancelled = false;
    api<FixturesPayload>(
      `/fixtures/upcoming?category_id=${categoryId}&include_context=false`,
    )
      .then((d) => {
        if (!cancelled) setFixtures(d);
      })
      .catch(() => {
        if (!cancelled) setFixtures(null);
      });
    return () => {
      cancelled = true;
    };
  }, [categoryId]);

  const grouped = useMemo(() => {
    const out = new Map<Status, DevRow[]>();
    for (const s of STATUS_ORDER) out.set(s, []);
    for (const r of dev?.rows ?? []) out.get(r.status)?.push(r);
    return out;
  }, [dev]);

  const seasons = teams?.seasons ?? dev?.seasons ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Desarrollo por cohorte</h1>
          <p className={styles.subtitle}>
            Quién juega por encima del grupo que le corresponde por edad.
          </p>
        </div>
        {seasons.length > 0 && (
          <div className={styles.tabs} role="tablist" aria-label="Temporada">
            {seasons.map((s) => (
              <button
                key={s}
                role="tab"
                type="button"
                aria-selected={s === season}
                className={`${styles.tab} ${s === season ? styles.tabOn : ""}`}
                onClick={() => setSeason(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </header>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {/* --- Equipo vs categoría de competencia -------------------------- */}
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>Equipos y su competencia</h2>
        <p className={styles.note}>
          <Info size={12} aria-hidden="true" /> El <strong>equipo</strong> es el
          grupo de jugadores y no cambia con los años; la{" "}
          <strong>categoría de competencia</strong> es dónde juega esa
          temporada. El nombre del equipo puede no coincidir con ella.
        </p>
        {teams === null ? (
          <p className={styles.empty}>Cargando…</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Equipo</th>
                  <th>Cohorte</th>
                  <th>Compite en {season}</th>
                </tr>
              </thead>
              <tbody>
                {teams.teams.map((t) => {
                  const ts = t.seasons.find((s) => s.season === season);
                  return (
                    <tr key={t.id}>
                      <td className={styles.strong}>{t.name}</td>
                      <td>
                        {t.cohort_year ?? (
                          <span className={styles.muted}>
                            varios años de nacimiento
                          </span>
                        )}
                      </td>
                      <td>
                        {ts ? (
                          <span className={styles.pill}>{ts.bracket}</span>
                        ) : (
                          <span className={styles.muted}>sin definir</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* --- Próximos partidos, por relevancia --------------------------- */}
      {fixtures && (
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>Próximos partidos</h2>
          <p className={styles.note}>
            <Info size={12} aria-hidden="true" /> Separados a propósito: lo que
            el equipo tiene comprometido no es lo mismo que aquello donde sus
            jugadores suelen aparecer.
          </p>
          {fixtures.layers
            .filter((l) => l.fixtures.length > 0)
            .map((layer) => (
              <div key={layer.key} className={styles.layer}>
                <h3 className={styles.layerTitle}>
                  {layer.label}
                  <span className={styles.count}>{layer.fixtures.length}</span>
                </h3>
                <ul className={styles.fixtures}>
                  {layer.fixtures.slice(0, 6).map((f) => (
                    <li key={f.event_id}>
                      <span className={styles.fxDate}>{fmtDate(f.starts_at)}</span>
                      <span className={styles.pillSm}>{f.bracket}</span>
                      <span className={styles.fxOpponent}>
                        {f.opponent || f.title}
                      </span>
                      <span className={styles.muted}>
                        {f.is_home === null ? "" : f.is_home ? "local" : "visita"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          {fixtures.layers.every((l) => l.fixtures.length === 0) && (
            <p className={styles.empty}>Sin partidos programados.</p>
          )}
        </section>
      )}

      {/* --- Desarrollo -------------------------------------------------- */}
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>Jugadores</h2>
        {loading && <p className={styles.empty}>Cargando…</p>}
        {!loading && dev && dev.rows.length === 0 && (
          <p className={styles.empty}>
            Sin partidos registrados en {season} para tus categorías.
          </p>
        )}
        {!loading && dev && dev.rows.length > 0 && (
          <>
            <ul className={styles.summary}>
              {dev.summary.counts.map((c) => (
                <li key={c.status} className={styles[`s_${c.status}`]}>
                  <StatusIcon status={c.status} />
                  <b>{c.players}</b> {c.label}
                </li>
              ))}
            </ul>

            {STATUS_ORDER.filter((s) => (grouped.get(s) ?? []).length > 0).map(
              (s) => (
                <div key={s} className={styles.group}>
                  <h3 className={`${styles.groupTitle} ${styles[`s_${s}`]}`}>
                    <StatusIcon status={s} />
                    {grouped.get(s)![0].status_label}
                    <span className={styles.count}>
                      {grouped.get(s)!.length}
                    </span>
                  </h3>
                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Jugador</th>
                          <th>Nacido</th>
                          <th>Equipo</th>
                          <th>Le corresponde</th>
                          <th>Jugó en</th>
                          <th className={styles.num}>Partidos</th>
                        </tr>
                      </thead>
                      <tbody>
                        {grouped.get(s)!.map((r) => (
                          <tr key={`${r.player_id}-${r.season}`}>
                            <td className={styles.strong}>{r.player_name}</td>
                            <td>{r.birth_year ?? "—"}</td>
                            <td className={styles.muted}>{r.team ?? "—"}</td>
                            <td>{r.natural_bracket ?? "—"}</td>
                            <td>
                              {r.played_bracket ? (
                                <span className={styles.pillSm}>
                                  {r.played_bracket}
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td className={styles.num}>
                              {r.appearances}
                              {r.appearances_total !== r.appearances && (
                                <span className={styles.muted}>
                                  {" "}
                                  / {r.appearances_total}
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {s === "sin_datos" && (
                    <p className={styles.note}>
                      <Info size={12} aria-hidden="true" /> Menos de 3 partidos
                      en la temporada: se muestran, pero no se juzgan.
                    </p>
                  )}
                </div>
              ),
            )}
          </>
        )}
      </section>
    </div>
  );
}


/** `useSearchParams` obliga a una frontera de Suspense: sin ella el build de
 *  producción falla ("Missing Suspense boundary with useSearchParams"), y en
 *  desarrollo el problema no se ve porque las rutas se renderizan on-demand.
 *  Envolver acá además deja que el resto del árbol se prerenderice. */
export default function DesarrolloPage() {
  return (
    <Suspense fallback={<p className={styles.empty}>Cargando…</p>}>
      <DesarrolloContent />
    </Suspense>
  );
}
