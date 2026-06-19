"use client";

import React, { useEffect, useState } from "react";

import { api } from "@/lib/api";
import styles from "./MatchDataPanel.module.css";

interface Lineup {
  team: string;
  team_id: number;
  formation: string | null;
  coach: string | null;
  start_xi: { name: string; number: number | null; pos: string | null }[];
  substitutes: { name: string; number: number | null; pos: string | null }[];
}
interface MatchEvent {
  minute: number | null;
  extra: number | null;
  team: string | null;
  player: string | null;
  assist: string | null;
  type: string | null;
  detail: string | null;
}
interface TeamStats {
  team: string | null;
  stats: { type: string | null; value: unknown }[];
}
interface MatchData {
  has_data: boolean;
  competition: string | null;
  status: string | null;
  score: { home: number | null; away: number | null } | null;
  synced_at: string | null;
  lineups: Lineup[];
  events: MatchEvent[];
  team_statistics: TeamStats[];
}

// Key stats to surface (in order) when present.
const KEY_STATS = [
  "Ball Possession", "Total Shots", "Shots on Goal", "Total passes",
  "Passes accurate", "Corner Kicks", "Fouls", "Yellow Cards",
];

/** Imported results + tactical data (API-Football) for a match. Renders
 *  nothing when no data has been synced — so it's invisible on matches
 *  that weren't imported. */
export default function MatchDataPanel({ eventId }: { eventId: string }) {
  const [data, setData] = useState<MatchData | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<MatchData>(`/events/${eventId}/match-data`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [eventId]);

  if (!data || !data.has_data) return null;

  return (
    <section className={styles.panel}>
      <header className={styles.head}>
        <div>
          <div className={styles.title}>Datos del partido</div>
          <div className={styles.sub}>
            {data.competition ?? "—"} · API-Football
            {data.synced_at && ` · sincronizado ${new Date(data.synced_at).toLocaleDateString("es-CL")}`}
          </div>
        </div>
        {data.score && (
          <div className={styles.score}>
            {data.score.home ?? "–"} <span>:</span> {data.score.away ?? "–"}
          </div>
        )}
      </header>

      {data.lineups.length > 0 && (
        <div className={styles.lineups}>
          {data.lineups.map((l) => (
            <div key={l.team_id} className={styles.lineup}>
              <div className={styles.lineupHead}>
                <span className={styles.teamName}>{l.team}</span>
                {l.formation && <span className={styles.formation}>{l.formation}</span>}
              </div>
              {l.coach && <div className={styles.coach}>DT: {l.coach}</div>}
              <ol className={styles.xi}>
                {l.start_xi.map((p, i) => (
                  <li key={i}>
                    <span className={styles.num}>{p.number ?? "–"}</span>
                    {p.name}
                    {p.pos && <span className={styles.pos}>{p.pos}</span>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      )}

      {data.team_statistics.length === 2 && (
        <div className={styles.statsBlock}>
          <div className={styles.statsHead}>
            <span>{data.team_statistics[0].team}</span>
            <span className={styles.statsLabelCol}>Estadística</span>
            <span>{data.team_statistics[1].team}</span>
          </div>
          {mergedStats(data.team_statistics).map((row) => (
            <div key={row.type} className={styles.statRow}>
              <span className={styles.statHome}>{fmt(row.home)}</span>
              <span className={styles.statType}>{row.type}</span>
              <span className={styles.statAway}>{fmt(row.away)}</span>
            </div>
          ))}
        </div>
      )}

      {data.events.length > 0 && (
        <div className={styles.timeline}>
          <div className={styles.timelineHead}>Eventos</div>
          {data.events.map((e, i) => (
            <div key={i} className={styles.event}>
              <span className={styles.min}>{e.minute != null ? `${e.minute}'` : "—"}</span>
              <span className={`${styles.evDot} ${dotClass(e)}`} />
              <span className={styles.evText}>
                <strong>{e.player ?? "—"}</strong>
                {e.detail ? ` · ${e.detail}` : e.type ? ` · ${e.type}` : ""}
                {e.team && <span className={styles.evTeam}> ({e.team})</span>}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function mergedStats(teams: TeamStats[]): { type: string; home: unknown; away: unknown }[] {
  const [a, b] = teams;
  const byTypeA = new Map(a.stats.map((s) => [s.type, s.value]));
  const byTypeB = new Map(b.stats.map((s) => [s.type, s.value]));
  const order = KEY_STATS.filter((t) => byTypeA.has(t) || byTypeB.has(t));
  // Append any other stats not in the curated list.
  for (const s of a.stats) if (s.type && !order.includes(s.type)) order.push(s.type);
  return order.map((t) => ({ type: t, home: byTypeA.get(t), away: byTypeB.get(t) }));
}

function fmt(v: unknown): string {
  if (v == null) return "–";
  return String(v);
}

function dotClass(e: MatchEvent): string {
  const t = (e.type || "").toLowerCase();
  const d = (e.detail || "").toLowerCase();
  if (t === "goal") return styles.dotGoal;
  if (d.includes("red")) return styles.dotRed;
  if (t === "card") return styles.dotYellow;
  if (t === "subst") return styles.dotSub;
  return styles.dotOther;
}
