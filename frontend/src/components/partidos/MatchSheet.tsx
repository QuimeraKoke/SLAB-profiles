"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Gavel, Users } from "lucide-react";

import { api } from "@/lib/api";
import MatchPitch, { type PitchSide } from "@/components/partidos/MatchPitch";
import styles from "./MatchSheet.module.css";

/** Federation match sheet (COMET) + SLAB's own GPS, cross-referenced.
 *  Renders nothing at all when no sheet has been synced for the match, so it's
 *  safe to mount unconditionally on the match page. */

interface TimelineRow {
  minute: number | null;
  /** COMET's own notation, already carrying added time: "45+3", "90+1". */
  display_minute: string | null;
  stoppage: number | null;
  extra: number | null;
  kind: "phase" | "event";
  team: string | null;
  player: string | null;
  shirt_number: number | null;
  assist: string | null;
  substituted_out: string | null;
  type: string;
  detail: string | null;
}
interface LineupSide {
  team: string | null;
  coach: string | null;
  formation: string | null;
  start_xi: { name: string | null; number: number | null; pos: string | null }[];
  substitutes: { name: string | null; number: number | null; pos: string | null }[];
}
interface SquadRow {
  player_id: string;
  player: string | null;
  shirt_number: number | null;
  status: "titular" | "ingreso" | "citado";
  captain: boolean;
  minutes_official: number;
  minutes_real: number | null;
  minute_in: number | null;
  minute_out: number | null;
  goals: number;
  assists: number;
  yellow: number;
  red: number;
  gps: null | {
    duration: number | null;
    distance: number | null;
    mpm: number | null;
    hsr: number | null;
    sprint: number | null;
    max_vel: number | null;
    m_per_official_min: number | null;
  };
}
interface StandingRow {
  team?: { name?: string };
  position?: number;
  played?: number;
  points?: number;
  goalsFor?: number;
  goalsAgainst?: number;
  highlight?: boolean;
}
interface H2HRow {
  dateTimeUTC?: number;
  homeTeam?: { name?: string };
  awayTeam?: { name?: string };
  homeTeamResult?: { current?: number | null };
  awayTeamResult?: { current?: number | null };
  competition?: { name?: string };
}
interface Sheet {
  has_sheet: boolean;
  synced_at?: string | null;
  header?: {
    competition: string | null; phase: string | null; round: string | null;
    status: string | null; status_long: string | null; venue: string | null;
    is_home: boolean | null; opponent: string | null;
    score: { home: number | null; away: number | null } | null;
    score_half_time: { home: number | null; away: number | null } | null;
    stoppage_first_half: number | null;
    stoppage_second_half: number | null;
    real_duration_minutes: number | null;
  };
  timeline?: TimelineRow[];
  lineups?: LineupSide[];
  referee?: string | null;
  match_officials?: { role: string | null; name: string | null }[];
  team_staff?: { role: string | null; name: string | null }[];
  squad?: SquadRow[];
  cross_check?: {
    with_gps: number; played: number;
    gps_without_official_minutes: string[];
    official_minutes_without_gps: string[];
    duration_mismatch: {
      player: string | null; minutes_official: number;
      minutes_real: number | null; gps_duration: number; issue: string;
    }[];
  };
  standings?: StandingRow[];
  head_to_head?: H2HRow[];
  pitch?: { ours: PitchSide; rival: PitchSide };
}

const STATUS_LABEL: Record<SquadRow["status"], string> = {
  titular: "Titular",
  ingreso: "Ingresó",
  citado: "Citado",
};

/** Goal / card / substitution get a glyph so the timeline scans quickly. */
function glyph(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("autogol")) return "⚽︎";
  if (t.includes("gol")) return "⚽";
  if (t.includes("amarilla")) return "🟨";
  if (t.includes("roja")) return "🟥";
  if (t.includes("cambio")) return "⇄";
  return "•";
}

function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("es-CL", { maximumFractionDigits: digits });
}

export default function MatchSheet({ eventId }: { eventId: string }) {
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<Sheet>(`/events/${eventId}/match-sheet`)
      .then((d) => {
        if (!cancelled) setSheet(d);
      })
      .catch(() => {
        if (!cancelled) setSheet(null);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  // Nothing synced → render nothing rather than an empty shell.
  if (!loaded || !sheet?.has_sheet) return null;

  const h = sheet.header!;
  const cc = sheet.cross_check!;
  const squad = sheet.squad ?? [];
  const warnings =
    (cc?.duration_mismatch?.length ?? 0) +
    (cc?.gps_without_official_minutes?.length ?? 0) +
    (cc?.official_minutes_without_gps?.length ?? 0);

  return (
    <section className={styles.wrap} aria-label="Ficha oficial del partido">
      {/* ── header ─────────────────────────────────────────────────────── */}
      <div className={styles.head}>
        <div>
          <h2 className={styles.h2}>Ficha oficial</h2>
          <p className={styles.sub}>
            {[h.competition, h.phase !== h.competition ? h.phase : null,
              h.round ? `Fecha ${h.round}` : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        {h.score && (
          <div className={styles.scoreBox}>
            <span className={styles.score}>
              {num(h.score.home)} – {num(h.score.away)}
            </span>
            {h.score_half_time && (
              <span className={styles.scoreHt}>
                {num(h.score_half_time.home)}–{num(h.score_half_time.away)} al
                descanso
              </span>
            )}
          </div>
        )}
      </div>
      <p className={styles.factRow}>
        {h.venue && <span>🏟 {h.venue}</span>}
        {sheet.referee && <span><Gavel size={12} aria-hidden="true" /> {sheet.referee}</span>}
        <span>{h.is_home ? "Local" : "Visita"}</span>
        {h.real_duration_minutes ? (
          <span title="Reglamentarios 90 más la adición de cada período">
            ⏱ {h.real_duration_minutes}&apos; reales (+{h.stoppage_first_half} 1T,
            +{h.stoppage_second_half} 2T)
          </span>
        ) : null}
        {h.status_long && <span>{h.status_long}</span>}
      </p>

      {/* ── cross-check warnings ───────────────────────────────────────── */}
      {warnings > 0 && (
        <div className={styles.warnBox} role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          <div>
            <strong>Descalces entre la ficha oficial y el GPS</strong>
            <ul className={styles.warnList}>
              {cc.duration_mismatch.map((m) => (
                <li key={`d-${m.player}`}>
                  <b>{m.player}</b>:{" "}
                  {m.minutes_real
                    ? `${m.minutes_real} min reales`
                    : `${m.minutes_official} min oficiales`}{" "}
                  vs {num(m.gps_duration, 1)} de GPS
                  {m.issue === "gps_mucho_menor" &&
                    " — la unidad pudo fallar o la sesión quedó mal asignada"}
                </li>
              ))}
              {cc.official_minutes_without_gps.length > 0 && (
                <li>
                  Con minutos oficiales y sin GPS:{" "}
                  {cc.official_minutes_without_gps.join(", ")}
                </li>
              )}
              {cc.gps_without_official_minutes.length > 0 && (
                <li>
                  Con GPS y sin minutos oficiales:{" "}
                  {cc.gps_without_official_minutes.join(", ")}
                </li>
              )}
            </ul>
          </div>
        </div>
      )}

      <div className={styles.grid}>
        {/* ── timeline ─────────────────────────────────────────────────── */}
        <div className={styles.card}>
          <h3 className={styles.h3}>Cronología</h3>
          <ol className={styles.timeline}>
            {(sheet.timeline ?? []).map((e, i) =>
              e.kind === "phase" ? (
                <li key={i} className={styles.phase}>
                  {e.type}
                </li>
              ) : (
                <li key={i} className={styles.tlRow}>
                  <span className={styles.min}>
                    {e.display_minute ? `${e.display_minute}'` : "—"}
                  </span>
                  <span className={styles.glyph} aria-hidden="true">
                    {glyph(e.type)}
                  </span>
                  <span className={styles.tlBody}>
                    <b>{e.player ?? "—"}</b>
                    {e.shirt_number ? (
                      <span className={styles.shirt}>#{e.shirt_number}</span>
                    ) : null}
                    <span className={styles.tlType}>{e.type}</span>
                    {e.substituted_out && (
                      <span className={styles.tlNote}>sale {e.substituted_out}</span>
                    )}
                    {e.assist && (
                      <span className={styles.tlNote}>asiste {e.assist}</span>
                    )}
                  </span>
                  {e.team && <span className={styles.tlTeam}>{e.team}</span>}
                </li>
              ),
            )}
          </ol>
        </div>

        {/* ── pitch (replaces the plain lineup list) ─────────────────── */}
        {sheet.pitch && (
          <div className={styles.card}>
            <h3 className={styles.h3}>Alineaciones en cancha</h3>
            <MatchPitch ours={sheet.pitch.ours} rival={sheet.pitch.rival} />
          </div>
        )}
      </div>

      {/* ── squad: status + GPS cross ───────────────────────────────────── */}
      <div className={styles.card}>
        <h3 className={styles.h3}>
          <Users size={14} aria-hidden="true" /> Plantel · oficial vs GPS
        </h3>
        <p className={styles.hint}>
          <b>Min oficiales</b> son los que publica la federación y topan en 90.
          <b> Min reales</b> suman la adición de cada período, y coinciden con el
          GPS con menos de 1 minuto de diferencia. <b>m/min oficial</b> normaliza
          la carga por el tiempo oficial, no por el medido.
        </p>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Jugador</th>
                <th>Estado</th>
                <th className={styles.r} title="Minutos que publica la federación (topan en 90)">
                  Min oficiales
                </th>
                <th className={styles.r} title="Reglamentarios más la adición realmente jugada">
                  Min reales
                </th>
                <th className={styles.r}>GPS min</th>
                <th className={styles.r}>Dist. (m)</th>
                <th className={styles.r}>m/min</th>
                <th className={styles.r} title="Metros por minuto oficial">m/min oficial</th>
                <th className={styles.r}>Vmax</th>
                <th className={styles.r}>G/A</th>
                <th className={styles.r}>T</th>
              </tr>
            </thead>
            <tbody>
              {squad.map((r) => (
                <tr key={r.player_id}>
                  <td className={styles.name}>
                    {r.shirt_number ? (
                      <span className={styles.shirtBox}>{r.shirt_number}</span>
                    ) : null}
                    {r.player}
                    {r.captain && <span className={styles.cap}>C</span>}
                  </td>
                  <td>
                    <span className={`${styles.badge} ${styles[r.status]}`}>
                      {STATUS_LABEL[r.status]}
                    </span>
                  </td>
                  <td className={styles.r}>
                    {r.minutes_official}
                    {r.minute_in ? (
                      <span className={styles.tlNote}>↑{r.minute_in}&apos;</span>
                    ) : null}
                    {r.minute_out ? (
                      <span className={styles.tlNote}>↓{r.minute_out}&apos;</span>
                    ) : null}
                  </td>
                  <td className={styles.r}>{num(r.minutes_real)}</td>
                  <td className={styles.r}>{num(r.gps?.duration, 1)}</td>
                  <td className={styles.r}>{num(r.gps?.distance)}</td>
                  <td className={styles.r}>{num(r.gps?.mpm)}</td>
                  <td className={`${styles.r} ${styles.strong}`}>
                    {num(r.gps?.m_per_official_min, 1)}
                  </td>
                  <td className={styles.r}>{num(r.gps?.max_vel, 1)}</td>
                  <td className={styles.r}>
                    {r.goals || r.assists ? `${r.goals}/${r.assists}` : "—"}
                  </td>
                  <td className={styles.r}>
                    {r.yellow ? "🟨".repeat(r.yellow) : ""}
                    {r.red ? "🟥" : ""}
                    {!r.yellow && !r.red ? "—" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── officials + tournament context ─────────────────────────────── */}
      <div className={styles.grid}>
        {(sheet.match_officials ?? []).length > 0 && (
          <div className={styles.card}>
            <h3 className={styles.h3}>Arbitraje y cuerpo técnico</h3>
            <ul className={styles.plainList}>
              {sheet.match_officials!.map((o, i) => (
                <li key={`o-${i}`}>
                  <span className={styles.role}>{o.role}</span> {o.name}
                </li>
              ))}
            </ul>
            {(sheet.team_staff ?? []).length > 0 && (
              <>
                <p className={styles.benchLabel}>Cuerpo técnico presente</p>
                <ul className={styles.plainList}>
                  {sheet.team_staff!.map((o, i) => (
                    <li key={`s-${i}`}>
                      <span className={styles.role}>{o.role}</span> {o.name}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        {((sheet.standings ?? []).length > 0 ||
          (sheet.head_to_head ?? []).length > 0) && (
          <div className={styles.card}>
            <h3 className={styles.h3}>Contexto del torneo</h3>
            {(sheet.standings ?? []).length > 0 && (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th className={styles.r}>#</th>
                      <th>Equipo</th>
                      <th className={styles.r}>PJ</th>
                      <th className={styles.r}>GF:GC</th>
                      <th className={styles.r}>Pts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sheet.standings!.slice(0, 8).map((s, i) => (
                      <tr
                        key={i}
                        className={s.highlight ? styles.hl : undefined}
                      >
                        <td className={styles.r}>{s.position}</td>
                        <td>{s.team?.name}</td>
                        <td className={styles.r}>{s.played}</td>
                        <td className={styles.r}>
                          {s.goalsFor}:{s.goalsAgainst}
                        </td>
                        <td className={`${styles.r} ${styles.strong}`}>
                          {s.points}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(sheet.head_to_head ?? []).length > 0 && (
              <>
                <p className={styles.benchLabel}>Historial reciente</p>
                <ul className={styles.plainList}>
                  {sheet.head_to_head!.slice(0, 6).map((m, i) => (
                    <li key={`h-${i}`}>
                      <span className={styles.role}>
                        {m.dateTimeUTC
                          ? new Date(m.dateTimeUTC).toLocaleDateString("es-CL")
                          : ""}
                      </span>
                      {m.homeTeam?.name} {num(m.homeTeamResult?.current)}–
                      {num(m.awayTeamResult?.current)} {m.awayTeam?.name}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
