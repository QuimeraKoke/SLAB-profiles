"use client";

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Info,
  ArrowDown,
  ArrowUp,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  TriageAlert,
  TriageAlertedMetric,
  TriageHistoryPoint,
  TriageLastMatch,
  TriageOtherMetric,
  TriageResponse,
} from "@/lib/types";
import styles from "./PlayerTriage.module.css";

interface Props {
  playerId: string;
}

/**
 * The new Resumen tab — a 4-section triage card answering "should I be
 * worried about this player today?". See `backend/api/triage.py` for the
 * data contract and selection rules. Built atop the existing `useToast`
 * + Alert types; renders alone (no widgets-engine dependency) so it's a
 * cheap drop-in replacement for the old ProfileSummary.
 */
export default function PlayerTriage({ playerId }: Props) {
  const [data, setData] = useState<TriageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) {
        setData(null);
        setError(null);
      }
    });
    api<TriageResponse>(`/players/${playerId}/triage`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "No se pudo cargar el resumen.");
      });
    return () => { cancelled = true; };
  }, [playerId]);

  if (error) {
    return <div className={styles.error} role="alert">{error}</div>;
  }
  if (!data) {
    return <div className={styles.muted}>Cargando resumen…</div>;
  }

  const generatedDate = new Date(data.generated_at);
  const generatedLabel = generatedDate.toLocaleString("es-CL", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <h2 className={styles.title}>Resumen del jugador</h2>
          <p className={styles.subtitle}>Datos al {generatedLabel}</p>
        </div>
      </header>

      <Section1Alerts alerts={data.alerts} />
      <Section2AlertedMetrics metrics={data.alerted_metrics} />
      <Section3OtherMetrics metrics={data.other_metrics} />
      <Section4LastMatch match={data.last_match} />
    </div>
  );
}

// ─── Section 1: active alerts (headline only) ──────────────────────────

function Section1Alerts({ alerts }: { alerts: TriageAlert[] }) {
  if (alerts.length === 0) {
    return (
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Alertas activas</h3>
        <p className={styles.empty}>Sin alertas — todo en orden.</p>
      </section>
    );
  }
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>
        Alertas activas <span className={styles.count}>({alerts.length})</span>
      </h3>
      <ul className={styles.alertList}>
        {alerts.map((a) => (
          <li key={a.id} className={`${styles.alertRow} ${styles[`sev_${a.severity}`]}`}>
            <SeverityIcon severity={a.severity} />
            <span className={styles.alertMessage}>{a.message}</span>
            <span className={styles.alertTime}>{relativeTime(a.last_fired_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Section 2: alerted metrics with previous reading ──────────────────

function Section2AlertedMetrics({ metrics }: { metrics: TriageAlertedMetric[] }) {
  if (metrics.length === 0) {
    // Don't go silently null — show a reassurance line. Helps the user
    // tell apart "report is loading" from "actually nothing to flag".
    return (
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Métricas alertadas</h3>
        <p className={styles.empty}>
          Sin métricas alertadas — los indicadores que sigues están en rango.
        </p>
      </section>
    );
  }
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>
        Métricas alertadas <span className={styles.sectionHint}>previo → actual</span>
      </h3>
      <table className={styles.table}>
        <colgroup>
          <col style={{ width: "auto" }} />
          <col style={{ width: "18%" }} />
          <col style={{ width: "18%" }} />
          <col style={{ width: "14%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>Métrica</th>
            <th className={styles.numCell}>Previo</th>
            <th className={styles.numCell}>Actual</th>
            <th className={styles.numCell}>Δ</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <MetricRow key={`${m.template_slug}-${m.field_key}`} m={m} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ─── Section 3: other metrics with 30-day sparkline ────────────────────

function Section3OtherMetrics({ metrics }: { metrics: TriageOtherMetric[] }) {
  if (metrics.length === 0) {
    return (
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Otras métricas recientes</h3>
        <p className={styles.empty}>
          Sin métricas con histórico suficiente para mostrar trayectoria.
        </p>
      </section>
    );
  }
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>
        Otras métricas recientes <span className={styles.sectionHint}>30 días</span>
      </h3>
      <p className={styles.fineprint}>
        Sólo se muestran campos con rangos de referencia o reglas de alerta configuradas.
      </p>
      <table className={styles.table}>
        <colgroup>
          <col style={{ width: "auto" }} />
          <col style={{ width: "264px" }} />
          <col style={{ width: "13%" }} />
          <col style={{ width: "13%" }} />
          <col style={{ width: "14%" }} />
        </colgroup>
        <thead>
          <tr>
            <th>Métrica</th>
            <th>Trayectoria</th>
            <th className={styles.numCell}>Previo</th>
            <th className={styles.numCell}>Actual</th>
            <th className={styles.numCell}>Δ</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={`${m.template_slug}-${m.field_key}`}>
              <td>
                <div className={styles.metricLabel}>{m.field_label}</div>
                <div className={styles.metricTpl}>{m.template_label}</div>
              </td>
              <td className={styles.sparkCell}>
                <Sparkline
                  points={m.history_30d}
                  unit={m.unit}
                  direction_of_good={m.direction_of_good}
                  delta={m.delta}
                />
              </td>
              <td className={styles.numCell}>
                {formatValue(m.previous_value, m.unit)}
              </td>
              <td className={styles.numCell}>
                {formatValue(m.current_value, m.unit)}
              </td>
              <td className={styles.numCell}>
                <DeltaBadge
                  delta={m.delta}
                  unit={m.unit}
                  direction_of_good={m.direction_of_good}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ─── Section 4: last match / citation status ───────────────────────────

function Section4LastMatch({ match }: { match: TriageLastMatch | null }) {
  if (!match) {
    return (
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>Último partido</h3>
        <p className={styles.empty}>No hay partidos en el calendario.</p>
      </section>
    );
  }
  const date = new Date(match.event_starts_at).toLocaleDateString("es-CL", {
    day: "2-digit", month: "short", year: "numeric",
  });

  // Roles where the player actually took the field.
  const playedRoles = new Set([
    "titular", "suplente_ingresa", "suplente_no_ingresa",
  ]);
  // Cited but didn't play (citado_no_vestir) — green is misleading
  // (coach reads it as "on the field"); render amber instead.
  const citedRoles = new Set(["citado_no_vestir", "promovido", "seleccion"]);
  const didPlay = match.match_role && playedRoles.has(match.match_role);
  const wasCited = match.match_role && citedRoles.has(match.match_role);

  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>
        {match.is_past ? "Último partido" : "Próximo partido"}
        <span className={styles.sectionHint}>· {date}</span>
      </h3>
      <div className={styles.matchCard}>
        <div className={styles.matchHeader}>
          <span className={styles.matchTitle}>{match.event_title}</span>
          {match.match_role_label && (
            <span
              className={`${styles.roleBadge} ${
                didPlay
                  ? styles.rolePlayed
                  : wasCited
                    ? styles.roleCited
                    : styles.roleAbsent
              }`}
            >
              {match.match_role_label}
            </span>
          )}
        </div>
        {didPlay && (match.minutes_played != null || match.goals != null) && (
          <div className={styles.matchStats}>
            {match.minutes_played != null && (
              <Stat label="Minutos" value={match.minutes_played} />
            )}
            {match.goals != null && match.goals > 0 && (
              <Stat label="Goles" value={match.goals} />
            )}
          </div>
        )}
        {match.performance.length > 0 && (
          <div className={styles.perfBlocks}>
            {match.performance.map((p) => (
              <PerformanceBlock key={p.template_slug} block={p} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────

function MetricRow({ m }: { m: TriageAlertedMetric }) {
  return (
    <tr>
      <td>
        <div className={styles.metricLabel}>{m.field_label}</div>
        <div className={styles.metricTpl}>{m.template_label}</div>
      </td>
      <td className={styles.numCell}>{formatValue(m.previous_value, m.unit)}</td>
      <td className={styles.numCell}>{formatValue(m.current_value, m.unit)}</td>
      <td className={styles.numCell}>
        <DeltaBadge
          delta={m.delta}
          unit={m.unit}
          direction_of_good={m.direction_of_good}
        />
      </td>
    </tr>
  );
}

function DeltaBadge({
  delta,
  unit,
  direction_of_good,
}: {
  delta: number | null;
  unit: string | null;
  direction_of_good: "up" | "down" | null;
}) {
  if (delta == null) return <span className={styles.deltaNeutral}>—</span>;
  if (Math.abs(delta) < 1e-9) return <span className={styles.deltaNeutral}>—</span>;

  const goingUp = delta > 0;
  // "Worse" if delta direction conflicts with direction_of_good. If
  // direction_of_good is unknown we render neutral.
  let isWorse: boolean | null = null;
  if (direction_of_good === "up") isWorse = !goingUp;
  if (direction_of_good === "down") isWorse = goingUp;

  const cls =
    isWorse === true ? styles.deltaWorse
    : isWorse === false ? styles.deltaBetter
    : styles.deltaNeutral;
  const Icon = goingUp ? ArrowUp : ArrowDown;
  // Strip trailing zeros for compactness ("0.43" not "0.43000").
  const numText = Math.abs(delta).toFixed(2).replace(/\.?0+$/, "");
  return (
    <span className={cls}>
      <Icon size={12} aria-hidden="true" />
      {unit ? `${numText} ${unit}` : numText}
    </span>
  );
}

function Sparkline({
  points,
  unit,
  direction_of_good,
  delta,
}: {
  points: TriageHistoryPoint[];
  unit: string | null;
  direction_of_good: "up" | "down" | null;
  /** previo → actual change — SAME signal the Δ chip uses, so the line color
   *  and the chip always agree (null/0 → neutral). */
  delta: number | null;
}) {
  // Index of the point under the cursor (null = not hovering). Per-row state
  // — each Sparkline owns its own hover so rows don't interfere.
  const [hover, setHover] = useState<number | null>(null);

  // Need at least 2 points to draw a line. Otherwise show a single dot
  // or a dash so the row stays visually balanced.
  if (points.length < 2) {
    return <span className={styles.sparkDot} aria-label="Sin trayectoria"></span>;
  }
  const W = 240;
  const H = 52;
  const PAD_X = 6;
  const PAD_Y = 10;
  const xs = points.map((_, i) => (i / (points.length - 1)) * (W - 2 * PAD_X) + PAD_X);
  const min = Math.min(...points.map((p) => p.value));
  const max = Math.max(...points.map((p) => p.value));
  const range = max - min || 1;
  const ys = points.map(
    (p) => H - PAD_Y - ((p.value - min) / range) * (H - 2 * PAD_Y),
  );
  const path = points
    .map((_, i) => `${i === 0 ? "M" : "L"} ${xs[i].toFixed(1)} ${ys[i].toFixed(1)}`)
    .join(" ");

  // Trend color must MATCH the Δ chip on the same row, so it uses the same
  // signal: the previo → actual `delta` (NOT first-vs-last of the window,
  // which could disagree with the chip). UP isn't always "good" — for
  // body-fat %, fatigue, RPE the good direction is down. Null/zero delta →
  // neutral gray, same as the chip.
  let isWorse: boolean | null = null;
  if (delta != null && Math.abs(delta) >= 1e-9) {
    const goingUp = delta > 0;
    if (direction_of_good === "up") isWorse = !goingUp;
    if (direction_of_good === "down") isWorse = goingUp;
  }
  const stroke =
    isWorse === true ? "#dc2626"
    : isWorse === false ? "#16a34a"
    : "#6b7280";

  const title = `${points.length} lecturas · min ${min.toFixed(1)}${unit ?? ""} · max ${max.toFixed(1)}${unit ?? ""}`;

  // Map a pointer X (relative to the SVG) to the nearest data point.
  const nearest = (offsetX: number): number => {
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < xs.length; i++) {
      const d = Math.abs(xs[i] - offsetX);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    return best;
  };

  const hi = hover != null && hover < points.length ? hover : null;
  // Keep the tooltip from spilling off the cell edges.
  const tipAlign = hi == null ? "" : xs[hi] < 46 ? styles.tipLeft : xs[hi] > W - 46 ? styles.tipRight : "";

  return (
    <div className={styles.trajWrap} style={{ width: W, height: H }}>
      <svg
        width={W}
        height={H}
        role="img"
        aria-label={title}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          setHover(nearest(e.clientX - rect.left));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <title>{title}</title>
        {hi != null && (
          <line
            x1={xs[hi]} y1={2} x2={xs[hi]} y2={H - 2}
            stroke="#cbd5e1" strokeWidth="1" strokeDasharray="2 2"
          />
        )}
        <path d={path} fill="none" stroke={stroke} strokeWidth="1.75" />
        {points.map((_, i) => (
          <circle
            key={i}
            cx={xs[i]}
            cy={ys[i]}
            r={i === hi ? 3.5 : 1.75}
            fill={stroke}
            opacity={hi == null || i === hi ? 1 : 0.45}
          />
        ))}
      </svg>
      {hi != null && (
        <div className={`${styles.trajTooltip} ${tipAlign}`} style={{ left: xs[hi], top: ys[hi] }}>
          <span className={styles.trajTipVal}>{formatValue(points[hi].value, unit)}</span>
          <span className={styles.trajTipDate}>{shortDate(points[hi].recorded_at)}</span>
        </div>
      )}
    </div>
  );
}

function SeverityIcon({ severity }: { severity: TriageAlert["severity"] }) {
  if (severity === "critical")
    return <AlertCircle size={14} aria-hidden="true" className={styles.iconCritical} />;
  if (severity === "warning")
    return <AlertTriangle size={14} aria-hidden="true" className={styles.iconWarning} />;
  return <Info size={14} aria-hidden="true" className={styles.iconInfo} />;
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}

function PerformanceBlock({
  block,
}: {
  block: { template_slug: string; template_label: string; result_data: Record<string, unknown> };
}) {
  // Pick the first 4 numeric-looking entries as "headline" stats. The
  // result_data shape varies wildly across templates; without per-template
  // knowledge we just surface what's there.
  const entries = Object.entries(block.result_data)
    .filter(([, v]) => typeof v === "number")
    .slice(0, 4);
  if (entries.length === 0) return null;
  return (
    <div className={styles.perfBlock}>
      <div className={styles.perfTitle}>{block.template_label}</div>
      <div className={styles.perfRow}>
        {entries.map(([k, v]) => (
          <Stat key={k} label={prettifyKey(k)} value={String(v)} />
        ))}
      </div>
    </div>
  );
}

// ─── helpers ───────────────────────────────────────────────────────────

function formatValue(value: number | null, unit: string | null): string {
  if (value == null) return "—";
  const rounded = Math.abs(value) < 10 ? value.toFixed(2) : value.toFixed(1);
  const stripped = rounded.replace(/\.?0+$/, "");
  return unit ? `${stripped} ${unit}` : stripped;
}

function shortDate(iso: string): string {
  // "18 jun" — compact label for the trajectory tooltip.
  return new Date(iso).toLocaleDateString("es-CL", { day: "numeric", month: "short" });
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = (now - then) / 1000;
  if (diff < 60) return "hace instantes";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return `hace ${Math.floor(diff / 86400)} días`;
}

function prettifyKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
